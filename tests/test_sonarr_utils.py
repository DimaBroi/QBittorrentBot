"""Run with: python -m tests.test_sonarr_utils   (or pytest)"""
import asyncio

from src.sonarr.utils import build_add_payload, parse_show_name, pick_profile, show_label

LOOKUP = {"title": "Yaga", "year": 2026, "tvdbId": 444, "titleSlug": "yaga", "seriesType": "standard",
          "images": [], "seasons": [{"seasonNumber": 1, "monitored": True}], "id": 0, "path": "/x",
          "statistics": {"episodeCount": 8}, "ratings": {"value": 7}}


def test_show_label():
    assert show_label({"title": "Yaga", "year": 2026, "tvdbId": 1}) == "Yaga (2026)"
    assert show_label({"title": "Yaga", "year": 2026, "tvdbId": 1}, existing_ids={1}) == "✓ Yaga (2026)"
    assert show_label({"title": "Yaga", "tvdbId": 1}, existing_ids={2}) == "Yaga"
    assert show_label({}) == "?"
    assert len(show_label({"title": "x" * 200, "year": 2000, "tvdbId": 1})) <= 60


def test_pick_profile():
    profiles = [{"id": 1, "name": "Any"}, {"id": 4, "name": "HD-1080p"}]
    assert pick_profile(profiles, "hd-1080P")["id"] == 4
    assert pick_profile(profiles, "Missing")["id"] == 1        # falls back to the first profile
    assert pick_profile([], "HD-1080p") is None and pick_profile(None, "x") is None


def test_build_add_payload_all_episodes():
    p = build_add_payload(LOOKUP, "/downloads/Shows", 4, "a")
    assert p["tvdbId"] == 444 and p["title"] == "Yaga" and p["titleSlug"] == "yaga"
    assert p["qualityProfileId"] == 4 and p["rootFolderPath"] == "/downloads/Shows"
    assert p["monitored"] is True and p["seasonFolder"] is True
    assert p["addOptions"] == {"monitor": "all", "searchForMissingEpisodes": True, "searchForCutoffUnmetEpisodes": False}
    for dropped in ("id", "path", "statistics", "ratings"):
        assert dropped not in p
    assert "id" in LOOKUP                                        # the input is not modified


def test_build_add_payload_future_only():
    p = build_add_payload(LOOKUP, "/downloads/Shows", 4, "f")
    assert p["addOptions"]["monitor"] == "future" and p["addOptions"]["searchForMissingEpisodes"] is False


def test_build_add_payload_rejects_unknown_mode():
    for bad in ("x", "", "all"):
        try:
            build_add_payload(LOOKUP, "/downloads/Shows", 4, bad)
        except ValueError:
            continue
        raise AssertionError(f"mode {bad!r} should be rejected")


def test_parse_show_name():
    assert parse_show_name("  House   M.D. ") == "House M.D."
    assert parse_show_name("") is None and parse_show_name(None) is None and parse_show_name("   ") is None


def test_callback_data_fits_telegram_limit():
    from src.bot.filters.callbacks import AddShowMenu, ShowAdd, ShowPick
    for packed in (AddShowMenu().pack(), ShowPick(tvdb=999999999).pack(), ShowAdd(tvdb=999999999, mode="a").pack()):
        assert len(packed.encode()) <= 64, packed
    assert ShowPick.unpack(ShowPick(tvdb=444).pack()).tvdb == 444
    assert ShowAdd.unpack(ShowAdd(tvdb=444, mode="f").pack()).mode == "f"


def test_settings_sonarr_is_optional():
    from src.settings import Settings
    base = {"client": {"host": "http://q:8080", "user": "u", "password": "p"}, "telegram": {"bot_token": "t", "proxy": None},
            "users": [{"user_id": 1, "role": "administrator", "notify": False}], "redis": {"url": None}}
    assert Settings(**base).sonarr is None
    s = Settings(**base, sonarr={"url": "http://sonarr:8989", "api_key": "k"})
    assert s.sonarr.root_folder == "/downloads/Shows" and s.sonarr.quality_profile == "HD-1080p"
    assert Settings(**s.model_dump(mode="json")).sonarr.url == "http://sonarr:8989"   # survives export/reload


def test_client_never_puts_the_key_in_errors():
    from src.sonarr.client import SonarrClient, SonarrError
    c = SonarrClient("http://127.0.0.1:1", "SECRETKEY", timeout=2)
    try:
        asyncio.run(c.lookup("x"))
    except SonarrError as e:
        assert "SECRETKEY" not in str(e)
    else:
        raise AssertionError("expected SonarrError")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print("ok", fn.__name__)
    print(f"{len(fns)} tests passed")
