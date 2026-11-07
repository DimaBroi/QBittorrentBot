"""Pure helpers for 'send a magnet / .torrent, then pick its category' (no Telegram or qBittorrent calls)."""
import json
import os
from typing import Optional
from urllib.parse import parse_qs, unquote_plus

from .rss_utils import short_id

PENDING_TTL = 3600          # seconds a not-yet-categorised magnet/torrent waits for the user's choice
NO_CATEGORY = "none"
CANCEL = "cancel"


def pending_key(chat_id: int, message_id: int) -> str:
    """One pending request per prompt message, so several files can be dropped at once."""
    return f"pending:{chat_id}:{message_id}"


def magnet_links(text: Optional[str]) -> list:
    """All magnet links in a message (one per line); [] when the text has none."""
    lines = [line.strip() for line in (text or "").splitlines()]
    return [line for line in lines if line.startswith("magnet:?xt")]


def magnet_title(link: str) -> str:
    """Display name (dn=) of a magnet link, or a generic label."""
    try:
        names = parse_qs(link.split("?", 1)[1]).get("dn")
    except IndexError:
        names = None
    return unquote_plus(names[0]) if names else "magnet link"


def pending_title(pending: dict) -> str:
    if pending.get("kind") == "magnet":
        links = pending["links"]
        title = magnet_title(links[0])
        return title if len(links) == 1 else f"{title} (+{len(links) - 1} more)"
    return pending.get("file_name") or "torrent file"


def encode_pending(kind: str, **data) -> str:
    return json.dumps({"kind": kind, **data})


def decode_pending(raw) -> Optional[dict]:
    """Inverse of encode_pending; None for a missing, expired or corrupt value."""
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("kind") == "magnet" and data.get("links"):
        return data
    if data.get("kind") == "torrent" and data.get("file_id"):
        return data
    return None


def safe_torrent_name(file_name: Optional[str]) -> str:
    """A plain file name that ends in .torrent (never a path)."""
    name = os.path.basename((file_name or "").replace("\\", "/")) or "file.torrent"
    return name if name.lower().endswith(".torrent") else name + ".torrent"


def category_choices(categories) -> list:
    """[(button label, choice id)] for each category, then 'No category'. Ids are short hashes (64 byte callback limit)."""
    choices = [(name, short_id(name)) for name in sorted(categories or [], key=str.lower)]
    choices.append(("No category", NO_CATEGORY))
    return choices
