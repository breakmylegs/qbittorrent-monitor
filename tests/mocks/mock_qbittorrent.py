"""Mock qBittorrent WebUI API for tests and local UI work.

Run standalone: python tools/mock_qbittorrent.py --port 8090 --api-key KEY
Use from tests: MockQbt(...).start() returns the base URL.

Models the behaviour the plugin relies on:
- API key (Bearer), cookie login with a port-suffixed cookie name, and an IP
  whitelist that skips auth only when no Bearer header is sent.
- Login answers 204 or 401 as in 5.2.0 and later. legacy_login=True gives the
  older 200 "Ok." or "Fails.".
- sync/maindata with rid, partial updates and torrents_removed. Real 5.3 servers
  always answer JSON. support_204=True simulates a 204 to test that path.
- start/stop on WebAPI 2.11.0 and later, pause/resume before that.
- 405 on the wrong method.
"""

from __future__ import annotations

import argparse
import copy
import json
import secrets as pysecrets
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

POST_ONLY = {
    "auth/login", "auth/logout", "transfer/toggleSpeedLimitsMode", "torrents/start", "torrents/stop",
    "torrents/pause", "torrents/resume", "torrents/recheck", "torrents/delete",
}


def sample_torrents() -> dict[str, dict[str, Any]]:
    return {
        "a" * 40: {"name": "Example Linux ISO", "state": "downloading", "progress": 0.42, "eta": 600,
                   "dlspeed": 2_000_000, "upspeed": 10_000, "size": 4_000_000_000, "added_on": 3, "category": "iso"},
        "b" * 40: {"name": "Public domain film", "state": "stalledUP", "progress": 1.0, "eta": 8640000,
                   "dlspeed": 0, "upspeed": 0, "size": 700_000_000, "added_on": 2, "category": ""},
        "c" * 40: {"name": "Open dataset", "state": "stoppedDL", "progress": 0.1, "eta": 8640000,
                   "dlspeed": 0, "upspeed": 0, "size": 9_000_000_000, "added_on": 1, "category": "data"},
    }


class MockState:
    def __init__(self, api_key: str = "", username: str = "admin", password: str = "", whitelist: bool = False,
                 webapi: str = "2.16.2", version: str = "v5.3.0", support_204: bool = False,
                 legacy_login: bool = False):
        self.legacy_login = legacy_login
        self.api_key = api_key
        self.username = username
        self.password = password
        self.whitelist = whitelist
        self.webapi = webapi
        self.version = version
        self.support_204 = support_204
        self.sessions: set[str] = set()
        self.torrents = sample_torrents()
        self.alt_speed = False
        self.rid = 1
        self.history: dict[int, dict[str, dict[str, Any]]] = {1: copy.deepcopy(self.torrents)}
        self.removed_since: dict[int, set[str]] = {}
        self.calls: list[tuple[str, str, dict[str, str]]] = []
        self.lock = threading.Lock()

    def bump(self) -> None:
        self.rid += 1
        self.history[self.rid] = copy.deepcopy(self.torrents)

    def set_torrent(self, hash_: str, **fields: Any) -> None:
        with self.lock:
            self.torrents.setdefault(hash_, {}).update(fields)
            self.bump()

    def remove(self, hash_: str) -> None:
        with self.lock:
            self.torrents.pop(hash_, None)
            self.bump()

    def maindata(self, rid: int) -> dict[str, Any] | None:
        with self.lock:
            server_state = {"dl_info_speed": sum(t.get("dlspeed", 0) for t in self.torrents.values()),
                            "up_info_speed": sum(t.get("upspeed", 0) for t in self.torrents.values()),
                            "use_alt_speed_limits": self.alt_speed, "connection_status": "connected",
                            "free_space_on_disk": 100_000_000_000}
            if rid not in self.history:
                return {"rid": self.rid, "full_update": True, "torrents": copy.deepcopy(self.torrents),
                        "server_state": server_state, "categories": {}, "tags": []}
            if rid == self.rid and self.support_204:
                return None
            before = self.history[rid]
            changed: dict[str, dict[str, Any]] = {}
            for h, t in self.torrents.items():
                old = before.get(h)
                if old is None:
                    changed[h] = copy.deepcopy(t)
                    continue
                diff = {k: v for k, v in t.items() if old.get(k) != v}
                if diff:
                    changed[h] = diff
            removed = [h for h in before if h not in self.torrents]
            out: dict[str, Any] = {"rid": self.rid, "server_state": server_state}
            if changed:
                out["torrents"] = changed
            if removed:
                out["torrents_removed"] = removed
            return out


