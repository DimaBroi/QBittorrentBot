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


def test_series_label_and_filter():
    from src.sonarr.utils import MAX_SERIES, filter_series, series_label
    series = [{"id": 1, "title": "Yaga", "year": 2026}, {"id": 2, "title": "House", "year": 2004, "sortTitle": "house"},
              {"id": 3, "title": "Full House", "year": 1987}]
    assert series_label(series[0]) == "Yaga (2026)" and series_label({}) == "?"
    assert [s["id"] for s in filter_series(series)] == [3, 2, 1]                   # sorted: full house, house, yaga
    assert {s["id"] for s in filter_series(series, " HOUSE ")} == {2, 3}          # case-insensitive substring
    assert filter_series(series, "zzz") == [] and filter_series(None) == []
    many = [{"id": i, "title": f"Show {i:03d}"} for i in range(50)]
    assert len(filter_series(many)) == MAX_SERIES and filter_series(many)[0]["title"] == "Show 000"


def test_download_hashes():
    from src.sonarr.utils import download_hashes
    history = [{"eventType": "grabbed", "downloadId": "ABC123"}, {"eventType": "grabbed", "downloadId": "abc123"},
               {"eventType": "downloadFolderImported", "downloadId": "ABC123"},
               {"eventType": "grabbed", "downloadId": ""}, {"eventType": "grabbed"}, {"eventType": "grabbed", "downloadId": " DEF "}]
    assert download_hashes(history) == {"abc123", "def"}
    assert download_hashes(None) == set() and download_hashes([]) == set()


def test_delete_confirmation():
    from src.sonarr.utils import DELETE_MODES, delete_confirmation
    assert set(DELETE_MODES) == {"k", "f", "t"}
    assert "files stay" in delete_confirmation("k", "Yaga (2026)")
    assert "torrents" in delete_confirmation("t", "Yaga (2026)") and delete_confirmation("f", "Yaga").startswith("Yaga")
    try:
        delete_confirmation("x", "Yaga")
    except ValueError:
        pass
    else:
        raise AssertionError("unknown mode must be rejected")


def test_delete_callback_data_fits_telegram_limit():
    from src.bot.filters.callbacks import DelShowGo, DelShowMenu, DelShowMode, DelShowPick
    for packed in (DelShowMenu().pack(), DelShowPick(sid=999999).pack(), DelShowMode(sid=999999, mode="t").pack(),
                   DelShowGo(sid=999999, mode="t").pack()):
        assert len(packed.encode()) <= 64, packed
    assert DelShowGo.unpack(DelShowGo(sid=7, mode="f").pack()).mode == "f"


def test_client_handles_delete_with_empty_body():
    """Sonarr answers DELETE /series/<id> with an empty 200; the client must not choke on it."""
    from aiohttp import web
    from src.sonarr.client import SonarrClient, SonarrError

    seen = {}

    async def run():
        async def delete(request):
            seen["query"] = dict(request.query)
            seen["key"] = request.headers.get("X-Api-Key")
            return web.Response(status=200, text="")

        async def history(request):
            return web.json_response([{"eventType": "grabbed", "downloadId": "ABC"}])

        async def boom(request):
            return web.Response(status=500, text="boom")

        app = web.Application()
        app.router.add_delete("/api/v3/series/5", delete)
        app.router.add_get("/api/v3/history/series", history)
        app.router.add_get("/api/v3/series", boom)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        try:
            c = SonarrClient(f"http://127.0.0.1:{port}", "K")
            assert await c.delete_series(5, delete_files=True) is None
            assert seen["query"] == {"deleteFiles": "true", "addImportListExclusion": "false"} and seen["key"] == "K"
            assert (await c.series_history(5))[0]["downloadId"] == "ABC"
            try:
                await c.series_list()
            except SonarrError as e:
                assert "500" in str(e) and "K" not in str(e).replace("Sonarr", "")
            else:
                raise AssertionError("expected SonarrError")
        finally:
            await runner.cleanup()

    asyncio.run(run())


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print("ok", fn.__name__)
    print(f"{len(fns)} tests passed")
