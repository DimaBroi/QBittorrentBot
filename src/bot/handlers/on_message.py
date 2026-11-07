import json
import logging
import tempfile

from aiogram import F
from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.dispatcher.router import Router
from aiogram.utils.i18n import gettext as _

from src.client_manager.client_repo import ClientRepo
from src.settings import Settings
from src.bot.filters import IsAuthorizedUser, IsCommand
from src.bot.filters.callbacks import PendingAdd
from src.redis_helper.wrapper import RedisWrapper

from .add_utils import (
    CANCEL, PENDING_TTL, category_choices, encode_pending, magnet_links, pending_key, pending_title,
    safe_torrent_name,
)
from .common import send_menu


logger = logging.getLogger(__name__)


def get_router():
    router = Router()

    async def on_magnet(message: Message, redis: RedisWrapper, bot: Bot, settings: Settings):
        if message.text.startswith("magnet:?xt"):
            magnet_link = message.text.split("\n")
            category = (await redis.get(f"action:{message.from_user.id}")).split("#")[1]

            repository_class = ClientRepo.get_client_manager(settings.client.type)
            response = await repository_class(settings).add_magnet(
                magnet_link=magnet_link,
                category=category
            )

            if not response:
                await message.reply(_("Unable to add magnet link"))
                return

            await send_menu(bot, redis, settings, message.chat.id, message.message_id)
            await redis.delete(f"action:{message.from_user.id}")

        else:
            await message.reply(
                _("This magnet link is invalid! Retry")
            )


    async def on_torrent(message: Message, redis: RedisWrapper, bot: Bot, settings: Settings):
        if ".torrent" in message.document.file_name:
            with tempfile.TemporaryDirectory() as tempdir:
                name = f"{tempdir}/{message.document.file_name}"

                action = await redis.get(f"action:{message.from_user.id}") or ""
                category = action.split("#")[1] if action else None

                file = await bot.get_file(message.document.file_id)
                file_path = file.file_path
                await bot.download_file(file_path, name)

                repository_class = ClientRepo.get_client_manager(settings.client.type)
                response = await repository_class(settings).add_torrent(file_name=name, category=category)

                if not response:
                    await message.reply(_("Unable to add torrent file"))
                    return

            if not action:
                pass
                #await list_categories(bot, message.chat.id, message.message_id, settings, f"torrent_cat:{response}")
                #await redis.set(f"action:{message.from_user.id}", None)
                #return

            await send_menu(bot, redis, settings, message.chat.id, message.message_id)
            await redis.delete(f"action:{message.from_user.id}")

        else:
            await message.reply(
                _("This is not a torrent file! Retry")
            )


    async def on_category_name(message: Message, redis: RedisWrapper):
        await redis.set(f"action:{message.from_user.id}", f"category_dir#{message.text}")
        await message.reply(
            _("Please, send the path for the category {category_name}"
                .format(
                    category_name=message.text
                )
            )
        )


    async def on_category_directory(message: Message, action, redis: RedisWrapper, bot: Bot, settings: Settings):
        name: str = (await redis.get(f"action:{message.from_user.id}")).split("#")[1]

        repository_class = ClientRepo.get_client_manager(settings.client.type)

        if "modify" in action:
            await repository_class(settings).edit_category(name=name, save_path=message.text.replace("\\", ""))
            await send_menu(bot, redis, settings, message.chat.id, message.message_id)
            return

        await repository_class(settings).create_category(name=name, save_path=message.text.replace("\\", ""))
        await send_menu(bot, redis, settings, message.chat.id, message.message_id)


    async def ask_category(message: Message, redis: RedisWrapper, settings: Settings, pending: dict) -> None:
        """A magnet/.torrent arrived without the Add buttons: ask which category (= folder) it belongs to."""
        repository_class = ClientRepo.get_client_manager(settings.client.type)
        categories = await repository_class(settings).get_categories()

        buttons = [InlineKeyboardButton(text=label, callback_data=PendingAdd(choice=choice).pack())
                   for label, choice in category_choices(categories)]
        rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
        rows.append([InlineKeyboardButton(text=_("✖ Cancel"), callback_data=PendingAdd(choice=CANCEL).pack())])

        sent = await message.reply(
            _("📥 {title}\n\nWhich category is this? It decides the folder.").format(title=pending_title(pending)),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
            parse_mode=None,  # titles may contain markdown characters
        )
        await redis.set(pending_key(message.chat.id, sent.message_id), json.dumps(pending), ex=PENDING_TTL)

    async def on_dropped_torrent(message: Message, redis: RedisWrapper, settings: Settings) -> None:
        file_name = message.document.file_name or ""
        if ".torrent" not in file_name:
            await message.reply(_("This is not a torrent file! Retry"))
            return
        await ask_category(message, redis, settings, json.loads(
            encode_pending("torrent", file_id=message.document.file_id, file_name=safe_torrent_name(file_name))))

    async def on_dropped_magnet(message: Message, redis: RedisWrapper, settings: Settings, links: list) -> None:
        await ask_category(message, redis, settings, json.loads(encode_pending("magnet", links=links)))

    @router.message(~F.from_user.is_bot, ~IsCommand(), IsAuthorizedUser())
    async def on_message(message: Message, redis: RedisWrapper, bot: Bot, settings: Settings) -> None:
        action = await redis.get(f"action:{message.from_user.id}") or ""

        if message.document and not action:  # a .torrent dropped into the chat: ask for its category
            await on_dropped_torrent(message, redis, settings)

        elif not action and magnet_links(message.text):  # a magnet pasted into the chat: ask for its category
            await on_dropped_magnet(message, redis, settings, magnet_links(message.text))

        elif "magnet" in action:
            await on_magnet(message, redis, bot, settings)

        elif "torrent" in action and message.document:
            await on_torrent(message, redis, bot, settings)

        elif action == "category_name":
            await on_category_name(message, redis)

        elif "category_dir" in action:
            await on_category_directory(message, action, redis, bot, settings)

        else:
            await message.reply(
                _("The command does not exist")
            )

    return router
