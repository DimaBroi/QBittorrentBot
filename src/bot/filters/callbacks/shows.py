from aiogram.filters.callback_data import CallbackData


class AddShowMenu(CallbackData, prefix="addshow_menu"):
    pass


class ShowPick(CallbackData, prefix="showpick"):
    tvdb: int


class ShowAdd(CallbackData, prefix="showadd"):
    tvdb: int
    mode: str      # 'a' all episodes, 'f' new episodes only, 'x' cancel


class DelShowMenu(CallbackData, prefix="delshow_menu"):
    pass


class DelShowPick(CallbackData, prefix="delshow_pick"):
    sid: int          # Sonarr's own series id


class DelShowMode(CallbackData, prefix="delshow_mode"):
    sid: int
    mode: str         # 'k' keep files, 'f' delete files, 't' delete files and torrents, 'x' cancel


class DelShowGo(CallbackData, prefix="delshow_go"):
    sid: int
    mode: str
