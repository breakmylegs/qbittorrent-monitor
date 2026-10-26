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
    }


def project(data: MainData, limit: int = TOP_N) -> dict[str, Any]:
    ordered = sorted(data.torrents.items(), key=lambda item: activity_key(item[1]))
    server = data.server_state
    return {
        "torrents": [project_torrent(h, t) for h, t in ordered[:limit]],
        "total": len(data.torrents),
        "active": sum(1 for t in data.torrents.values() if t.get("state") in states.ACTIVE_STATES),
        "server": {
            "dl_speed": int(_num(server.get("dl_info_speed"))),
            "up_speed": int(_num(server.get("up_info_speed"))),
            "alt_speed": bool(server.get("use_alt_speed_limits")),
            "connection_status": str(server.get("connection_status") or ""),
            "free_space": int(_num(server.get("free_space_on_disk"))) if "free_space_on_disk" in server else None,
        },
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
