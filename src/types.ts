import type { CommonSettings } from "./shared/ConnectionForm";

export type AuthMode = "api_key" | "password" | "none";

export interface QbtSettings extends CommonSettings {
  auth_mode: AuthMode;
  username: string;
  game_alt_speed: boolean;
}

export interface Torrent {
  hash: string;
  name: string;
  progress: number;
  eta: number | null;
  dlspeed: number;
  upspeed: number;
  state: string;
  label: string;
  stopped: boolean;
  size: number;
  category: string;
  force_start: boolean;
  queue_pos: number | null;
  ratio: number;
}

export interface ServerState {
  dl_speed: number;
  up_speed: number;
  alt_speed: boolean;
  connection_status: string;
  free_space: number | null;
  // Limits for the current mode, normal or alternative, in bytes per second. 0 means none.
  dl_limit: number;
  up_limit: number;
  dl_session: number | null;
  up_session: number | null;
  ratio: number | null;
  dht_nodes: number | null;
  queueing: boolean;
  // null when the server is older than qBittorrent 5.3.
  session_paused: boolean | null;
  left: number;
  eta: number | null;
}

export interface QbtData {
  torrents: Torrent[];
  total: number;
  active: number;
  server: ServerState;
  categories: string[];
}

export type FilterId = "all" | "downloading" | "seeding" | "completed" | "stopped" | "active" | "error";
export type SortId = "activity" | "name" | "added" | "size";

export interface TorrentList {
  ok: boolean;
  torrents: Torrent[];
  matched: number;
  total: number;
  limit: number;
  error?: { kind: string; message: string };
}

export interface Toast {
  kind: "completed" | "error";
  key: string;
  title: string;
  body: string;
}
