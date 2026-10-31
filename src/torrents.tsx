import { callable, toaster } from "@decky/api";
import {
  ButtonItem,
  ConfirmModal,
  DialogButton,
  Focusable,
  ModalRoot,
  PanelSectionRow,
  ProgressBar,
  ToggleField,
  showModal,
  staticClasses,
} from "@decky/ui";
import { useState, type ReactElement } from "react";
import type { ActionResult } from "./shared/backend";
import { canStart, rowDetail, rowTitle } from "./rows";
import type { FilterId, SortId, Torrent, TorrentList } from "./types";

// Torrent rows and their action modals, shared by the panel and the full list.

export const torrentAction = callable<
  [action: "start" | "stop" | "recheck" | "reannounce", hashes: string[] | "all"],
  ActionResult
>("torrent_action");
const deleteTorrents = callable<[hashes: string[], deleteFiles: boolean], ActionResult>("delete_torrents");
const setForceStart = callable<[hashes: string[], value: boolean], ActionResult>("set_force_start");
const queueMove = callable<[hashes: string[], where: "top" | "bottom"], ActionResult>("queue_move");
const setCategory = callable<[hashes: string[], category: string], ActionResult>("set_category");
export const listTorrents = callable<[filterId: FilterId, category: string | null, sort: SortId], TorrentList>(
  "list_torrents",
);

export const note: React.CSSProperties = { fontSize: 12, lineHeight: 1.35 };

export function failed(res: ActionResult, what: string) {
  if (!res.ok) toaster.toast({ title: `${what} failed`, body: res.error?.message ?? res.message ?? "Try again." });
}

// What the action modal needs to know about the server.
export interface ServerContext {
  queueing: boolean;
  categories: string[];
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

function CategoryModal({
  torrent,
  categories,
  closeModal,
}: {
  torrent: Torrent;
  categories: string[];
  closeModal?: () => void;
}) {
  const pick = async (category: string) => {
    closeModal?.();
    failed(await setCategory([torrent.hash], category), "Category change");
  };
  return (
    <ModalRoot closeModal={closeModal}>
      <div className={staticClasses.Title} style={{ marginBottom: 8 }}>
        Category
      </div>
      <div style={{ ...note, marginBottom: 16 }}>{torrent.name}</div>
      <Focusable style={{ display: "flex", flexDirection: "column", gap: 8, maxHeight: 360, overflowY: "auto" }}>
        {torrent.category !== "" && <DialogButton onClick={() => pick("")}>No category</DialogButton>}
        {categories
          .filter((c) => c !== torrent.category)
          .map((c) => (
            <DialogButton key={c} onClick={() => pick(c)}>
              {c}
            </DialogButton>
          ))}
        <DialogButton onClick={() => closeModal?.()}>Cancel</DialogButton>
      </Focusable>
    </ModalRoot>
  );
}

function ActionsModal({
  torrent,
  server,
  closeModal,
}: {
  torrent: Torrent;
  server: ServerContext;
  closeModal?: () => void;
}) {
  const run = async (fn: () => Promise<ActionResult>, what: string) => {
    closeModal?.();
    failed(await fn(), what);
  };
  const then = (modal: ReactElement) => {
    closeModal?.();
    showModal(modal);
  };
  const hashes = [torrent.hash];
  return (
    <ModalRoot closeModal={closeModal}>
      <div className={staticClasses.Title} style={{ marginBottom: 8 }}>
        {torrent.name}
      </div>
      <div style={{ ...note, marginBottom: 16 }}>
        {rowDetail(torrent)}
        {torrent.category ? ` | ${torrent.category}` : ""}
        {torrent.progress >= 1 ? ` | ratio ${torrent.ratio.toFixed(2)}` : ""}
      </div>
      <Focusable style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {canStart(torrent) ? (
          <DialogButton onClick={() => run(() => torrentAction("start", hashes), "Start")}>Start</DialogButton>
        ) : (
          <DialogButton onClick={() => run(() => torrentAction("stop", hashes), "Stop")}>Stop</DialogButton>
        )}
        {torrent.force_start ? (
          <DialogButton onClick={() => run(() => setForceStart(hashes, false), "Force start")}>
            Stop forcing (follow the queue)
          </DialogButton>
        ) : (
          <DialogButton onClick={() => run(() => setForceStart(hashes, true), "Force start")}>
            Force start (skip the queue)
          </DialogButton>
        )}
        {server.queueing && torrent.queue_pos !== null && (
          <>
            <DialogButton onClick={() => run(() => queueMove(hashes, "top"), "Queue move")}>
              Move to top of queue
            </DialogButton>
            <DialogButton onClick={() => run(() => queueMove(hashes, "bottom"), "Queue move")}>
              Move to bottom of queue
            </DialogButton>
          </>
        )}
        <DialogButton onClick={() => run(() => torrentAction("reannounce", hashes), "Reannounce")}>
          Reannounce to trackers
        </DialogButton>
        <DialogButton onClick={() => run(() => torrentAction("recheck", hashes), "Recheck")}>Recheck</DialogButton>
        {(server.categories.length > 0 || torrent.category !== "") && (
          <DialogButton
            onClick={() => then(<CategoryModal torrent={torrent} categories={server.categories} />)}
          >
            Category...
          </DialogButton>
        )}
        <DialogButton onClick={() => then(<DeleteModal torrent={torrent} />)}>Delete...</DialogButton>
        <DialogButton onClick={() => closeModal?.()}>Close</DialogButton>
      </Focusable>
    </ModalRoot>
  );
}

export function TorrentRow({ torrent, server }: { torrent: Torrent; server: ServerContext }) {
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
        onClick={() => showModal(<ActionsModal torrent={torrent} server={server} />)}
      >
        <span style={{ fontSize: 13, wordBreak: "break-word" }}>{rowTitle(torrent)}</span>
      </ButtonItem>
    </PanelSectionRow>
  );
}
