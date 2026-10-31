"""qBittorrent monitor backend."""

from __future__ import annotations

import asyncio
import threading
from typing import Any

from plugin_core import conntest
from plugin_core.errors import BAD_RESPONSE, FORBIDDEN, PluginError, classify
from plugin_core.http import TlsOptions, parse_base_url
from plugin_core.service import MonitorService

from .client import AUTH_MODES, MAX_LIMIT, MODE_API_KEY, MODE_NONE, MODE_PASSWORD, QUEUE_MOVES, Credentials, QbtClient
from .sync import MainData, TransitionTracker, list_torrents, project

ACTIONS = ("start", "stop", "recheck", "reannounce")
LIMIT_DIRECTIONS = ("download", "upload")


def _bad(message: str) -> dict[str, Any]:
    return {"ok": False, "error": {"kind": "bad_response", "message": message}}


class QbtService(MonitorService):
    plugin_id = "qbittorrent-monitor"
    secret_names = ("api_key", "password")
    extra_defaults = {"auth_mode": MODE_API_KEY, "username": "", "game_alt_speed": False}

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.client: QbtClient | None = None
        self.maindata = MainData()
        self.tracker = TransitionTracker()
        self._game_mutex = threading.Lock()

    connection_keys = frozenset({"base_url", "tls_verify", "ca_file", "auth_mode", "username"})

    def save_settings(self, values):  # type: ignore[override]
        mode = values.get("auth_mode") if hasattr(values, "get") else None
        if mode is not None and mode not in AUTH_MODES:
            raise ValueError("unknown auth mode")
        return super().save_settings(values)

    # Client

    def credentials(self, with_key: bool = True) -> Credentials:
        mode = self.settings.get("auth_mode")
        return Credentials(
            mode=mode,
            api_key=self.secrets.get("api_key") if with_key else "",
            username=self.settings.get("username") if mode == MODE_PASSWORD else "",
            password=self.secrets.get("password") if mode == MODE_PASSWORD else "",
        )

    def tls(self) -> TlsOptions:
        return TlsOptions(verify=self.settings.get("tls_verify"), ca_file=self.settings.get("ca_file"))

    def build_client(self, with_key: bool = True) -> QbtClient:
        return QbtClient(parse_base_url(self.settings.get("base_url")), self.credentials(with_key), self.tls())

    def get_client(self) -> QbtClient:
        if self.client is None:
            self.client = self.build_client()
        return self.client

    def on_connection_changed(self) -> None:
        self.client = None
        self.maindata.reset()
        self.tracker.reset()

    # Poll

    def _poll_blocking(self) -> MainData:
        client = self.get_client()
        payload = client.maindata(self.maindata.rid)
        try:
            self.maindata.apply(payload)
        except ValueError:
            self.maindata.reset()
            raise PluginError(BAD_RESPONSE, "maindata shape") from None
        if self.game_ended_undo_due():
            # The undo at game end failed, for example while offline. Try again now.
            try:
                self._undo_game_change(client, from_poll=True)
            except Exception as exc:  # noqa: BLE001, classified
                self.log.warning("game-time undo failed: %s", classify(exc).kind)
        return self.maindata

    async def fetch(self) -> MainData:
        try:
            return await asyncio.to_thread(self._poll_blocking)
        except ValueError as err:
            # A bad base URL. Surface it as a bad response, without the value.
            raise PluginError(BAD_RESPONSE, "invalid base URL") from err

    def notifications_for(self, data: MainData) -> list[dict[str, str]]:
        return self.tracker.changes(data)

    def project(self, data: MainData) -> dict[str, Any]:
        return project(data)

    # Actions

    async def torrent_action(self, action: str, hashes: list[str] | str) -> dict[str, Any]:
        if action not in ACTIONS:
            return {"ok": False, "error": {"kind": "bad_response", "message": "Unknown action."}}
        client = self.get_client()
        return await self.run_action(lambda: getattr(client, action)(hashes))

    async def delete_torrents(self, hashes: list[str], delete_files: bool) -> dict[str, Any]:
        if hashes == "all":
            return {"ok": False, "error": {"kind": "bad_response", "message": "Delete one torrent at a time."}}
        client = self.get_client()
        return await self.run_action(lambda: client.delete(hashes, bool(delete_files)))

    async def toggle_alt_speed(self) -> dict[str, Any]:
        client = self.get_client()
        return await self.run_action(client.toggle_alt_speed)

    async def set_force_start(self, hashes: list[str], value: bool) -> dict[str, Any]:
        client = self.get_client()
        return await self.run_action(lambda: client.set_force_start(hashes, bool(value)))

    async def queue_move(self, hashes: list[str], where: str) -> dict[str, Any]:
        if where not in QUEUE_MOVES:
            return _bad("Unknown queue move.")
        client = self.get_client()
        return await self.run_action(lambda: client.queue_move(hashes, where))

    async def set_category(self, hashes: list[str], category: str) -> dict[str, Any]:
        if not isinstance(category, str):
            return _bad("Pick a category.")
        if category and category not in self.maindata.categories:
            return _bad("qBittorrent has no category with that name. Refresh and pick again.")
        client = self.get_client()
        return await self.run_action(lambda: client.set_category(hashes, category))

    async def set_speed_limit(self, direction: str, limit: int) -> dict[str, Any]:
        if direction not in LIMIT_DIRECTIONS:
            return _bad("Unknown limit.")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 0 <= limit <= MAX_LIMIT:
            return _bad("Pick a limit from the list.")
        client = self.get_client()
        fn = client.set_download_limit if direction == "download" else client.set_upload_limit
        return await self.run_action(lambda: fn(limit))

    async def set_session_paused(self, paused: bool) -> dict[str, Any]:
        client = self.get_client()

        def run() -> None:
            if not client.supports_session_pause():
                raise PluginError(BAD_RESPONSE, "no session pause", hint="Pausing all traffic needs qBittorrent 5.3 or newer.")
            if paused:
                client.pause_session()
            else:
                client.resume_session()

        return await self.run_action(run)

    def list_torrents(self, filter_id: str, category: str | None, sort: str) -> dict[str, Any]:
        """Served from the maindata cache, with no extra request to the server."""
        try:
            return {"ok": True, **list_torrents(self.maindata, filter_id, category, sort)}
        except ValueError as err:
            return _bad(str(err).capitalize() + ".")

    # Game-time alternative speed (opt-in)

    def game_changed_blocking(self, running: bool) -> None:
        client = self.get_client()
        if not running:
            self._undo_game_change(client)
            return
        with self._game_mutex:
            if not self.settings.get("game_alt_speed") or self.game_change():
                return
            if client.speed_limits_mode():
                # Already on, so the user chose it. Leave it alone afterwards too.
                return
            client.set_alt_speed(True)
            self.remember_game_change({"alt_speed": True})
        self.log.info("game started, alternative speed limits on")

    def _undo_game_change(self, client: QbtClient, from_poll: bool = False) -> None:
        # The game-end task and a poll can both get here. The mutex stops a double toggle.
        with self._game_mutex:
            if from_poll and not self.game_ended_undo_due():
                # A game started while this poll ran.
                return
            record = self.game_change()
            if not record:
                return
            if record.get("alt_speed") and client.speed_limits_mode():
                client.set_alt_speed(False)
                self.log.info("game ended, alternative speed limits off")
            # Cleared even when the user turned it off during the game.
            self.game_memory.clear()

    # Connection test

    async def test_connection(self) -> dict[str, Any]:
        return await asyncio.to_thread(self._test_blocking)

    def _test_blocking(self) -> dict[str, Any]:
        report = conntest.Report()
        base = conntest.check_url(report, self.settings.get("base_url"))
        if base is None:
            return report.to_dict()

        probe_client = QbtClient(base, Credentials(mode=MODE_NONE), self.tls())
        ok, status = conntest.run_step(report, conntest.VERSION, probe_client.probe)
        if not ok:
            return report.to_dict()
        if status == 404:
            report.failed(conntest.VERSION, "No qBittorrent WebUI API at this address. Check the port and path.")
            return report.to_dict()
        if status not in (200, 401, 403):
            report.failed(conntest.VERSION, f"The server answered HTTP {status}. Check the address.")
            return report.to_dict()
        open_access = status == 200
        report.passed(conntest.VERSION, "Server reachable" + (" without sign-in" if open_access else ""))

        mode = self.settings.get("auth_mode")
        has_key = self.secrets.has("api_key")
        if mode == MODE_API_KEY and not has_key:
            report.failed(conntest.AUTH, "Auth mode is API key but no key is stored.")
            return report.to_dict()
        if mode == MODE_PASSWORD and not (self.settings.get("username") and self.secrets.has("password")):
            report.failed(conntest.AUTH, "Enter a username and password first.")
            return report.to_dict()

        client = self.build_client()
        try:
            client.webapi_version()
            report.server_version = client.app_version()
        except Exception as exc:  # noqa: BLE001, classified
            err = classify(exc)
            if has_key and err.kind in ("auth", FORBIDDEN) and mode != MODE_PASSWORD:
                fallback = self.build_client(with_key=False)
                try:
                    fallback.webapi_version()
                    report.server_version = fallback.app_version()
                except Exception:  # noqa: BLE001
                    report.failed(conntest.AUTH, err)
                    return report.to_dict()
                report.warnings.append(
                    "The server rejected the API key. qBittorrent skips the IP whitelist when a key is sent, "
                    "so polling will fail. Clear the API key or enter the correct one."
                )
                report.auth_path = "whitelist"
                report.passed(conntest.AUTH, "Signed in through the IP whitelist")
                report.ok = True
                return report.to_dict()
            report.failed(conntest.AUTH, err)
            return report.to_dict()

        if open_access:
            report.auth_path = "whitelist"
            detail = "No sign-in needed. The server whitelists this device"
            if has_key:
                detail += ". The API key was sent but is not needed"
        elif mode == MODE_PASSWORD and not has_key:
            report.auth_path = "password"
            detail = "Signed in with username and password"
        elif has_key:
            report.auth_path = "api_key"
            detail = "Signed in with the API key"
        else:
            report.auth_path = "password"
            detail = "Signed in"
        report.passed(conntest.AUTH, detail)
        report.ok = True
        return report.to_dict()
