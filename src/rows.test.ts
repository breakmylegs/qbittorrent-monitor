import { describe, expect, it } from "vitest";
import { authHelp, canStart, rowDetail, rowTitle } from "./rows";
import type { Torrent } from "./types";

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
