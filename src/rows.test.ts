import { describe, expect, it } from "vitest";
import {
  DOWNLOAD_PRESETS,
  authHelp,
  canStart,
  categoryOptions,
  connectionNote,
  leftSummary,
  limitLabel,
  presetIndex,
  rowDetail,
  rowTitle,
  statsLines,
} from "./rows";
import type { ServerState, Torrent } from "./types";

const base: Torrent = {
  hash: "h",
  name: "Example",
  progress: 0.5,
  eta: 120,
  dlspeed: 1_000_000,
  upspeed: 0,
  state: "downloading",
  label: "Downloading",
  stopped: false,
  size: 1,
  category: "",
  force_start: false,
  queue_pos: null,
  ratio: 0,
};

const server: ServerState = {
  dl_speed: 2_000_000,
  up_speed: 0,
  alt_speed: false,
  connection_status: "connected",
  free_space: 100_000_000_000,
  dl_limit: 0,
  up_limit: 0,
  dl_session: 5_000_000_000,
  up_session: 1_200_000_000,
  ratio: 1.25,
  dht_nodes: 312,
  queueing: true,
  session_paused: false,
  left: 2_320_000_000,
  eta: 1160,
};

describe("torrent rows", () => {
  it("shows label, percent, ETA and speed while downloading", () => {
    expect(rowDetail(base)).toBe("Downloading | 50% | 2m 0s | down 1.00 MB/s");
  });

  it("shows No ETA for the infinite value the backend maps to null", () => {
    expect(rowDetail({ ...base, eta: null, dlspeed: 0, label: "Stalled" })).toBe("Stalled | 50% | No ETA");
  });

  it("hides ETA once complete or stopped", () => {
    expect(rowDetail({ ...base, progress: 1, label: "Seeding", dlspeed: 0, upspeed: 5000 })).toBe(
      "Seeding | 100% | up 5.00 KB/s",
    );
    expect(rowDetail({ ...base, stopped: true, label: "Stopped", dlspeed: 0 })).toBe("Stopped | 50%");
  });

  it("offers Start for stopped and errored torrents", () => {
    expect(canStart({ ...base, stopped: true })).toBe(true);
    expect(canStart({ ...base, label: "Error" })).toBe(true);
    expect(canStart(base)).toBe(false);
  });

  it("names unnamed torrents", () => {
    expect(rowTitle({ ...base, name: "" })).toBe("Unnamed torrent");
  });

  it("has help for every auth mode", () => {
    for (const mode of ["api_key", "password", "none"] as const) expect(authHelp(mode)).toBeTruthy();
  });
});

describe("queue and force start", () => {
  it("marks forced torrents and shows the queue position", () => {
    expect(rowDetail({ ...base, force_start: true, dlspeed: 0 })).toBe("Downloading (forced) | 50% | 2m 0s");
    expect(rowDetail({ ...base, label: "Queued", queue_pos: 3, dlspeed: 0, eta: null })).toBe(
      "Queued | 50% | #3 in queue | No ETA",
    );
  });
});

describe("server stats", () => {
  it("sums what is left with a rough ETA", () => {
    expect(leftSummary(server)).toBe("2.32 GB left, about 19m 20s");
    expect(leftSummary({ ...server, eta: null })).toBe("2.32 GB left, No ETA");
    expect(leftSummary({ ...server, left: 0 })).toBeNull();
    expect(leftSummary({ ...server, session_paused: true })).toBe("All traffic paused");
  });

  it("lists only the stats the server sent", () => {
    expect(statsLines(server)).toEqual([
      "Free space: 100 GB",
      "This session: 5.00 GB down, 1.20 GB up",
      "All-time ratio: 1.25",
    ]);
    expect(statsLines({ ...server, free_space: null, dl_session: null, ratio: null })).toEqual([]);
  });

  it("warns when firewalled or disconnected", () => {
    expect(connectionNote(server)).toEqual({ text: "Network: connected, 312 DHT nodes", warn: false });
    expect(connectionNote({ ...server, connection_status: "firewalled" })?.warn).toBe(true);
    expect(connectionNote({ ...server, connection_status: "disconnected" })?.warn).toBe(true);
    expect(connectionNote({ ...server, connection_status: "" })).toBeNull();
  });
});

describe("speed limit presets", () => {
  it("puts no limit on the last notch and snaps others to the nearest", () => {
    expect(presetIndex(DOWNLOAD_PRESETS, 0)).toBe(DOWNLOAD_PRESETS.length - 1);
    expect(presetIndex(DOWNLOAD_PRESETS, 5_000_000)).toBe(2);
    expect(presetIndex(DOWNLOAD_PRESETS, 4_000_000)).toBe(2);
    expect(presetIndex(DOWNLOAD_PRESETS, 900_000_000)).toBe(5);
    expect(limitLabel(0)).toBe("No limit");
    expect(limitLabel(5_000_000)).toBe("5.00 MB/s");
  });
});

describe("category filter", () => {
  it("offers any, none, then each category", () => {
    const options = categoryOptions(["iso"]);
    expect(options.map((o) => o.label)).toEqual(["Any category", "No category", "iso"]);
    expect(options[1].data).toBe("");
  });
});
