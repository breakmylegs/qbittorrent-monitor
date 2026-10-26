// Pure row formatting for the torrent list. Tested with vitest.
import { formatDuration, formatPercent, formatSpeed, truncate } from "./shared/format";
import type { AuthMode, Torrent } from "./types";

export function rowTitle(t: Torrent): string {
  return truncate(t.name || "Unnamed torrent", 60);
}

export function rowDetail(t: Torrent): string {
  const parts = [t.label, formatPercent(t.progress)];
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
