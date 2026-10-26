import asyncio
import json
import logging

import pytest

from plugin_core.errors import AUTH, FORBIDDEN, PluginError
from plugin_core.http import parse_base_url
from qbtmon import states
from qbtmon.client import MODE_API_KEY, MODE_NONE, MODE_PASSWORD, Credentials, QbtClient, join_hashes
from qbtmon.service import QbtService
from qbtmon.sync import MainData, TransitionTracker, project

mock_qbittorrent = pytest.importorskip("mock_qbittorrent")

KEY = "qbt_" + "k" * 28
A, B, C = "a" * 40, "b" * 40, "c" * 40


@pytest.fixture()
def mock():
    servers = []

    def make(**kwargs):
        server = mock_qbittorrent.MockQbt(**kwargs)
        server.start()
        servers.append(server)
        return server

    yield make
    for server in servers:
        server.stop()


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def make_service(tmp_path, events=None):
    events = events if events is not None else []

    async def emit(name, payload):
        events.append((name, payload))

    return QbtService(
        settings_dir=str(tmp_path / "settings"),
        runtime_dir=str(tmp_path / "runtime"),
        plugin_dir=str(tmp_path / "plugin"),
        user_home=str(tmp_path / "home"),
        version="0.1.0",
        emit=emit,
        logger=logging.getLogger("test"),
    )


# State mapping


@pytest.mark.parametrize(
    "state,label",
    [
        ("downloading", "Downloading"), ("forcedDL", "Downloading"), ("metaDL", "Fetching metadata"),
        ("forcedMetaDL", "Fetching metadata"), ("stalledDL", "Stalled"), ("queuedDL", "Queued"),
        ("queuedUP", "Queued"), ("stoppedDL", "Stopped"), ("pausedDL", "Stopped"),
        ("stoppedUP", "Completed"), ("pausedUP", "Completed"), ("uploading", "Seeding"),
        ("forcedUP", "Seeding"), ("stalledUP", "Seeding"), ("checkingDL", "Checking"),
        ("checkingUP", "Checking"), ("checkingResumeData", "Checking"), ("allocating", "Working"),
        ("moving", "Working"), ("error", "Error"), ("missingFiles", "Error"),
        ("somethingNew", "Unknown"), (None, "Unknown"),
    ],
)
def test_state_labels(state, label):
    assert states.label(state) == label


def test_infinite_eta_projects_to_none():
    data = MainData()
    data.apply({"rid": 1, "full_update": True, "torrents": {A: {"name": "x", "eta": 8640000, "state": "stalledDL"}}})
    assert project(data)["torrents"][0]["eta"] is None


# Incremental merge


def test_maindata_full_partial_removed_and_204():
    data = MainData()
    data.apply({"rid": 1, "full_update": True, "torrents": {A: {"name": "a", "progress": 0.1, "state": "downloading"},
                                                           B: {"name": "b", "progress": 1, "state": "uploading"}},
                "server_state": {"dl_info_speed": 5, "use_alt_speed_limits": False}})
    data.apply({"rid": 2, "torrents": {A: {"progress": 0.5}}, "server_state": {"dl_info_speed": 9}})
    assert data.torrents[A] == {"name": "a", "progress": 0.5, "state": "downloading"}
    assert data.server_state == {"dl_info_speed": 9, "use_alt_speed_limits": False}
    data.apply({"rid": 3, "torrents_removed": [B]})
    assert set(data.torrents) == {A} and data.rid == 3
    data.apply(None)
    assert data.rid == 3
    data.apply({"rid": 4, "full_update": True, "torrents": {C: {"name": "c"}}})
    assert set(data.torrents) == {C}


def test_projection_is_top_8_active_first():
    data = MainData()
    torrents = {f"{i:040d}": {"name": f"t{i}", "state": "stalledUP", "progress": 1, "added_on": i} for i in range(12)}
    torrents["f" * 40] = {"name": "busy", "state": "downloading", "progress": 0.2, "dlspeed": 100}
    data.apply({"rid": 1, "full_update": True, "torrents": torrents})
    out = project(data)
    assert len(out["torrents"]) == 8 and out["total"] == 13
    assert out["torrents"][0]["name"] == "busy"


def test_hashes_are_opaque_and_joined():
    assert join_hashes(["x1", "y2"]) == "x1|y2"
    assert join_hashes("all") == "all"
    with pytest.raises(ValueError):
        join_hashes(["a|b"])


# Transitions