def make_handler(state: MockState):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def _send(self, status: int, body: bytes | str = b"", ctype: str = "text/plain", headers=None):
            if isinstance(body, str):
                body = body.encode()
            self.send_response(status)
            if status != 204:
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            if status != 204:
                self.wfile.write(body)

        def _json(self, data: Any):
            self._send(200, json.dumps(data), "application/json")

        def _cookie_name(self) -> str:
            return f"QBT_SID_{self.server.server_address[1]}"

        def _authorised(self) -> bool:
            auth = self.headers.get("Authorization", "")
            if auth.startswith("Bearer "):
                # Matches what we model: a wrong key fails even for a whitelisted client.
                return bool(state.api_key) and auth[7:] == state.api_key
            if state.whitelist:
                return True
            cookie = self.headers.get("Cookie", "")
            for part in cookie.split(";"):
                name, _, value = part.strip().partition("=")
                if name == self._cookie_name() and value in state.sessions:
                    return True
            return False

        def _route(self, method: str):
            parts = urllib.parse.urlsplit(self.path)
            if not parts.path.startswith("/api/v2/"):
                return self._send(404, "Not Found")
            path = parts.path[len("/api/v2/"):]
            query = dict(urllib.parse.parse_qsl(parts.query))
            form: dict[str, str] = {}
            if method == "POST":
                length = int(self.headers.get("Content-Length") or 0)
                form = dict(urllib.parse.parse_qsl(self.rfile.read(length).decode()))
            state.calls.append((method, path, form or query))
            if path in POST_ONLY and method != "POST":
                return self._send(405, "Method Not Allowed")
            if path == "auth/login":
                if self.headers.get("Authorization", "").lower().startswith("bearer "):
                    return self._send(403, "Forbidden")
                ok = form.get("username") == state.username and form.get("password") == state.password and state.password
                if not ok:
                    # 5.2.0 and later answer 401. Older servers answer 200 "Fails.".
                    return self._send(200, "Fails.") if state.legacy_login else self._send(401, "Unauthorized")
                sid = pysecrets.token_hex(8)
                state.sessions.add(sid)
                cookie = {"Set-Cookie": f"{self._cookie_name()}={sid}; path=/; HttpOnly"}
                return self._send(200, "Ok.", headers=cookie) if state.legacy_login else self._send(204, headers=cookie)
            if not self._authorised():
                return self._send(403, "Forbidden")
            if path == "app/version":
                return self._send(200, state.version)
            if path == "app/webapiVersion":
                return self._send(200, state.webapi)
            if path == "sync/maindata":
                data = state.maindata(int(query.get("rid", 0)))
                return self._send(204) if data is None else self._json(data)
            if path == "transfer/info":
                return self._json({"dl_info_speed": 0, "up_info_speed": 0})
            if path == "transfer/speedLimitsMode":
                return self._send(200, "1" if state.alt_speed else "0")
            if path == "transfer/toggleSpeedLimitsMode":
                with state.lock:
                    state.alt_speed = not state.alt_speed
                    state.bump()
                return self._send(200)
            new_api = tuple(int(p) for p in state.webapi.split(".")) >= (2, 11, 0)
            verbs = {"torrents/start": "start", "torrents/stop": "stop"} if new_api else {
                "torrents/resume": "start", "torrents/pause": "stop"}
            if path in verbs:
                target = "downloading" if verbs[path] == "start" else "stoppedDL"
                hashes = list(state.torrents) if form.get("hashes") == "all" else form.get("hashes", "").split("|")
                for h in hashes:
                    if h in state.torrents:
                        state.set_torrent(h, state=target)
                return self._send(200)
            if path == "torrents/recheck":
                return self._send(200)
            if path == "torrents/delete":
                for h in form.get("hashes", "").split("|"):
                    state.remove(h)
                return self._send(200)
            if path == "torrents/categories":
                return self._json({})
            if path == "torrents/tags":
                return self._json([])
            return self._send(404, "Not Found")

        def do_GET(self):
            self._route("GET")

        def do_POST(self):
            self._route("POST")

    return Handler


class MockQbt:
    def __init__(self, port: int = 0, **kwargs: Any):
        self.state = MockState(**kwargs)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(self.state))
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def start(self) -> str:
        self.thread.start()
        return self.url

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--api-key", default="")
    parser.add_argument("--password", default="")
    parser.add_argument("--whitelist", action="store_true")
    args = parser.parse_args()
    mock = MockQbt(args.port, api_key=args.api_key, password=args.password, whitelist=args.whitelist)
    print(f"Mock qBittorrent on {mock.url}")
    mock.httpd.serve_forever()


if __name__ == "__main__":
    main()
