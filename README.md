# qBittorrent Monitor

A Decky Loader plugin. Watch and control a qBittorrent server from the Quick Access Menu on any Decky handheld.

- Download and upload speed, connection state and the alternative speed limit toggle.
- The 8 most active torrents with progress, ETA, speed and state.
- Start, stop, recheck and delete per torrent. Start all and stop all.
- A toast when a download completes or a torrent hits an error. Optional during games.

Issues and source: [breakmylegs/decky-plugins](https://github.com/breakmylegs/decky-plugins). This repo is a mirror for releases.

## Install

1. Decky Settings, General, turn on Developer mode.
2. Decky Settings, Developer, Install Plugin from URL.
3. Enter:

```
https://github.com/breakmylegs/qbittorrent-monitor/releases/latest/download/qbittorrent-monitor.zip
```

## Set up

1. Open the plugin in the Quick Access Menu, then Show settings.
2. Enter the WebUI address, for example `http://192.168.x.x:8090` or `https://qbt.example.com`.
3. Pick a sign-in method:
   - **API key** (qBittorrent 5.2 or newer). Create one in qBittorrent, Options, WebUI.
   - **Username and password.**
   - **None.** For a server that bypasses auth for this device. Whitelist this device's single address and give it a DHCP reservation. Do not whitelist the whole subnet.
4. Test connection. It reports each step and which sign-in path worked.

To avoid typing a long key on the on-screen keyboard, create `~/Documents/decky-import/qbittorrent-monitor.json` in Desktop Mode:

```json
{ "base_url": "http://192.168.x.x:8090", "auth_mode": "api_key", "api_key": "your key" }
```

Press Import from file, then delete the file when asked.

### Port 8080

Steam and Decky use port 8080 on the handheld. qBittorrent defaults to 8080 too. If qBittorrent runs on the handheld itself, move its WebUI to another port, such as 8090. The connection test warns you.

## Screenshots

To follow after on-device testing.

## Supported versions

| Component | Version |
|---|---|
| qBittorrent | 5.2 and 5.3 (API key needs 5.2 or newer). 4.6 and later best effort |
| Decky Loader | 3.0 and later. 3.3.0 tested |

## Data and privacy

The plugin talks only to the server you enter. Credentials stay in `~/homebrew/settings/qbittorrent-monitor/secrets.json` (mode 600) and never reach the panel, logs or events. Once a day it checks GitHub for a newer release. Turn that off in settings. Full detail in [PRIVACY.md](https://github.com/breakmylegs/decky-plugins/blob/main/docs/PRIVACY.md).

## Licence

GPL-3.0. See `LICENSE`.
