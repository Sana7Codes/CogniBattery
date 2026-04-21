"""
In-session event logging for the Battery application.

EventLog writes every event row to disk immediately after it occurs so that
data is preserved even if the application crashes mid-session.

The on-disk format is:
  Block 1 — metadata lines prefixed with "#"
  Block 2 — CSV event rows (header + data)

CSVExporter (data/csv_exporter.py) can reconstruct a clean file from the
in-memory event list after the session ends.
"""

import csv
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


# ─── Column order (shared with CSVExporter) ───────────────────────────────────

CSV_COLUMNS: list[str] = [
    "Time_s",
    "Time_iso",
    "Event",
    "Essai",
    "Stimulus",
    "Response",
    "Correct",
    "TR_s",
    "stim_epoch",
    "TouchX",
    "TouchY",
    "Notes",
]


# ─── Event types ──────────────────────────────────────────────────────────────

class EventType(Enum):
    SESSION_START    = "SESSION_START"
    TRIAL_START      = "TRIAL_START"
    IMAGE_ON         = "IMAGE_ON"
    RESPONSE         = "RESPONSE"
    STIM_START       = "STIM_START"
    STIM_END         = "STIM_END"
    TRIAL_END        = "TRIAL_END"
    STIMULUS_SKIP    = "STIMULUS_SKIP"
    STIMULUS_EXCLUDE = "STIMULUS_EXCLUDE"
    STIMULUS_REPLACE = "STIMULUS_REPLACE"
    SESSION_END      = "SESSION_END"
    NOTE             = "NOTE"
    SESSION_NOTES    = "SESSION_NOTES"


# ─── Event row ────────────────────────────────────────────────────────────────

@dataclass
class Event:
    time_s:      float
    time_iso:    str
    event:       EventType
    essai:       Optional[int]   = None
    stimulus:    Optional[str]   = None
    response:    Optional[str]   = None
    correct:     Optional[str]   = None   # "Yes" | "No" | None
    tr_s:        Optional[float] = None
    stim_epoch:  Optional[str]   = None   # "pré-stim" | "per-stim" | "post-stim"
    touch_x:     Optional[float] = None
    touch_y:     Optional[float] = None
    notes:       Optional[str]   = None


# ─── EventLog ─────────────────────────────────────────────────────────────────

