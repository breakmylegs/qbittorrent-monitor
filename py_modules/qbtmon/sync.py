"""Incremental `sync/maindata` cache and the compact projection sent to the UI."""

from __future__ import annotations

from typing import Any

from . import states

TOP_N = 8


def _num(value: Any, default: float = 0) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _deep_merge(target: dict, patch: dict) -> None:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = value


class MainData:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.rid = 0
        self.torrents: dict[str, dict[str, Any]] = {}
        self.server_state: dict[str, Any] = {}
        self.categories: dict[str, Any] = {}
        self.tags: list[str] = []

    def apply(self, payload: dict[str, Any] | None) -> None:
        """Apply one maindata reply. None means HTTP 204, no change."""
        if payload is None:
            return
        if not isinstance(payload, dict):
            raise ValueError("maindata reply is not an object")
        if payload.get("full_update"):
            self.torrents = {}
            self.server_state = {}
            self.categories = {}
            self.tags = []
        for hash_, patch in (payload.get("torrents") or {}).items():
            if not isinstance(patch, dict):
                continue
            current = self.torrents.setdefault(str(hash_), {})
            _deep_merge(current, patch)
        for hash_ in payload.get("torrents_removed") or []:
            self.torrents.pop(str(hash_), None)
        server = payload.get("server_state")
        if isinstance(server, dict):
            _deep_merge(self.server_state, server)
        cats = payload.get("categories")
        if isinstance(cats, dict):
            _deep_merge(self.categories, cats)
        for name in payload.get("categories_removed") or []:
            self.categories.pop(name, None)
        tags = payload.get("tags")
        if isinstance(tags, list):
            self.tags = sorted(set(self.tags) | {t for t in tags if isinstance(t, str)})
        removed = set(payload.get("tags_removed") or [])
        if removed:
            self.tags = [t for t in self.tags if t not in removed]
        rid = payload.get("rid")
        if isinstance(rid, int) and not isinstance(rid, bool):
            self.rid = rid


def activity_key(torrent: dict[str, Any]) -> tuple:
    state = torrent.get("state")
    speed = _num(torrent.get("dlspeed")) + _num(torrent.get("upspeed"))
    active = state in states.ACTIVE_STATES or speed > 0
    downloading = _num(torrent.get("progress")) < 1
    return (not active, not downloading, -speed, -_num(torrent.get("added_on")))


def project_torrent(hash_: str, torrent: dict[str, Any]) -> dict[str, Any]:
    eta = int(_num(torrent.get("eta"), states.INFINITE_ETA))
    # "priority" is the queue position. 0 or -1 means not in the queue.
    position = int(_num(torrent.get("priority")))
    return {
        "hash": hash_,
        "name": str(torrent.get("name") or ""),
        "progress": max(0.0, min(1.0, _num(torrent.get("progress")))),
        "eta": None if eta >= states.INFINITE_ETA or eta < 0 else eta,
        "dlspeed": int(_num(torrent.get("dlspeed"))),
        "upspeed": int(_num(torrent.get("upspeed"))),
        "state": str(torrent.get("state") or ""),
        "label": states.label(torrent.get("state")),
        "stopped": states.is_stopped(torrent.get("state")),
        "size": int(_num(torrent.get("size"))),
        "category": str(torrent.get("category") or ""),
        "force_start": bool(torrent.get("force_start")),
        "queue_pos": position if position > 0 else None,
        "ratio": round(_num(torrent.get("ratio")), 2),
    }


def _downloading(torrent: dict[str, Any]) -> bool:
    return _num(torrent.get("progress")) < 1 and not states.is_stopped(torrent.get("state"))


def _optional_int(server: dict[str, Any], key: str) -> int | None:
    return int(_num(server.get(key))) if key in server else None


def project_server(data: MainData) -> dict[str, Any]:
    server = data.server_state
    dl_speed = int(_num(server.get("dl_info_speed")))
    left = sum(int(_num(t.get("amount_left"))) for t in data.torrents.values() if _downloading(t))
    eta = int(left / dl_speed) if left and dl_speed > 0 else None
    ratio = _num(server.get("global_ratio"), -1)
    return {
        "dl_speed": dl_speed,
        "up_speed": int(_num(server.get("up_info_speed"))),
        "alt_speed": bool(server.get("use_alt_speed_limits")),
        "connection_status": str(server.get("connection_status") or ""),
        "free_space": _optional_int(server, "free_space_on_disk"),
        # The limits for the current mode, normal or alternative. 0 means none.
        "dl_limit": int(_num(server.get("dl_rate_limit"))),
        "up_limit": int(_num(server.get("up_rate_limit"))),
        "dl_session": _optional_int(server, "dl_info_data"),
        "up_session": _optional_int(server, "up_info_data"),
        "ratio": round(ratio, 2) if ratio >= 0 else None,
        "dht_nodes": _optional_int(server, "dht_nodes"),
        "queueing": bool(server.get("queueing")),
        # qBittorrent 5.3 and later only. None means the server cannot pause the session.
        "session_paused": bool(server["session_state"]) if "session_state" in server else None,
        "left": left,
        "eta": eta if eta is None or eta < states.INFINITE_ETA else None,
    }


