import { addEventListener, callable, definePlugin, removeEventListener, toaster, useQuickAccessVisible } from "@decky/api";
import {
  ButtonItem,
  ConfirmModal,
  DialogButton,
  DropdownItem,
  Field,
  Focusable,
  ModalRoot,
  PanelSection,
  PanelSectionRow,
  ProgressBar,
  TextField,
  ToggleField,
  showModal,
  staticClasses,
} from "@decky/ui";
import { useEffect, useState } from "react";
import { FaMagnet } from "react-icons/fa";
import { monitorBackend, type ActionResult, type Snapshot, type Status, type UpdateInfo } from "./shared/backend";
import { ConnectionForm } from "./shared/ConnectionForm";
import { formatSpeed } from "./shared/format";
import { watchGameRunning } from "./shared/gameState";
import { OfflineBanner } from "./shared/OfflineBanner";
import { StatusHeader } from "./shared/StatusHeader";
import { shouldToast } from "./shared/toastOnce";
import { UpdateBadge } from "./shared/UpdateBadge";
import { useBackendEvent } from "./shared/useBackendEvent";
import { AUTH_OPTIONS, authHelp, canStart, rowDetail, rowTitle } from "./rows";
import type { AuthMode, QbtData, QbtSettings, Toast, Torrent } from "./types";

// plugin.json "name", exactly. Decky lists the plugin by it and matches the
// installed copy by it when Update now replaces the plugin.
const PLUGIN_NAME = "qBittorrent Monitor";

type Snap = Snapshot<QbtSettings, QbtData>;

const backend = monitorBackend<QbtSettings, QbtData>();
const torrentAction = callable<[action: "start" | "stop" | "recheck", hashes: string[] | "all"], ActionResult>(
  "torrent_action",
);
const deleteTorrents = callable<[hashes: string[], deleteFiles: boolean], ActionResult>("delete_torrents");
const toggleAltSpeed = callable<[], ActionResult>("toggle_alt_speed");

const note: React.CSSProperties = { fontSize: 12, lineHeight: 1.35 };

function failed(res: ActionResult, what: string) {
  if (!res.ok) toaster.toast({ title: `${what} failed`, body: res.error?.message ?? res.message ?? "Try again." });
}

function DeleteModal({ torrent, closeModal }: { torrent: Torrent; closeModal?: () => void }) {
  const [withFiles, setWithFiles] = useState(false);
  return (
    <ConfirmModal
      closeModal={closeModal}
      strTitle="Delete torrent?"
      strDescription={
        <>
          <div style={{ marginBottom: 12 }}>{torrent.name}</div>
          <ToggleField
            label="Also delete downloaded files"
            description={withFiles ? "Files are removed from disk. This cannot be undone." : "Files stay on disk."}
            checked={withFiles}
            onChange={setWithFiles}
          />
        </>
      }
      strOKButtonText={withFiles ? "Delete torrent and files" : "Delete torrent"}
      bDestructiveWarning={withFiles}
      onOK={async () => failed(await deleteTorrents([torrent.hash], withFiles), "Delete")}
    />
  );
}

function ActionsModal({ torrent, closeModal }: { torrent: Torrent; closeModal?: () => void }) {
  const run = async (fn: () => Promise<ActionResult>, what: string) => {
    closeModal?.();
    failed(await fn(), what);
  };
  return (
    <ModalRoot closeModal={closeModal}>
      <div className={staticClasses.Title} style={{ marginBottom: 8 }}>
        {torrent.name}
      </div>
      <div style={{ ...note, marginBottom: 16 }}>{rowDetail(torrent)}</div>
      <Focusable style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {canStart(torrent) ? (
          <DialogButton onClick={() => run(() => torrentAction("start", [torrent.hash]), "Start")}>Start</DialogButton>
        ) : (
          <DialogButton onClick={() => run(() => torrentAction("stop", [torrent.hash]), "Stop")}>Stop</DialogButton>
        )}
        <DialogButton onClick={() => run(() => torrentAction("recheck", [torrent.hash]), "Recheck")}>
          Recheck
        </DialogButton>
        <DialogButton
          onClick={() => {
            closeModal?.();
            showModal(<DeleteModal torrent={torrent} />);
          }}
        >
          Delete...
        </DialogButton>
        <DialogButton onClick={() => closeModal?.()}>Close</DialogButton>
      </Focusable>
    </ModalRoot>
  );
}

function TorrentRow({ torrent }: { torrent: Torrent }) {
  return (
    <PanelSectionRow>
      <ButtonItem
        layout="below"
        bottomSeparator="none"
        description={
          <>
            <ProgressBar nProgress={torrent.progress * 100} />
            <div style={{ ...note, marginTop: 4 }}>{rowDetail(torrent)}</div>
          </>
        }
        onClick={() => showModal(<ActionsModal torrent={torrent} />)}
      >
        <span style={{ fontSize: 13, wordBreak: "break-word" }}>{rowTitle(torrent)}</span>
      </ButtonItem>
    </PanelSectionRow>
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

  return (
    <>
      <PanelSection>
        <StatusHeader
          status={status}
          summary={
            server && online ? (
              <span style={note}>
                down {formatSpeed(server.dl_speed)} | up {formatSpeed(server.up_speed)}
              </span>
            ) : undefined
          }
        />
        <OfflineBanner status={status} />
        <UpdateBadge update={update} name={PLUGIN_NAME} />
        {online && server && (
          <PanelSectionRow>
            <ToggleField
              label="Alternative speed limits"
              checked={server.alt_speed}
              onChange={async () => failed(await toggleAltSpeed(), "Speed limit change")}
            />
          </PanelSectionRow>
        )}
      </PanelSection>

      {online && data && (
        <PanelSection title={`Torrents (${data.active} active of ${data.total})`}>
          {data.torrents.length === 0 && (
            <PanelSectionRow>
              <div style={note}>No torrents.</div>
            </PanelSectionRow>
          )}
          {data.torrents.map((t) => (
            <TorrentRow key={t.hash} torrent={t} />
          ))}
          {data.total > 0 && (
            <>
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

      <PanelSection title="Settings">
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => setShowSettings(!showSettings)}>
            {showSettings ? "Hide settings" : "Show settings"}
          </ButtonItem>
        </PanelSectionRow>
        {showSettings && (
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
  const onNotify = addEventListener<[Toast]>("notify", (toast) => {
    if (shouldToast(toast.key)) toaster.toast({ title: toast.title, body: toast.body });
  });
  const stopWatching = watchGameRunning((running) => {
    backend.setGameRunning(running);
  });

  return {
    name: PLUGIN_NAME,
    titleView: <div className={staticClasses.Title}>qBittorrent Monitor</div>,
    content: <Content />,
    icon: <FaMagnet />,
    onDismount() {
      removeEventListener("notify", onNotify);
      stopWatching();
    },
  };
});
