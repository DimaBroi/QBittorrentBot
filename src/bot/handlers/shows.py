import logging

from aiogram import F
from aiogram.dispatcher.router import Router
from aiogram.filters import Command, CommandObject, Filter
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from src.bot.filters import HasRole, IsAuthorizedUser, IsCommand
from src.bot.filters.callbacks import AddShowMenu, DelShowGo, DelShowMenu, DelShowMode, DelShowPick, ShowAdd, ShowPick
from src.client_manager.client_repo import ClientRepo
from src.redis_helper.wrapper import RedisWrapper
from src.settings import Settings
from src.settings.enums import UserRolesEnum
from src.sonarr.client import SonarrClient, SonarrError
from src.sonarr.utils import (
    DELETE_MODES, MAX_RESULTS, MAX_SERIES, build_add_payload, delete_confirmation, download_hashes, filter_series,
    parse_show_name, pick_profile, series_label, show_label,
)
from src.utils import get_user_from_config

SONARR_CATEGORY = "sonarr"   # only torrents in this qBittorrent category are ever deleted together with a show

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

    # ---- removing a show (administrators only, like the Delete menu) ----------------------------------------------

    def is_admin(user_id: int, settings: Settings) -> bool:
        user = get_user_from_config(user_id, settings)
        return bool(user) and user.role == UserRolesEnum.Administrator

    async def series_buttons(settings: Settings, term=None):
        """(text, keyboard) listing the series that match `term`, or (message, None) when there is nothing to pick."""
        series = await client(settings).series_list()
        matches = filter_series(series, term)
        if not matches:
            return (f"No show in Sonarr matches: {term}" if term else "Sonarr has no shows yet."), None
        rows = [[InlineKeyboardButton(text=series_label(s), callback_data=DelShowPick(sid=s["id"]).pack())] for s in matches]
        rows.append([InlineKeyboardButton(text="✖ Cancel", callback_data=DelShowMode(sid=0, mode="x").pack())])
        more = "\nMore shows exist: use /delshow <name> to narrow the list." if len(series) > len(matches) and not term else ""
        return f"Which show do you want to remove?{more}", InlineKeyboardMarkup(inline_keyboard=rows)

    @router.message(Command("delshow"), IsAuthorizedUser())
    async def delshow_command(message: Message, command: CommandObject, settings: Settings) -> None:
        if not settings.sonarr:
            await message.reply("Sonarr is not set up. Add a sonarr section to the bot's config.yml.", parse_mode=None)
            return
        if not is_admin(message.from_user.id, settings):
            await message.reply("Removing shows is for administrators only.", parse_mode=None)
            return
        try:
            text, markup = await series_buttons(settings, parse_show_name(command.args))
        except SonarrError as e:
            await message.reply(f"Sonarr problem: {e}", parse_mode=None)
            return
        await message.reply(text, reply_markup=markup, parse_mode=None)

    @router.callback_query(DelShowMenu.filter(), HasRole(UserRolesEnum.Administrator))
    async def delshow_menu(callback_query: CallbackQuery, settings: Settings) -> None:
        if not settings.sonarr:
            await callback_query.answer("Sonarr is not set up", show_alert=True)
            return
        try:
            text, markup = await series_buttons(settings)
        except SonarrError as e:
            await callback_query.answer(f"Sonarr problem: {e}"[:190], show_alert=True)
            return
        await callback_query.answer()
        await callback_query.message.answer(text, reply_markup=markup, parse_mode=None)

    @router.callback_query(DelShowPick.filter(), HasRole(UserRolesEnum.Administrator))
    async def delshow_picked(callback_query: CallbackQuery, callback_data: DelShowPick) -> None:
        sid = callback_data.sid
        rows = [
            [InlineKeyboardButton(text="🗂 Remove from Sonarr, keep files", callback_data=DelShowMode(sid=sid, mode="k").pack())],
            [InlineKeyboardButton(text="🗑 Remove + delete episode files", callback_data=DelShowMode(sid=sid, mode="f").pack())],
            [InlineKeyboardButton(text="🗑 Remove + delete files + torrents", callback_data=DelShowMode(sid=sid, mode="t").pack())],
            [InlineKeyboardButton(text="✖ Cancel", callback_data=DelShowMode(sid=sid, mode="x").pack())],
        ]
        await callback_query.message.edit_text("What should happen to it?", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode=None)
        await callback_query.answer()

    @router.callback_query(DelShowMode.filter(), HasRole(UserRolesEnum.Administrator))
    async def delshow_mode(callback_query: CallbackQuery, callback_data: DelShowMode, settings: Settings) -> None:
        if callback_data.mode == "x":
            await callback_query.message.edit_text("Cancelled.", parse_mode=None)
            await callback_query.answer()
            return
        try:
            series = next((s for s in await client(settings).series_list() if s["id"] == callback_data.sid), None)
        except SonarrError as e:
            await callback_query.message.edit_text(f"Sonarr problem: {e}", parse_mode=None)
            await callback_query.answer()
            return
        if not series:
            await callback_query.message.edit_text("That show is no longer in Sonarr.", parse_mode=None)
            await callback_query.answer()
            return
        rows = [[InlineKeyboardButton(text="✅ Yes, do it", callback_data=DelShowGo(sid=callback_data.sid, mode=callback_data.mode).pack())],
                [InlineKeyboardButton(text="✖ Cancel", callback_data=DelShowMode(sid=callback_data.sid, mode="x").pack())]]
        await callback_query.message.edit_text(delete_confirmation(callback_data.mode, series_label(series)),
                                               reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode=None)
        await callback_query.answer()

    @router.callback_query(DelShowGo.filter(), HasRole(UserRolesEnum.Administrator))
    async def delshow_go(callback_query: CallbackQuery, callback_data: DelShowGo, settings: Settings) -> None:
        async def finish(text: str) -> None:
            await callback_query.message.edit_text(text, parse_mode=None)
            await callback_query.answer()

        if callback_data.mode not in DELETE_MODES or not settings.sonarr:
            await finish("Nothing done.")
            return

        sonarr = client(settings)
        try:
            series = next((s for s in await sonarr.series_list() if s["id"] == callback_data.sid), None)
            if not series:
                await finish("That show is no longer in Sonarr.")
                return
            name = series_label(series)
            # the torrent hashes come from the history, which disappears together with the series
            hashes = download_hashes(await sonarr.series_history(callback_data.sid)) if callback_data.mode == "t" else set()
            await sonarr.delete_series(callback_data.sid, delete_files=callback_data.mode in ("f", "t"))
        except SonarrError as e:
            logger.warning(f"Remove show failed: {e}")
            await finish(f"Could not remove the show: {e}")
            return

        lines = [f"✅ Removed {name} from Sonarr."]
        if callback_data.mode in ("f", "t"):
            lines.append("Episode files deleted.")
        if callback_data.mode == "t":
            removed = 0
            qbt = ClientRepo.get_client_manager(settings.client.type)(settings)
            for torrent_hash in sorted(hashes):
                try:
                    torrent = await qbt.get_torrent(torrent_hash)
                    if torrent and torrent.category == SONARR_CATEGORY:
                        await qbt.delete_one_data(torrent_hash)
                        removed += 1
                except Exception as e:
                    logger.warning(f"Could not delete torrent {torrent_hash}: {e}")
            lines.append(f"Torrents deleted: {removed} of {len(hashes)}.")
        await finish("\n".join(lines))

    return router
