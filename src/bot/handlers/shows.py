import logging

from aiogram import F
from aiogram.dispatcher.router import Router
from aiogram.filters import Command, CommandObject, Filter
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from src.bot.filters import HasRole, IsAuthorizedUser, IsCommand
from src.bot.filters.callbacks import AddShowMenu, ShowAdd, ShowPick
from src.redis_helper.wrapper import RedisWrapper
from src.settings import Settings
from src.settings.enums import UserRolesEnum
from src.sonarr.client import SonarrClient, SonarrError
from src.sonarr.utils import MAX_RESULTS, build_add_payload, parse_show_name, pick_profile, show_label
from src.utils import get_user_from_config

logger = logging.getLogger(__name__)

ACTION = "addshow"   # redis "action:<user>" value while the bot waits for a show name
ASK_NAME = "Send the show name, for example: Yaga"


class AwaitingShowName(Filter):
    async def __call__(self, message: Message, redis: RedisWrapper) -> bool:
        return (await redis.get(f"action:{message.from_user.id}")) == ACTION


def get_router():
    router = Router()

    def client(settings: Settings):
        return SonarrClient(settings.sonarr.url, settings.sonarr.api_key) if settings.sonarr else None

    def can_add(user_id: int, settings: Settings) -> bool:
        user = get_user_from_config(user_id, settings)
        return bool(user) and user.role in (UserRolesEnum.Manager, UserRolesEnum.Administrator)

    async def guard(message: Message, settings: Settings) -> bool:
        if not settings.sonarr:
            await message.reply("Sonarr is not set up. Add a sonarr section to the bot's config.yml.", parse_mode=None)
            return False
        if not can_add(message.from_user.id, settings):
            await message.reply("Adding shows is for managers and administrators.", parse_mode=None)
            return False
        return True

    async def search(message: Message, settings: Settings, term: str) -> None:
        """Look the name up in Sonarr and show the matches as buttons."""
        sonarr = client(settings)
        try:
            results = (await sonarr.lookup(term))[:MAX_RESULTS]
            existing = await sonarr.existing_tvdb_ids()
        except SonarrError as e:
            await message.reply(f"Sonarr problem: {e}", parse_mode=None)
            return

        results = [r for r in results if r.get("tvdbId")]
        if not results:
            await message.reply(f"No series found for: {term}", parse_mode=None)
            return

        rows = [[InlineKeyboardButton(text=show_label(r, existing), callback_data=ShowPick(tvdb=r["tvdbId"]).pack())]
                for r in results]
        rows.append([InlineKeyboardButton(text="✖ Cancel", callback_data=ShowAdd(tvdb=0, mode="x").pack())])
        await message.reply(f"Results for: {term}\n(✓ = already in Sonarr)",
                            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode=None)

    @router.message(Command("addshow"), IsAuthorizedUser())
    async def addshow_command(message: Message, command: CommandObject, settings: Settings, redis: RedisWrapper) -> None:
        if not await guard(message, settings):
            return
        term = parse_show_name(command.args)
        if not term:
            await redis.set(f"action:{message.from_user.id}", ACTION, ex=600)
            await message.reply(ASK_NAME, parse_mode=None)
            return
        await redis.delete(f"action:{message.from_user.id}")
        await search(message, settings, term)

    @router.message(F.text, ~IsCommand(), IsAuthorizedUser(), AwaitingShowName())
    async def show_name_message(message: Message, settings: Settings, redis: RedisWrapper) -> None:
        await redis.delete(f"action:{message.from_user.id}")
        term = parse_show_name(message.text)
        if term and await guard(message, settings):
            await search(message, settings, term)

    @router.callback_query(AddShowMenu.filter(), HasRole(UserRolesEnum.Administrator))
    @router.callback_query(AddShowMenu.filter(), HasRole(UserRolesEnum.Manager))
    async def addshow_menu(callback_query: CallbackQuery, settings: Settings, redis: RedisWrapper) -> None:
        if not settings.sonarr:
            await callback_query.answer("Sonarr is not set up", show_alert=True)
            return
        await redis.set(f"action:{callback_query.from_user.id}", ACTION, ex=600)
        await callback_query.answer()
        await callback_query.message.answer(ASK_NAME, parse_mode=None)

    @router.callback_query(ShowPick.filter(), HasRole(UserRolesEnum.Administrator))
    @router.callback_query(ShowPick.filter(), HasRole(UserRolesEnum.Manager))
    async def show_picked(callback_query: CallbackQuery, callback_data: ShowPick) -> None:
        """Second step: which episodes should Sonarr get?"""
        tvdb = callback_data.tvdb
        rows = [
            [InlineKeyboardButton(text="📥 All episodes (download everything)", callback_data=ShowAdd(tvdb=tvdb, mode="a").pack())],
            [InlineKeyboardButton(text="🆕 New episodes only", callback_data=ShowAdd(tvdb=tvdb, mode="f").pack())],
            [InlineKeyboardButton(text="✖ Cancel", callback_data=ShowAdd(tvdb=tvdb, mode="x").pack())],
        ]
        await callback_query.message.edit_text("Which episodes do you want?",
                                               reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode=None)
        await callback_query.answer()

    @router.callback_query(ShowAdd.filter(), HasRole(UserRolesEnum.Administrator))
    @router.callback_query(ShowAdd.filter(), HasRole(UserRolesEnum.Manager))
    async def show_add(callback_query: CallbackQuery, callback_data: ShowAdd, settings: Settings) -> None:
        async def finish(text: str) -> None:
            await callback_query.message.edit_text(text, parse_mode=None)
            await callback_query.answer()

        if callback_data.mode == "x":
            await finish("Cancelled.")
            return
        if not settings.sonarr:
            await finish("Sonarr is not set up.")
            return

        sonarr = client(settings)
        try:
            if callback_data.tvdb in await sonarr.existing_tvdb_ids():
                await finish("Already in Sonarr.")
                return
            item = await sonarr.lookup_tvdb(callback_data.tvdb)
            profile = pick_profile(await sonarr.quality_profiles(), settings.sonarr.quality_profile)
            if not item or not profile:
                await finish("Could not read the series or a quality profile from Sonarr.")
                return
            payload = build_add_payload(item, settings.sonarr.root_folder, profile["id"], callback_data.mode)
            await sonarr.add_series(payload)
        except SonarrError as e:
            logger.warning(f"Add show failed: {e}")
            await finish(f"Could not add the show: {e}")
            return

        name = f"{item.get('title')} ({item.get('year')})"
        if callback_data.mode == "a":
            await finish(f"✅ Added {name}\nSonarr is searching for all episodes now; they appear in qBittorrent shortly.")
        else:
            await finish(f"✅ Added {name}\nNew episodes will download as they air.")

    return router
