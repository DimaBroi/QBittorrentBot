from aiogram.filters.callback_data import CallbackData


class AddShowMenu(CallbackData, prefix="addshow_menu"):
    pass


class ShowPick(CallbackData, prefix="showpick"):
    tvdb: int


class ShowAdd(CallbackData, prefix="showadd"):
    tvdb: int
    mode: str      # 'a' all episodes, 'f' new episodes only, 'x' cancel
