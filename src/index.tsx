import {
  addEventListener,
  callable,
  definePlugin,
  removeEventListener,
  routerHook,
  toaster,
  useQuickAccessVisible,
} from "@decky/api";
import {
  ButtonItem,
  ConfirmModal,
  DropdownItem,
  Field,
  PanelSection,
  PanelSectionRow,
  SliderField,
  TextField,
  ToggleField,
  showModal,
  staticClasses,
} from "@decky/ui";
import { useEffect, useRef, useState } from "react";
import { FaMagnet } from "react-icons/fa";
import { monitorBackend, type ActionResult, type Snapshot, type Status, type UpdateInfo } from "./shared/backend";
import { ConnectionForm } from "./shared/ConnectionForm";
import { formatSpeed } from "./shared/format";
import { openPage } from "./shared/FullPage";
import { watchGameRunning } from "./shared/gameState";
import { OfflineBanner } from "./shared/OfflineBanner";
import { StatusHeader } from "./shared/StatusHeader";
import { shouldToast } from "./shared/toastOnce";
import { PanelBoundary } from "./shared/PanelBoundary";
import { UpdateBadge } from "./shared/UpdateBadge";
import { UpdatesSection } from "./shared/UpdatesSection";
import { useBackendEvent } from "./shared/useBackendEvent";
import {
  AUTH_OPTIONS,
  DOWNLOAD_PRESETS,
  UPLOAD_PRESETS,
  authHelp,
  connectionNote,
  leftSummary,
  limitLabel,
  presetIndex,
  statsLines,
} from "./rows";
import { TorrentRow, failed, note, torrentAction } from "./torrents";
import { TORRENTS_ROUTE, TorrentsPage } from "./TorrentsPage";
import type { AuthMode, QbtData, QbtSettings, ServerState, Toast } from "./types";

// plugin.json "name", exactly. Decky lists the plugin by it and matches the
// installed copy by it when Update now replaces the plugin.
const PLUGIN_NAME = "qBittorrent Monitor";

type Snap = Snapshot<QbtSettings, QbtData>;

const backend = monitorBackend<QbtSettings, QbtData>();
const toggleAltSpeed = callable<[], ActionResult>("toggle_alt_speed");
const setSpeedLimit = callable<[direction: "download" | "upload", limit: number], ActionResult>("set_speed_limit");
const setSessionPaused = callable<[paused: boolean], ActionResult>("set_session_paused");

const warnNote: React.CSSProperties = { ...note, color: "#e0a030" };

// A notched slider over the presets. It waits for the stick to settle before it
// sends the limit, so moving across notches sends one request, not several.
function LimitSlider({
  label,
  presets,
  limit,
  direction,
}: {
  label: string;
  presets: number[];
  limit: number;
  direction: "download" | "upload";
}) {
  const [index, setIndex] = useState(presetIndex(presets, limit));
  const timer = useRef<number | undefined>(undefined);
  // The notch waiting to be sent, or null.
  const pending = useRef<number | null>(null);
  const mounted = useRef(true);
  const latest = useRef(limit);
  latest.current = limit;

  const send = async (value: number) => {
    pending.current = null;
    const res = await setSpeedLimit(direction, presets[value]);
    failed(res, "Speed limit change");
    // On failure, go back to the limit the server still has.
    if (!res.ok && mounted.current) setIndex(presetIndex(presets, latest.current));
  };
  useEffect(() => {
    if (pending.current === null) setIndex(presetIndex(presets, limit));
  }, [limit]);
  useEffect(
    () => () => {
      mounted.current = false;
      window.clearTimeout(timer.current);
      // The panel closed before the stick settled. Send the change anyway.
      if (pending.current !== null) void send(pending.current);
    },
    [],
  );
  const onChange = (value: number) => {
    setIndex(value);
    pending.current = value;
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => void send(value), 700);
  };
  // A limit set elsewhere may sit between notches. Name the real value then.
  const offPreset = pending.current === null && !presets.includes(limit);
  return (
    <SliderField
      label={label}
      description={
        <span style={note}>{offPreset ? `Now ${limitLabel(limit)}` : limitLabel(presets[index])}</span>
      }
      value={index}
      min={0}
      max={presets.length - 1}
      step={1}
      notchCount={presets.length}
      notchTicksVisible
      onChange={onChange}
    />
  );
}

