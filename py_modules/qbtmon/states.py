"""qBittorrent torrent state labels.

qBittorrent 5 reports stoppedDL and stoppedUP. 4.6 reports pausedDL and
pausedUP. Both map to the same labels.
"""

from __future__ import annotations

DOWNLOADING = "Downloading"
METADATA = "Fetching metadata"
STALLED = "Stalled"
QUEUED = "Queued"
STOPPED = "Stopped"
COMPLETED = "Completed"
SEEDING = "Seeding"
CHECKING = "Checking"
WORKING = "Working"
ERROR = "Error"
UNKNOWN = "Unknown"

STATE_LABELS = {
    "downloading": DOWNLOADING,
    "forcedDL": DOWNLOADING,
    "metaDL": METADATA,
    "forcedMetaDL": METADATA,
    "stalledDL": STALLED,
    "queuedDL": QUEUED,
    "queuedUP": QUEUED,
    "stoppedDL": STOPPED,
    "pausedDL": STOPPED,
    "stoppedUP": COMPLETED,
    "pausedUP": COMPLETED,
    "uploading": SEEDING,
    "forcedUP": SEEDING,
    "stalledUP": SEEDING,
    "checkingDL": CHECKING,
    "checkingUP": CHECKING,
    "checkingResumeData": CHECKING,
    "allocating": WORKING,
    "moving": WORKING,
    "error": ERROR,
    "missingFiles": ERROR,
}

# States where the torrent is moving data or about to.
ACTIVE_STATES = frozenset(
    {"downloading", "forcedDL", "metaDL", "forcedMetaDL", "uploading", "forcedUP",
     "checkingDL", "checkingUP", "checkingResumeData", "allocating", "moving"}
)

STOPPED_STATES = frozenset({"stoppedDL", "pausedDL", "stoppedUP", "pausedUP"})

INFINITE_ETA = 8640000


def label(state: object) -> str:
    return STATE_LABELS.get(state, UNKNOWN) if isinstance(state, str) else UNKNOWN


def is_stopped(state: object) -> bool:
    return state in STOPPED_STATES
