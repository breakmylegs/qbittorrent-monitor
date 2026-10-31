import { DropdownItem, PanelSectionRow } from "@decky/ui";
import { useEffect, useRef, useState } from "react";
import { monitorBackend } from "./shared/backend";
import { FullPage } from "./shared/FullPage";
import { useBackendEvent } from "./shared/useBackendEvent";
import { ANY_CATEGORY, FILTER_OPTIONS, SORT_OPTIONS, categoryOptions } from "./rows";
import { TorrentRow, listTorrents, note } from "./torrents";
import type { FilterId, QbtData, QbtSettings, SortId, TorrentList } from "./types";

export const TORRENTS_ROUTE = "/qbittorrent-monitor/torrents";

const backend = monitorBackend<QbtSettings, QbtData>();

// Every torrent, with filters. The list comes from the backend's cache, so
// paging through it sends nothing to the server.
export function TorrentsPage() {
  const [data, setData] = useState<QbtData | null>(null);
  const [list, setList] = useState<TorrentList | null>(null);
  const [filter, setFilter] = useState<FilterId>("all");
  const [category, setCategory] = useState<string>(ANY_CATEGORY);
  const [sort, setSort] = useState<SortId>("activity");

  // Filters can change while a request runs. Keep only the newest reply.
  const latest = useRef(0);
  const load = () => {
    const id = ++latest.current;
    return listTorrents(filter, category === ANY_CATEGORY ? null : category, sort).then((res) => {
      if (id === latest.current && res.ok) setList(res);
    });
  };

  useEffect(() => {
    backend.getSnapshot().then((s) => setData(s.data));
  }, []);
  useEffect(() => {
    load();
  }, [filter, category, sort, data]);
  useBackendEvent<QbtData>("data", setData);

  const server = { queueing: data?.server.queueing ?? false, categories: data?.categories ?? [] };
  const menu = { bShiftToFitWindow: true, bFitToWindow: true };

  return (
    <FullPage title="Torrents" onVisible={(v) => backend.setRouteVisible(v)}>
      <PanelSectionRow>
        <DropdownItem
          label="Show"
          rgOptions={FILTER_OPTIONS}
          selectedOption={filter}
          menuLabel="Show"
          contextMenuPositionOptions={menu}
          onChange={(o) => setFilter(o.data as FilterId)}
        />
      </PanelSectionRow>
      {server.categories.length > 0 && (
        <PanelSectionRow>
          <DropdownItem
            label="Category"
            rgOptions={categoryOptions(server.categories)}
            selectedOption={category}
            contextMenuPositionOptions={menu}
            onChange={(o) => setCategory(o.data as string)}
          />
        </PanelSectionRow>
      )}
      <PanelSectionRow>
        <DropdownItem
          label="Sort by"
          rgOptions={SORT_OPTIONS}
          selectedOption={sort}
          contextMenuPositionOptions={menu}
          onChange={(o) => setSort(o.data as SortId)}
        />
      </PanelSectionRow>
      {list === null && <div style={note}>Loading...</div>}
      {list && (
        <div style={{ ...note, margin: "8px 0" }}>
          {list.matched === list.total ? `${list.total} torrents` : `${list.matched} of ${list.total} torrents`}
          {list.matched > list.limit ? `. Showing the first ${list.limit}.` : ""}
        </div>
      )}
      {list?.torrents.length === 0 && <div style={note}>No torrents match.</div>}
      {list?.torrents.map((t) => <TorrentRow key={t.hash} torrent={t} server={server} />)}
    </FullPage>
  );
}