function ServerSection({ server }: { server: ServerState }) {
  const health = connectionNote(server);
  const lines = statsLines(server);
  return (
    <PanelSection title="Server">
      <PanelSectionRow>
        <ToggleField
          label="Alternative speed limits"
          checked={server.alt_speed}
          onChange={async () => failed(await toggleAltSpeed(), "Speed limit change")}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <LimitSlider
          label={server.alt_speed ? "Download limit (alternative)" : "Download limit"}
          presets={DOWNLOAD_PRESETS}
          limit={server.dl_limit}
          direction="download"
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <LimitSlider
          label={server.alt_speed ? "Upload limit (alternative)" : "Upload limit"}
          presets={UPLOAD_PRESETS}
          limit={server.up_limit}
          direction="upload"
        />
      </PanelSectionRow>
      {server.session_paused !== null && (
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            description={
              <span style={note}>
                {server.session_paused
                  ? "Every torrent is held as it was. Resume to carry on."
                  : "Stops all traffic but keeps each torrent's state, unlike Stop all."}
              </span>
            }
            onClick={async () => failed(await setSessionPaused(!server.session_paused), "Pause all traffic")}
          >
            {server.session_paused ? "Resume all traffic" : "Pause all traffic"}
          </ButtonItem>
        </PanelSectionRow>
      )}
      {(lines.length > 0 || health) && (
        <PanelSectionRow>
          <Field focusable bottomSeparator="none" childrenLayout="below">
            {lines.map((line) => (
              <div key={line} style={note}>
                {line}
              </div>
            ))}
            {health && <div style={health.warn ? warnNote : note}>{health.text}</div>}
          </Field>
        </PanelSectionRow>
      )}
    </PanelSection>
  );
}

function AuthFields({ snapshot, onSnapshot }: { snapshot: Snap; onSnapshot: (s: Snap) => void }) {
  const [username, setUsername] = useState(snapshot.settings.username);
  useEffect(() => setUsername(snapshot.settings.username), [snapshot.settings.username]);
  const save = async (values: Partial<QbtSettings>) => {
    const res = await backend.saveSettings(values);
    if (res.snapshot) onSnapshot(res.snapshot);
  };
  const mode = snapshot.settings.auth_mode;
  return (
    <>
      <PanelSectionRow>
        <DropdownItem
          label="Sign-in"
          description={<span style={note}>{authHelp(mode)}</span>}
          rgOptions={AUTH_OPTIONS}
          selectedOption={mode}
          onChange={(o) => save({ auth_mode: o.data as AuthMode })}
        />
      </PanelSectionRow>
      {mode === "password" && (
        <PanelSectionRow>
          <TextField
            label="Username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            onBlur={() => username !== snapshot.settings.username && save({ username })}
          />
        </PanelSectionRow>
      )}
    </>
  );
}

