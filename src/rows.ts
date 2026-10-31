// Pure row formatting for the torrent list. Tested with vitest.
import { formatBytes, formatDuration, formatPercent, formatSpeed, truncate } from "./shared/format";
import type { AuthMode, FilterId, ServerState, SortId, Torrent } from "./types";

export function rowTitle(t: Torrent): string {
  return truncate(t.name || "Unnamed torrent", 60);
}

export function rowDetail(t: Torrent): string {
  const parts = [t.force_start ? `${t.label} (forced)` : t.label, formatPercent(t.progress)];
  if (t.label === "Queued" && t.queue_pos !== null) parts.push(`#${t.queue_pos} in queue`);
  if (t.progress < 1 && !t.stopped) parts.push(t.eta === null ? "No ETA" : formatDuration(t.eta));
  if (t.dlspeed > 0) parts.push(`down ${formatSpeed(t.dlspeed)}`);
  if (t.upspeed > 0) parts.push(`up ${formatSpeed(t.upspeed)}`);
  return parts.join(" | ");
}

export function canStart(t: Torrent): boolean {
  return t.stopped || t.label === "Error";
}

export const AUTH_OPTIONS: { data: AuthMode; label: string }[] = [
  { data: "api_key", label: "API key (qBittorrent 5.2 or newer)" },
  { data: "password", label: "Username and password" },
  { data: "none", label: "None (IP whitelist)" },
];

export function authHelp(mode: AuthMode): string {
  switch (mode) {
    case "api_key":
      return "Create a key in qBittorrent, Options, WebUI. It is sent with every request.";
    case "password":
      return "The WebUI username and password. An API key is still sent if one is stored.";
    case "none":
      return "Works when qBittorrent bypasses auth for this device. Whitelist one address with a DHCP reservation, not the whole subnet.";
  }
}

// Header line under the speeds: how much is left and roughly how long.
export function leftSummary(s: ServerState): string | null {
  if (s.session_paused) return "All traffic paused";
  if (!s.left) return null;
  const eta = s.eta === null ? "No ETA" : `about ${formatDuration(s.eta)}`;
  return `${formatBytes(s.left)} left, ${eta}`;
}

export function statsLines(s: ServerState): string[] {
  const lines: string[] = [];
  if (s.free_space !== null) lines.push(`Free space: ${formatBytes(s.free_space)}`);
  if (s.dl_session !== null && s.up_session !== null) {
    lines.push(`This session: ${formatBytes(s.dl_session)} down, ${formatBytes(s.up_session)} up`);
  }
  if (s.ratio !== null) lines.push(`All-time ratio: ${s.ratio.toFixed(2)}`);
  return lines;
}

// One line on network health. Firewalled and no DHT nodes both explain slow torrents.
export function connectionNote(s: ServerState): { text: string; warn: boolean } | null {
  const nodes = s.dht_nodes === null ? "" : `, ${s.dht_nodes} DHT nodes`;
  switch (s.connection_status) {
    case "connected":
      return { text: `Network: connected${nodes}`, warn: false };
    case "firewalled":
      return { text: `Network: firewalled${nodes}. Peers cannot connect in, so torrents may be slow. Forward the listening port on the server's router.`, warn: true };
    case "disconnected":
      return { text: "Network: disconnected. qBittorrent has no network connection.", warn: true };
    default:
      return null;
  }
}

// Speed limit presets in bytes per second. The last notch is no limit.
export const UNLIMITED = 0;
export const DOWNLOAD_PRESETS = [1_000_000, 2_000_000, 5_000_000, 10_000_000, 25_000_000, 50_000_000, UNLIMITED];
export const UPLOAD_PRESETS = [100_000, 250_000, 500_000, 1_000_000, 2_000_000, 5_000_000, UNLIMITED];

export function limitLabel(limit: number): string {
  return limit <= 0 ? "No limit" : formatSpeed(limit);
}

// The notch for a limit. A value between presets snaps to the nearest one, and
// "no limit" is always the last notch.
export function presetIndex(presets: number[], limit: number): number {
  if (limit <= 0) return presets.length - 1;
  let best = 0;
  presets.forEach((p, i) => {
    if (p > 0 && Math.abs(p - limit) < Math.abs(presets[best] - limit)) best = i;
  });
  return best;
}

export const FILTER_OPTIONS: { data: FilterId; label: string }[] = [
  { data: "all", label: "All" },
  { data: "active", label: "Moving data" },
  { data: "downloading", label: "Downloading" },
  { data: "seeding", label: "Seeding" },
  { data: "completed", label: "Completed" },
  { data: "stopped", label: "Stopped" },
  { data: "error", label: "Errors" },
];

export const SORT_OPTIONS: { data: SortId; label: string }[] = [
  { data: "activity", label: "Most active" },
  { data: "name", label: "Name" },
  { data: "added", label: "Newest" },
  { data: "size", label: "Largest" },
];

// Category filter values. null means any category, "" means none set.
export const ANY_CATEGORY = "\u0000any";

export function categoryOptions(categories: string[]): { data: string; label: string }[] {
  return [
    { data: ANY_CATEGORY, label: "Any category" },
    { data: "", label: "No category" },
    ...categories.map((c) => ({ data: c, label: c })),
  ];
}
