import logging
import tempfile

from aiogram import Bot, Router
from aiogram.types import CallbackQuery
from aiogram.utils.i18n import gettext as _

from src.client_manager.client_repo import ClientRepo
from src.settings import Settings
from src.settings.user import User
from src.settings.enums import UserRolesEnum

from src.bot.filters import HasRole
from src.bot.filters.callbacks import AddMagnet, AddTorrent, PendingAdd
from src.bot.handlers.add_utils import (
    CANCEL, NO_CATEGORY, decode_pending, pending_key, pending_title, safe_torrent_name,
)
from src.bot.handlers.rss_utils import find_by_id

from src.redis_helper.wrapper import RedisWrapper

logger = logging.getLogger(__name__)


def get_router():
    router = Router()

    @router.callback_query(AddMagnet.filter(), HasRole(UserRolesEnum.Administrator))
    @router.callback_query(AddMagnet.filter(), HasRole(UserRolesEnum.Manager))
    async def add_magnet_callback(callback_query: CallbackQuery, callback_data: AddMagnet, bot: Bot, redis: RedisWrapper, user: User) -> None:
        print(callback_data.pack())
        await redis.set(f"action:{callback_query.from_user.id}", f"magnet#{callback_data.category}")
        await bot.answer_callback_query(callback_query.id, _("Send a magnet link"))


    @router.callback_query(AddTorrent.filter(), HasRole(UserRolesEnum.Administrator))
    @router.callback_query(AddTorrent.filter(), HasRole(UserRolesEnum.Manager))
    async def add_torrent_callback(callback_query: CallbackQuery, callback_data: AddTorrent, bot: Bot, redis: RedisWrapper, user: User) -> None:
        await redis.set(f"action:{callback_query.from_user.id}", f"torrent#{callback_data.category}")
        await bot.answer_callback_query(callback_query.id, _("Send a torrent file"))


    @router.callback_query(PendingAdd.filter(), HasRole(UserRolesEnum.Administrator))
    @router.callback_query(PendingAdd.filter(), HasRole(UserRolesEnum.Manager))
    async def pending_add_callback(callback_query: CallbackQuery, callback_data: PendingAdd, bot: Bot, redis: RedisWrapper, settings: Settings, user: User) -> None:
        """The user picked a category for a magnet/.torrent they dropped into the chat: add it now."""
        chat_id = callback_query.message.chat.id
        message_id = callback_query.message.message_id
        key = pending_key(chat_id, message_id)

        async def finish(text: str) -> None:
            await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, parse_mode=None)

        pending = decode_pending(await redis.get(key))
        if pending is None:
            await finish(_("This request expired. Send the magnet or file again."))
            await callback_query.answer()
            return

        if callback_data.choice == CANCEL:
            await redis.delete(key)
            await finish(_("Cancelled: {title}").format(title=pending_title(pending)))
            await callback_query.answer()
            return

        repository_class = ClientRepo.get_client_manager(settings.client.type)
        category = None
        if callback_data.choice != NO_CATEGORY:
            categories = await repository_class(settings).get_categories() or {}
            category = find_by_id(list(categories), callback_data.choice)
            if category is None:  # deleted since the prompt was shown: keep the request so the user can pick again
                await callback_query.answer(_("That category no longer exists"), show_alert=True)
                return

        if pending["kind"] == "magnet":
            ok = await repository_class(settings).add_magnet(magnet_link=pending["links"], category=category)
        else:
            with tempfile.TemporaryDirectory() as tempdir:
                path = f"{tempdir}/{safe_torrent_name(pending.get('file_name'))}"
                file = await bot.get_file(pending["file_id"])
                await bot.download_file(file.file_path, path)
                ok = await repository_class(settings).add_torrent(file_name=path, category=category)

        await redis.delete(key)
        title = pending_title(pending)
        if ok:
            await finish(_("✅ Added: {title}\nCategory: {category}").format(title=title, category=category or _("none")))
        else:
            await finish(_("❌ Could not add: {title}").format(title=title))
        await callback_query.answer()

    return router
