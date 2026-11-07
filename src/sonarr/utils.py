"""Pure helpers for adding series to Sonarr (no network calls, easy to test)."""
from typing import Optional

MODES = {"a": "all", "f": "future"}   # monitor modes offered to the user (short codes fit callback data)
MAX_RESULTS = 8


def show_label(item: dict, existing_ids=()) -> str:
    """Button text for a search result: 'Title (year)', with a check mark when Sonarr already has it."""
    title = (item.get("title") or "?").strip()
    year = item.get("year")
    label = f"{title} ({year})" if year else title
    if item.get("tvdbId") in set(existing_ids):
        label = "✓ " + label
    return label[:60]


def pick_profile(profiles: list, wanted: str) -> Optional[dict]:
    """The quality profile called `wanted` (case-insensitive), else the first one, else None."""
    for p in profiles or []:
        if (p.get("name") or "").strip().lower() == (wanted or "").strip().lower():
            return p
    return (profiles or [None])[0]


def build_add_payload(item: dict, root_folder: str, profile_id: int, mode: str) -> dict:
    """
    Body for POST /api/v3/series from a /series/lookup result.
    mode: 'a' = monitor and search every episode, 'f' = only episodes that air from now on.
    """
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}")
    payload = {k: v for k, v in item.items() if k not in ("id", "path", "statistics", "added", "ratings")}
    payload.update({
        "qualityProfileId": profile_id,
        "rootFolderPath": root_folder,
        "monitored": True,
        "seasonFolder": True,
        "addOptions": {
            "monitor": MODES[mode],
            "searchForMissingEpisodes": mode == "a",
            "searchForCutoffUnmetEpisodes": False,
        },
    })
    return payload


def parse_show_name(args: Optional[str]) -> Optional[str]:
    """'/addshow <name>' argument -> cleaned search term, or None when empty."""
    name = " ".join((args or "").split())
    return name or None
