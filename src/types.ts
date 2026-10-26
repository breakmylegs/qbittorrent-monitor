import type { CommonSettings } from "./shared/ConnectionForm";

export type AuthMode = "api_key" | "password" | "none";

export interface QbtSettings extends CommonSettings {
  auth_mode: AuthMode;
  username: string;
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
}

export interface QbtData {
  torrents: Torrent[];
  total: number;
  active: number;
  server: {
    dl_speed: number;
    up_speed: number;
    alt_speed: boolean;
    connection_status: string;
    free_space: number | null;
  };
}

export interface Toast {
  kind: "completed" | "error";
  key: string;
  title: string;
  body: string;
}