function Content() {
  const visible = useQuickAccessVisible();
  const [snap, setSnap] = useState<Snap | null>(null);
  const [status, setStatus] = useState<Status | null>(null);
  const [data, setData] = useState<QbtData | null>(null);
  const [update, setUpdate] = useState<UpdateInfo | null>(null);
  const [showSettings, setShowSettings] = useState(false);

  const apply = (s: Snap) => {
    setSnap(s);
    setStatus(s.status);
    setData(s.data);
    setUpdate(s.update);
  };

  useEffect(() => {
    backend.getSnapshot().then((s) => {
      apply(s);
      if (!s.settings.base_url) setShowSettings(true);
    });
  }, []);

  useEffect(() => {
    backend.setVisible(visible);
    return () => {
      backend.setVisible(false);
    };
  }, [visible]);

  useBackendEvent<Status>("status", setStatus);
  useBackendEvent<QbtData>("data", setData);
  useBackendEvent<UpdateInfo | null>("update", setUpdate);

  if (!snap) {
    return (
      <PanelSection>
        <PanelSectionRow>
          <div style={note}>Loading...</div>
        </PanelSectionRow>
      </PanelSection>
    );
  }

  const online = status?.state === "online";
  const server = data?.server;
  const keyFields =
    snap.settings.auth_mode === "password"
      ? [{ name: "password", label: "Password" }, { name: "api_key", label: "API key", description: "Optional." }]
      : snap.settings.auth_mode === "api_key"
        ? [{ name: "api_key", label: "API key" }]
        : [];

  const left = server && online ? leftSummary(server) : null;
  const context = { queueing: server?.queueing ?? false, categories: data?.categories ?? [] };

  return (
    <>
      <PanelSection>
        <StatusHeader
          status={status}
          summary={
            server && online ? (
              <span style={note}>
                down {formatSpeed(server.dl_speed)} | up {formatSpeed(server.up_speed)}
                {left && <div>{left}</div>}
              </span>
            ) : undefined
          }
        />
        <OfflineBanner status={status} />
        <UpdateBadge update={update} name={PLUGIN_NAME} />
      </PanelSection>

      {online && data && (
        <PanelSection title={`Torrents (${data.active} active of ${data.total})`}>
          {data.torrents.length === 0 && (
            <PanelSectionRow>
              <div style={note}>No torrents.</div>
            </PanelSectionRow>
          )}
          {data.torrents.map((t) => (
            <TorrentRow key={t.hash} torrent={t} server={context} />
          ))}
          {data.total > 0 && (
            <>
              {data.total > data.torrents.length && (
                <PanelSectionRow>
                  <ButtonItem layout="below" onClick={() => openPage(TORRENTS_ROUTE)}>
                    All {data.total} torrents...
                  </ButtonItem>
                </PanelSectionRow>
              )}
              <PanelSectionRow>
                <ButtonItem layout="below" onClick={async () => failed(await torrentAction("start", "all"), "Start all")}>
                  Start all
                </ButtonItem>
              </PanelSectionRow>
              <PanelSectionRow>
                <ButtonItem
                  layout="below"
                  onClick={() =>
                    showModal(
                      <ConfirmModal
                        strTitle="Stop all torrents?"
                        strDescription="Every torrent stops downloading and seeding."
                        strOKButtonText="Stop all"
                        onOK={async () => failed(await torrentAction("stop", "all"), "Stop all")}
                      />,
                    )
                  }
                >
                  Stop all
                </ButtonItem>
              </PanelSectionRow>
            </>
          )}
        </PanelSection>
      )}

      {online && server && <ServerSection server={server} />}

      <UpdatesSection update={update} name={PLUGIN_NAME} check={() => backend.checkUpdate(true)} />
      <PanelSection title="Settings">
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => setShowSettings(!showSettings)}>
            {showSettings ? "Hide settings" : "Show settings"}
          </ButtonItem>
        </PanelSectionRow>
        {showSettings && (
          <>
            <ConnectionForm
              snapshot={snap}
              backend={backend}
              onSnapshot={apply}
              secretFields={keyFields}
              urlPlaceholder="http://192.168.x.x:8090"
              urlDescription="The WebUI address, for example http://192.168.x.x:8090 or https://qbt.example.com."
            >
              <AuthFields snapshot={snap} onSnapshot={apply} />
            </ConnectionForm>
            <PanelSectionRow>
              <ToggleField
                label="Alternative speed while gaming"
                description={
                  <span style={note}>
                    Turns on alternative speed limits when a game starts and off when it ends. Leaves them alone if
                    you had them on already.
                  </span>
                }
                checked={snap.settings.game_alt_speed}
                onChange={async (v) => {
                  const res = await backend.saveSettings({ game_alt_speed: v });
                  if (res.snapshot) apply(res.snapshot);
                }}
              />
            </PanelSectionRow>
          </>
        )}
        <PanelSectionRow>
          <Field label="Version" bottomSeparator="none" focusable={false}>
            <span style={note}>{snap.version}</span>
          </Field>
        </PanelSectionRow>
      </PanelSection>
    </>
  );
}

export default definePlugin(() => {
  routerHook.addRoute(TORRENTS_ROUTE, () => (
    <PanelBoundary>
      <TorrentsPage />
    </PanelBoundary>
  ));
  const onNotify = addEventListener<[Toast]>("notify", (toast) => {
    if (shouldToast(toast.key)) toaster.toast({ title: toast.title, body: toast.body });
  });
  const stopWatching = watchGameRunning((running) => {
    backend.setGameRunning(running);
  });

  return {
    name: PLUGIN_NAME,
    titleView: <div className={staticClasses.Title}>qBittorrent Monitor</div>,
    content: (
      <PanelBoundary>
        <Content />
      </PanelBoundary>
    ),
    icon: <FaMagnet />,
    onDismount() {
      routerHook.removeRoute(TORRENTS_ROUTE);
      removeEventListener("notify", onNotify);
      stopWatching();
    },
  };
});