class EventLog:
    """
    Writes events to a CSV file incrementally (crash-safe).

    File layout:
      # Key: Value          ← metadata block
      # ...
      Time_s,Time_iso,...   ← CSV header
      0.001234,2025-...     ← event rows (appended on every log() call)
    """

    def __init__(self, metadata: dict[str, str], csv_path: str | Path) -> None:
        self.metadata  = metadata
        self.csv_path  = Path(csv_path)
        self._events:  list[Event] = []
        self._file     = None
        self._writer   = None
        self._open_file()

    # ── Public API ────────────────────────────────────────────────────────────

    def log(self, event: Event) -> None:
        """Append one event row to memory and immediately flush to disk."""
        self._events.append(event)
        self._writer.writerow(self._row(event))
        self._file.flush()

    def flush_to_csv(self, path: str | Path) -> None:
        """Write a complete standalone copy of metadata + events to *path*."""
        dest = Path(path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("w", newline="", encoding="utf-8") as fh:
            for k, v in self.metadata.items():
                fh.write(f"# {k}: {v}\n")
            fh.write("#\n")
            w = csv.writer(fh)
            w.writerow(CSV_COLUMNS)
            for ev in self._events:
                w.writerow(self._row(ev))

    @property
    def events(self) -> list[Event]:
        return list(self._events)

    def close(self) -> None:
        if self._file and not self._file.closed:
            self._file.flush()
            self._file.close()

    def finalize_epochs(self) -> None:
        """
        Classify all RESPONSE events by stim epoch, then rewrite the on-disk CSV
        with the epoch column filled in.  Call this after close().
        """
        compute_stim_epochs(self._events)
        self.flush_to_csv(self.csv_path)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _open_file(self) -> None:
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.csv_path.open("w", newline="", encoding="utf-8")
        for k, v in self.metadata.items():
            self._file.write(f"# {k}: {v}\n")
        self._file.write("#\n")
        self._writer = csv.writer(self._file)
        self._writer.writerow(CSV_COLUMNS)
        self._file.flush()

    @staticmethod
    def _row(ev: Event) -> list:
        return [
            round(ev.time_s, 6),
            ev.time_iso,
            ev.event.value,
            ev.essai,
            ev.stimulus,
            ev.response,
            ev.correct,
            round(ev.tr_s, 6) if ev.tr_s is not None else None,
            ev.stim_epoch,
            ev.touch_x,
            ev.touch_y,
            ev.notes,
        ]


# ─── Epoch classification ─────────────────────────────────────────────────────

def compute_stim_epochs(events: list[Event]) -> None:
    """
    Classify each RESPONSE event in-place as 'pré-stim', 'per-stim', or 'post-stim'.

    Algorithm (most-recent window first):
      per-stim  — IMAGE_ON or RESPONSE falls inside a STIM_START→STIM_END window
      post-stim — IMAGE_ON occurred after the most-recent window that ended before it
      pré-stim  — default (no stim window precedes IMAGE_ON)
    """
    # Build (start_ts, end_ts) windows from STIM_START/STIM_END pairs
    stim_windows: list[tuple[float, float]] = []
    open_start: Optional[float] = None
    for ev in events:
        if ev.event == EventType.STIM_START:
            open_start = ev.time_s
        elif ev.event == EventType.STIM_END:
            if open_start is not None:
                stim_windows.append((open_start, ev.time_s))
                open_start = None
    if open_start is not None:
        last_ts = events[-1].time_s if events else 0.0
        stim_windows.append((open_start, last_ts))

    # IMAGE_ON timestamp per essai
    image_on_by_essai: dict[int, float] = {}
    for ev in events:
        if ev.event == EventType.IMAGE_ON and ev.essai is not None:
            image_on_by_essai[ev.essai] = ev.time_s

    for ev in events:
        if ev.event != EventType.RESPONSE:
            continue
        image_on_ts = image_on_by_essai.get(ev.essai) if ev.essai is not None else None
        if image_on_ts is None:
            ev.stim_epoch = "pré-stim"
            continue
        response_ts = ev.time_s
        epoch = "pré-stim"
        for stim_start, stim_end in reversed(stim_windows):
            if (stim_start <= image_on_ts <= stim_end) or \
               (stim_start <= response_ts <= stim_end):
                epoch = "per-stim"
                break
            if image_on_ts > stim_end:
                epoch = "post-stim"
                break
        ev.stim_epoch = epoch


# ─── MockEventLog ─────────────────────────────────────────────────────────────

class MockEventLog(EventLog):
    """
    Identical interface to EventLog; prints events to console instead of
    writing to disk. Used when MOCK_HARDWARE=True and no file path is needed.
    Still accepts a csv_path so callers can treat it identically.
    """

    def __init__(self, metadata: dict[str, str], csv_path: str | Path) -> None:
        self.metadata = metadata
        self.csv_path = Path(csv_path)
        self._events:  list[Event] = []
        self._file     = None
        self._writer   = None
        print(f"[MockEventLog] would write to {self.csv_path}")

    def _open_file(self) -> None:
        pass  # no-op

    def log(self, event: Event) -> None:
        self._events.append(event)
        parts = [
            f"t={event.time_s:.3f}s",
            event.event.value,
            f"essai={event.essai}",
            f"stim={event.stimulus}",
            f"resp={event.response}",
            f"ok={event.correct}",
            f"TR={event.tr_s}",
        ]
        if event.notes:
            parts.append(f"notes={event.notes!r}")
        print("[EVT] " + " | ".join(str(p) for p in parts))

    def flush_to_csv(self, path: str | Path) -> None:
        print(f"[MockEventLog] flush_to_csv → {path} ({len(self._events)} events, not written)")

    def finalize_epochs(self) -> None:
        compute_stim_epochs(self._events)
        n = sum(1 for ev in self._events if ev.event == EventType.RESPONSE and ev.stim_epoch)
        print(f"[MockEventLog] finalize_epochs — {n} RESPONSE events classified")

    def close(self) -> None:
        print(f"[MockEventLog] closed ({len(self._events)} events total)")