def test_transitions_toast_once_and_skip_baseline():
    data, tracker = MainData(), TransitionTracker()
    data.apply({"rid": 1, "full_update": True, "torrents": {
        A: {"name": "a", "state": "downloading", "progress": 0.9},
        B: {"name": "b", "state": "uploading", "progress": 1}}})
    assert tracker.changes(data) == []
    data.apply({"rid": 2, "torrents": {A: {"state": "uploading", "progress": 1}}})
    assert [t["kind"] for t in tracker.changes(data)] == ["completed"]
    data.apply({"rid": 3, "torrents": {A: {"state": "stoppedUP"}}})
    assert tracker.changes(data) == []
    data.apply({"rid": 4, "torrents": {B: {"state": "missingFiles"}}})
    assert [t["kind"] for t in tracker.changes(data)] == ["error"]
    assert tracker.changes(data) == []


# Client against the mock


def test_api_key_auth(mock):
    server = mock(api_key=KEY)
    client = QbtClient(parse_base_url(server.url), Credentials(MODE_API_KEY, api_key=KEY))
    assert client.webapi_version() >= (2, 11, 0)
    assert client.maindata(0)["full_update"] is True
    client2 = QbtClient(parse_base_url(server.url), Credentials(MODE_API_KEY, api_key="wrong" * 6))
    with pytest.raises(PluginError) as info:
        client2.webapi_version()
    assert info.value.kind == FORBIDDEN


def test_password_auth_relogin_on_403(mock):
    server = mock(password="pw")
    client = QbtClient(parse_base_url(server.url), Credentials(MODE_PASSWORD, username="admin", password="pw"))
    assert client.app_version() == "v5.3.0"
    server.state.sessions.clear()
    assert client.app_version() == "v5.3.0"
    logins = [c for c in server.state.calls if c[1] == "auth/login"]
    assert len(logins) == 2
    # Referer and the port-suffixed cookie both went through.
    assert any(name.startswith("QBT_SID_") for name in (c.name for c in client.http.cookies))


@pytest.mark.parametrize("legacy", [False, True])
def test_password_auth_both_login_styles(mock, legacy):
    server = mock(password="pw", legacy_login=legacy, webapi="2.9.3" if legacy else "2.16.2")
    good = QbtClient(parse_base_url(server.url), Credentials(MODE_PASSWORD, username="admin", password="pw"))
    assert good.app_version()
    bad = QbtClient(parse_base_url(server.url), Credentials(MODE_PASSWORD, username="admin", password="no"))
    with pytest.raises(PluginError) as info:
        bad.app_version()
    assert info.value.kind == AUTH


def test_password_auth_wrong_password(mock):
    server = mock(password="pw")
    client = QbtClient(parse_base_url(server.url), Credentials(MODE_PASSWORD, username="admin", password="no"))
    with pytest.raises(PluginError) as info:
        client.app_version()
    assert info.value.kind == AUTH


def test_whitelist_no_credentials(mock):
    server = mock(whitelist=True)
    client = QbtClient(parse_base_url(server.url), Credentials(MODE_NONE))
    assert client.app_version() == "v5.3.0"


def test_204_means_no_change(mock):
    # qBittorrent 5.3 never sends 204 for maindata. The client still copes if one arrives.
    server = mock(api_key=KEY, support_204=True)
    client = QbtClient(parse_base_url(server.url), Credentials(MODE_API_KEY, api_key=KEY))
    rid = client.maindata(0)["rid"]
    assert client.maindata(rid) is None


def test_start_stop_verbs_follow_api_version(mock):
    new = mock(api_key=KEY)
    client = QbtClient(parse_base_url(new.url), Credentials(MODE_API_KEY, api_key=KEY))
    client.stop([A])
    client.start("all")
    assert [c[1] for c in new.state.calls if c[0] == "POST"] == ["torrents/stop", "torrents/start"]
    old = mock(api_key=KEY, webapi="2.9.3", version="v4.6.7")
    client = QbtClient(parse_base_url(old.url), Credentials(MODE_API_KEY, api_key=KEY))
    client.stop([A])
    client.start([A])
    assert [c[1] for c in old.state.calls if c[0] == "POST"] == ["torrents/pause", "torrents/resume"]


def test_delete_sends_delete_files_flag(mock):
    server = mock(api_key=KEY)
    client = QbtClient(parse_base_url(server.url), Credentials(MODE_API_KEY, api_key=KEY))
    client.delete([A], delete_files=False)
    method, path, form = server.state.calls[-1]
    assert (method, path, form) == ("POST", "torrents/delete", {"hashes": A, "deleteFiles": "false"})
    assert A not in server.state.torrents


# Service


