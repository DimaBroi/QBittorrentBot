"""Run with: python -m tests.test_add_utils   (or pytest)"""
from src.bot.handlers.add_utils import (
    CANCEL, NO_CATEGORY, category_choices, decode_pending, encode_pending, magnet_links, magnet_title,
    pending_key, pending_title, safe_torrent_name,
)
from src.bot.handlers.rss_utils import find_by_id


def test_magnet_links():
    text = "  magnet:?xt=urn:btih:AAA&dn=One  \nnot a link\nmagnet:?xt=urn:btih:BBB"
    assert magnet_links(text) == ["magnet:?xt=urn:btih:AAA&dn=One", "magnet:?xt=urn:btih:BBB"]
    assert magnet_links("hello") == [] and magnet_links(None) == [] and magnet_links("") == []


def test_magnet_title():
    assert magnet_title("magnet:?xt=urn:btih:AAA&dn=House.M.D.S01+720p&tr=udp%3A%2F%2Fx") == "House.M.D.S01 720p"
    assert magnet_title("magnet:?xt=urn:btih:AAA") == "magnet link"


def test_pending_round_trip():
    raw = encode_pending("magnet", links=["magnet:?xt=urn:btih:AAA&dn=Foo"])
    p = decode_pending(raw)
    assert p["kind"] == "magnet" and pending_title(p) == "Foo"
    raw = encode_pending("magnet", links=["magnet:?xt=urn:btih:AAA&dn=Foo", "magnet:?xt=urn:btih:BBB"])
    assert pending_title(decode_pending(raw)) == "Foo (+1 more)"
    p = decode_pending(encode_pending("torrent", file_id="F1", file_name="a.torrent"))
    assert p["file_id"] == "F1" and pending_title(p) == "a.torrent"


def test_decode_pending_rejects_junk():
    for bad in (None, "", "not json", "[]", '{"kind": "magnet"}', '{"kind": "torrent"}', '{"kind": "x", "links": ["a"]}'):
        assert decode_pending(bad) is None, bad


def test_safe_torrent_name():
    assert safe_torrent_name("../../etc/x.torrent") == "x.torrent"
    assert safe_torrent_name(r"C:\dir\y.TORRENT") == "y.TORRENT"
    assert safe_torrent_name("noext") == "noext.torrent" and safe_torrent_name(None) == "file.torrent"


def test_category_choices_and_lookup():
    cats = {"Shows": {}, "movies": {}, "Audiobooks": {}}
    choices = category_choices(cats)
    assert [c[0] for c in choices] == ["Audiobooks", "movies", "Shows", "No category"]
    assert choices[-1][1] == NO_CATEGORY and category_choices(None) == [("No category", NO_CATEGORY)]
    ids = [c[1] for c in choices[:-1]]
    assert len(set(ids)) == 3 and all(len(i) == 10 for i in ids)
    assert find_by_id(list(cats), ids[0]) == "Audiobooks" and find_by_id(list(cats), "deadbeef00") is None


def test_callback_data_fits_telegram_limit():
    from src.bot.filters.callbacks import PendingAdd
    for choice in (category_choices({"x" * 200: {}})[0][1], NO_CATEGORY, CANCEL):
        assert len(PendingAdd(choice=choice).pack().encode()) <= 64
    assert pending_key(123456789, 4242) == "pending:123456789:4242"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print("ok", fn.__name__)
    print(f"{len(fns)} tests passed")