def project(data: MainData, limit: int = TOP_N) -> dict[str, Any]:
    ordered = sorted(data.torrents.items(), key=lambda item: activity_key(item[1]))
    return {
        "torrents": [project_torrent(h, t) for h, t in ordered[:limit]],
        "total": len(data.torrents),
        "active": sum(1 for t in data.torrents.values() if t.get("state") in states.ACTIVE_STATES),
        "server": project_server(data),
        "categories": sorted(str(name) for name in data.categories),
    }


# Full list filters. Each takes the raw torrent from the maindata cache.
FILTERS = {
    "all": lambda t: True,
    "downloading": _downloading,
    "seeding": lambda t: states.label(t.get("state")) == states.SEEDING,
    "completed": lambda t: _num(t.get("progress")) >= 1,
    "stopped": lambda t: states.is_stopped(t.get("state")),
    "active": lambda t: _num(t.get("dlspeed")) + _num(t.get("upspeed")) > 0,
    "error": lambda t: states.label(t.get("state")) == states.ERROR,
}

SORTS = {
    "activity": lambda item: activity_key(item[1]),
    "name": lambda item: str(item[1].get("name") or "").lower(),
    "added": lambda item: -_num(item[1].get("added_on")),
    "size": lambda item: -_num(item[1].get("size")),
}

LIST_LIMIT = 100


def list_torrents(data: MainData, filter_id: str = "all", category: str | None = None, sort: str = "activity",
                  limit: int = LIST_LIMIT) -> dict[str, Any]:
    """Torrents for the full-screen list. `category` None means any, "" means none set."""
    if filter_id not in FILTERS:
        raise ValueError("unknown filter")
    if sort not in SORTS:
        raise ValueError("unknown sort")
    keep = FILTERS[filter_id]
    # A poll thread may add or remove torrents meanwhile. Copy the items first.
    items = list(data.torrents.items())
    matched = [
        (h, t) for h, t in items
        if keep(t) and (category is None or str(t.get("category") or "") == category)
    ]
    matched.sort(key=SORTS[sort])
    return {
        "torrents": [project_torrent(h, t) for h, t in matched[:limit]],
        "matched": len(matched),
        "total": len(data.torrents),
        "limit": limit,
    }


class TransitionTracker:
    """Finds torrents that finished downloading or entered an error state.

    Each torrent toasts once for completion. An error toasts each time a torrent
    enters the error state from another state.
    """

    def __init__(self) -> None:
        self.previous: dict[str, tuple[str, float]] = {}
        self.completed: set[str] = set()

    def reset(self) -> None:
        self.previous = {}
        self.completed = set()

    def changes(self, data: MainData) -> list[dict[str, str]]:
        toasts: list[dict[str, str]] = []
        current: dict[str, tuple[str, float]] = {}
        for hash_, torrent in data.torrents.items():
            lbl = states.label(torrent.get("state"))
            progress = _num(torrent.get("progress"))
            current[hash_] = (lbl, progress)
            before = self.previous.get(hash_)
            if before is None:
                if lbl in (states.COMPLETED, states.SEEDING):
                    self.completed.add(hash_)
                continue
            name = str(torrent.get("name") or "Torrent")
            was_downloading = before[1] < 1 and before[0] not in (states.COMPLETED, states.SEEDING)
            if lbl in (states.COMPLETED, states.SEEDING) and was_downloading and hash_ not in self.completed:
                self.completed.add(hash_)
                toasts.append({"kind": "completed", "key": f"completed:{hash_}", "title": "Download complete", "body": name})
            if lbl == states.ERROR and before[0] != states.ERROR:
                toasts.append({"kind": "error", "key": f"error:{hash_}", "title": "Torrent error", "body": name})
        self.completed &= set(current)
        self.previous = current
        return toasts