def test_service_poll_and_notifications(mock, tmp_path):
    server = mock(api_key=KEY)
    events = []
    service = make_service(tmp_path, events)
    service.save_settings({"base_url": server.url})
    service.set_secret("api_key", KEY)

    async def scenario():
        await service.poller.poll_once()
        server.state.set_torrent(A, state="uploading", progress=1.0, dlspeed=0)
        await service.poller.poll_once()
        await service.poller.poll_once()

    _run(scenario())
    names = [e[0] for e in events]
    assert names.count("notify") == 1
    toast = next(p for n, p in events if n == "notify")
    assert toast["kind"] == "completed" and toast["body"] == "Example Linux ISO"
    data = service.last_data
    assert data["total"] == 3 and len(data["torrents"]) == 3
    assert KEY not in json.dumps(events) and KEY not in json.dumps(service.snapshot())


def test_service_suppresses_toasts_in_game_when_asked(mock, tmp_path):
    server = mock(api_key=KEY)
    events = []
    service = make_service(tmp_path, events)
    service.save_settings({"base_url": server.url, "notify_in_game": False})
    service.set_secret("api_key", KEY)
    service.set_game_running(True)

    async def scenario():
        await service.poller.poll_once()
        server.state.set_torrent(A, state="uploading", progress=1.0)
        await service.poller.poll_once()

    _run(scenario())
    assert "notify" not in [e[0] for e in events]


def test_service_unconfigured_status(tmp_path):
    events = []
    service = make_service(tmp_path, events)
    _run(service.poller.poll_once())
    assert events[-1][1]["state"] == "unconfigured"


def test_connection_test_paths(mock, tmp_path):
    server = mock(api_key=KEY)
    service = make_service(tmp_path)
    service.save_settings({"base_url": server.url})
    service.set_secret("api_key", KEY)
    report = _run(service.test_connection())
    assert report["ok"] and report["auth_path"] == "api_key" and report["server_version"] == "v5.3.0"

    service.set_secret("api_key", "bad" * 10)
    report = _run(service.test_connection())
    assert not report["ok"] and report["failed_step"] == "auth"

    open_server = mock(whitelist=True)
    service.save_settings({"base_url": open_server.url, "auth_mode": "none"})
    service.clear_secret("api_key")
    report = _run(service.test_connection())
    assert report["ok"] and report["auth_path"] == "whitelist"


def test_connection_test_whitelist_with_rejected_key(mock, tmp_path):
    server = mock(whitelist=True, api_key=KEY)
    service = make_service(tmp_path)
    service.save_settings({"base_url": server.url})
    service.set_secret("api_key", "bad" * 10)
    report = _run(service.test_connection())
    assert report["ok"] and report["auth_path"] == "whitelist"
    assert any("rejected the API key" in w for w in report["warnings"])


def test_connection_test_warns_on_local_8080(tmp_path):
    service = make_service(tmp_path)
    service.save_settings({"base_url": "http://localhost:8080"})
    report = _run(service.test_connection())
    assert any("8090" in w for w in report["warnings"])


def test_connection_test_wrong_path(mock, tmp_path):
    server = mock(api_key=KEY)
    service = make_service(tmp_path)
    service.save_settings({"base_url": server.url + "/nothing-here"})
    service.set_secret("api_key", KEY)
    report = _run(service.test_connection())
    assert report["failed_step"] == "version"


def test_actions_and_refresh(mock, tmp_path):
    server = mock(api_key=KEY)
    service = make_service(tmp_path)
    service.save_settings({"base_url": server.url})
    service.set_secret("api_key", KEY)
    assert _run(service.torrent_action("stop", [A])) == {"ok": True}
    assert server.state.torrents[A]["state"] == "stoppedDL"
    assert _run(service.toggle_alt_speed()) == {"ok": True}
    assert server.state.alt_speed is True
    assert _run(service.torrent_action("explode", [A]))["ok"] is False
    assert _run(service.delete_torrents("all", True))["ok"] is False


def test_import_from_file(tmp_path):
    service = make_service(tmp_path)
    path = tmp_path / "home" / "Documents" / "decky-import" / "qbittorrent-monitor.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"base_url": "http://192.0.2.5:8090", "api_key": KEY}))
    result = service.import_from_file()
    assert result["ok"] and result["imported"] == ["api_key", "base_url"]
    assert service.secrets.get("api_key") == KEY
    assert KEY not in json.dumps(result)
    assert service.delete_import_file()["ok"] and not path.exists()


def test_import_rejects_unknown_auth_mode(tmp_path):
    service = make_service(tmp_path)
    path = tmp_path / "home" / "Documents" / "decky-import" / "qbittorrent-monitor.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"auth_mode": "magic"}))
    result = service.import_from_file()
    assert result["ok"] is False and service.settings.get("auth_mode") == "api_key"
