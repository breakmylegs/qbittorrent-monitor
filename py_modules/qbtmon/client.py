"""qBittorrent WebUI API v2 client.

Auth modes:
- api_key: `Authorization: Bearer <key>` on every request (5.2.0 and later).
- password: POST auth/login, then replay whatever cookie the server sets. 5.2.0
  appends the port to the cookie name, so the name is never assumed.
- none: no credentials, for servers that whitelist this device's IP.

The API key is sent whenever one is stored, whatever the mode.
Reads use GET and changes use POST. qBittorrent answers 405 to the wrong method.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Iterable

from plugin_core.errors import AUTH, BAD_RESPONSE, FORBIDDEN, PluginError, from_status
from plugin_core.http import BaseUrl, HttpClient, Response, TlsOptions

API = "api/v2/"
MODE_API_KEY = "api_key"
MODE_PASSWORD = "password"
MODE_NONE = "none"
AUTH_MODES = (MODE_API_KEY, MODE_PASSWORD, MODE_NONE)

# WebAPI 2.11.0 (qBittorrent 5.0) renamed pause and resume to stop and start.
START_STOP_SINCE = (2, 11, 0)


def parse_api_version(text: str) -> tuple[int, ...]:
    parts = []
    for piece in text.strip().split("."):
        if not piece.isdigit():
            break
        parts.append(int(piece))
    return tuple(parts)


def join_hashes(hashes: Iterable[str] | str) -> str:
    if hashes == "all":
        return "all"
    if isinstance(hashes, str):
        hashes = [hashes]
    clean = [h for h in hashes if isinstance(h, str) and h and "|" not in h]
    if not clean:
        raise ValueError("no torrents selected")
    return "|".join(clean)


@dataclass
class Credentials:
    mode: str = MODE_API_KEY
    api_key: str = ""
    username: str = ""
    password: str = ""


class QbtClient:
    def __init__(self, base: BaseUrl, creds: Credentials, tls: TlsOptions | None = None, timeout: float = 5.0):
        if creds.mode not in AUTH_MODES:
            raise ValueError("unknown auth mode")
        self.base = base
        self.creds = creds
        headers = {"Referer": base.origin, "Origin": base.origin}
        if creds.api_key:
            headers["Authorization"] = f"Bearer {creds.api_key}"
        self.http = HttpClient(base, timeout=timeout, tls=tls or TlsOptions(), use_cookies=True, headers=headers)
        self._logged_in = False
        self._lock = threading.Lock()
        self.api_version: tuple[int, ...] | None = None

    # Auth

    def login(self) -> None:
        if not self.creds.username:
            raise PluginError(AUTH, "no username")
        self.http.clear_cookies()
        res = self.http.post(
            API + "auth/login",
            form={"username": self.creds.username, "password": self.creds.password},
            headers={"Accept": "text/plain"},
        )
        if res.status == 403:
            # Too many failed logins. qBittorrent has banned this IP for a while.
            raise PluginError(FORBIDDEN, "login banned", 403)
        # 5.2.0 and later: 204 with an empty body on success, 401 on bad credentials.
        # Before 5.2.0: 200 with "Ok." or "Fails.".
        body = res.text().strip()
        if res.status == 204 or (res.status == 200 and body == "Ok."):
            self._logged_in = True
            return
        raise PluginError(AUTH, "login rejected", res.status)

    def _call(self, method: str, path: str, **kwargs: Any) -> Response:
        with self._lock:
            if self.creds.mode == MODE_PASSWORD and not self._logged_in:
                self.login()
            res = self.http.request(method, API + path, **kwargs)
            if res.status in (401, 403) and self.creds.mode == MODE_PASSWORD:
                # The session expired. Log in once more, then give up.
                self._logged_in = False
                self.login()
                res = self.http.request(method, API + path, **kwargs)
        if res.status in (401, 403):
            raise from_status(res.status)
        if res.status == 204:
            return res
        if res.status >= 400:
            raise from_status(res.status)
        return res

    def _get_json(self, path: str, **params: Any) -> Any:
        return self._call("GET", path, params=params or None).json()

    def _post(self, path: str, **form: Any) -> None:
        self._call("POST", path, form=form)

    # Version

    def probe(self) -> int:
        """Unauthenticated reachability check. Returns the HTTP status. qBittorrent
        has no public version endpoint, so a 403 still proves the server is there."""
        res = HttpClient(self.base, timeout=self.http.timeout, tls=self.http.tls).get(API + "app/version")
        return res.status

    def app_version(self) -> str:
        return self._call("GET", "app/version").text().strip()

    def webapi_version(self) -> tuple[int, ...]:
        text = self._call("GET", "app/webapiVersion").text()
        version = parse_api_version(text)
        if not version:
            raise PluginError(BAD_RESPONSE, "no API version")
        self.api_version = version
        return version

    def _ensure_version(self) -> tuple[int, ...]:
        return self.api_version or self.webapi_version()

    # Reads

    def maindata(self, rid: int) -> dict[str, Any] | None:
        """None means 204, nothing changed since `rid` (5.2.0 and later)."""
        res = self._call("GET", "sync/maindata", params={"rid": rid})
        if res.status == 204 or not res.body:
            return None
        return res.json()

    def transfer_info(self) -> dict[str, Any]:
        return self._get_json("transfer/info")

    def speed_limits_mode(self) -> bool:
        return self._call("GET", "transfer/speedLimitsMode").text().strip() == "1"

    def categories(self) -> dict[str, Any]:
        return self._get_json("torrents/categories")

    def tags(self) -> list[str]:
        return self._get_json("torrents/tags")

    # Changes

    def toggle_alt_speed(self) -> None:
        self._post("transfer/toggleSpeedLimitsMode")

    def start(self, hashes: Iterable[str] | str) -> None:
        verb = "start" if self._ensure_version() >= START_STOP_SINCE else "resume"
        self._post(f"torrents/{verb}", hashes=join_hashes(hashes))

    def stop(self, hashes: Iterable[str] | str) -> None:
        verb = "stop" if self._ensure_version() >= START_STOP_SINCE else "pause"
        self._post(f"torrents/{verb}", hashes=join_hashes(hashes))

    def recheck(self, hashes: Iterable[str] | str) -> None:
        self._post("torrents/recheck", hashes=join_hashes(hashes))

    def delete(self, hashes: Iterable[str] | str, delete_files: bool) -> None:
        self._post("torrents/delete", hashes=join_hashes(hashes), deleteFiles=bool(delete_files))
