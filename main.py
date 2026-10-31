"""Decky entry point. A thin adapter over qbtmon.service.QbtService."""

import os

import decky

from plugin_core.service import error_result
from qbtmon.service import QbtService


def _version() -> str:
    return os.environ.get("DECKY_PLUGIN_VERSION", "0.0.0")


class Plugin:
    service: QbtService

    async def _main(self):
        self.service = QbtService(
            settings_dir=decky.DECKY_PLUGIN_SETTINGS_DIR,
            runtime_dir=decky.DECKY_PLUGIN_RUNTIME_DIR,
            plugin_dir=decky.DECKY_PLUGIN_DIR,
            user_home=decky.DECKY_USER_HOME,
            version=_version(),
            emit=decky.emit,
            logger=decky.logger,
        )
        await self.service.start()
        decky.logger.info("qbittorrent-monitor started")

    async def _unload(self):
        await self.service.stop()

    async def _uninstall(self):
        await self.service.uninstall()

    # Frontend API. Every method returns plain JSON and never a secret.

    async def get_snapshot(self):
        return self.service.snapshot()

    async def save_settings(self, values):
        try:
            return {"ok": True, "snapshot": self.service.save_settings(values)}
        except ValueError as err:
            return {"ok": False, "message": str(err)}

    async def set_secret(self, name, value):
        try:
            return {"ok": True, "snapshot": self.service.set_secret(name, value)}
        except ValueError as err:
            return {"ok": False, "message": str(err)}

    async def clear_secret(self, name):
        return {"ok": True, "snapshot": self.service.clear_secret(name)}

    async def import_from_file(self):
        return self.service.import_from_file()

    async def delete_import_file(self):
        return self.service.delete_import_file()

    async def test_connection(self):
        try:
            return await self.service.test_connection()
        except Exception as exc:  # noqa: BLE001
            return error_result(exc)

    async def set_visible(self, visible):
        self.service.set_visible(visible)

    async def set_route_visible(self, visible):
        self.service.set_route_visible(visible)

    async def set_game_running(self, running):
        self.service.set_game_running(running)

    async def refresh(self):
        self.service.poller.wake()

    async def check_update(self, force=False):
        return await self.service.check_update(force)

    async def torrent_action(self, action, hashes):
        try:
            return await self.service.torrent_action(action, hashes)
        except Exception as exc:  # noqa: BLE001
            return error_result(exc)

    async def delete_torrents(self, hashes, delete_files):
        try:
            return await self.service.delete_torrents(hashes, delete_files)
        except Exception as exc:  # noqa: BLE001
            return error_result(exc)

    async def toggle_alt_speed(self):
        try:
            return await self.service.toggle_alt_speed()
        except Exception as exc:  # noqa: BLE001
            return error_result(exc)

    async def _guard(self, coro):
        try:
            return await coro
        except Exception as exc:  # noqa: BLE001
            return error_result(exc)

    async def set_force_start(self, hashes, value):
        return await self._guard(self.service.set_force_start(hashes, value))

    async def queue_move(self, hashes, where):
        return await self._guard(self.service.queue_move(hashes, where))

    async def set_category(self, hashes, category):
        return await self._guard(self.service.set_category(hashes, category))

    async def set_speed_limit(self, direction, limit):
        return await self._guard(self.service.set_speed_limit(direction, limit))

    async def set_session_paused(self, paused):
        return await self._guard(self.service.set_session_paused(paused))

    async def list_torrents(self, filter_id="all", category=None, sort="activity"):
        try:
            return self.service.list_torrents(filter_id, category, sort)
        except Exception as exc:  # noqa: BLE001
            return error_result(exc)
