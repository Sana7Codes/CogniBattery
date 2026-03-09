import csv
import os
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from core.timing import Clock


class EventType(Enum):
    SESSION_START    = "SESSION_START"
    SESSION_END      = "SESSION_END"
    ERROR            = "ERROR"
    NOTE             = "NOTE"

    TRIAL_START      = "TRIAL_START"
    IMAGE_ON         = "IMAGE_ON"
    RESPONSE         = "RESPONSE"
    STIM_START       = "STIM_START"
    STIM_END         = "STIM_END"
    TRIAL_END        = "TRIAL_END"

    STIMULUS_SKIP    = "STIMULUS_SKIP"
    STIMULUS_EXCLUDE = "STIMULUS_EXCLUDE"
    STIMULUS_REPLACE = "STIMULUS_REPLACE"


CSV_COLUMNS = [
    "Time_s", "Time_iso", "Event", "Essai", "Stimulus",
    "Response", "Correct", "TR_s", "TouchX", "TouchY", "Notes",
]


@dataclass
class Event:
    time_s:    float
    time_iso:  str
    event:     EventType
    essai:     Optional[int]
    stimulus:  Optional[str]
    response:  Optional[str]
    correct:   Optional[bool]
    tr_s:      Optional[float]
    touch_x:   Optional[int]
    touch_y:   Optional[int]
    notes:     Optional[str]


class _CsvAppendWriter:
    """Internal helper: opens a CSV in append mode and fsyncs after every row."""

    def __init__(self, path: str, metadata: dict = None):
        self._path = path
        is_new = not os.path.exists(path) or os.path.getsize(path) == 0
        self._file = open(path, "a", newline="", encoding="utf-8")
        self._writer = csv.writer(self._file)
        if is_new:
            if metadata:
                for key, value in metadata.items():
                    self._file.write(f"# {key},{value}\n")
                self._file.flush()
                os.fsync(self._file.fileno())
            self._writer.writerow(CSV_COLUMNS)
            self._file.flush()
            os.fsync(self._file.fileno())

    def write(self, event: Event) -> None:
        self._writer.writerow([
            round(event.time_s, 6),
            event.time_iso,
            event.event.value,
            event.essai,
            event.stimulus,
            event.response,
            event.correct,
            round(event.tr_s, 6) if event.tr_s is not None else None,
            event.touch_x,
            event.touch_y,
            event.notes,
        ])
        self._file.flush()
        os.fsync(self._file.fileno())

    def close(self) -> None:
        self._file.close()


class PersistentEventLog:
    """
    Append-only event logger.
    Writes to CSV immediately on each record() to prevent data loss on crash.
    Keeps an in-memory cache for UI stats; disk is the source of truth.

    Optional *trigger* parameter: any object with a ``send_event(EventType)``
    method (e.g. CompositeTrigger).  Called synchronously after each write.
    """

    def __init__(self, clock: Clock, csv_path: str, trigger=None, metadata: dict = None):
        self._clock      = clock
        self._csv_writer = _CsvAppendWriter(csv_path, metadata=metadata)
        self._cache: list[Event] = []
        self._image_on_times: dict[int, float] = {}  # essai -> time_s
        self._trigger    = trigger  # optional CompositeTrigger

    def record(
        self,
        event_type: EventType,
        essai: Optional[int] = None,
        stimulus: Optional[str] = None,
        response: Optional[str] = None,
        correct: Optional[bool] = None,
        tr_s: Optional[float] = None,
        touch_x: Optional[int] = None,
        touch_y: Optional[int] = None,
        notes: Optional[str] = None,
    ) -> Event:
        """
        Captures time_s and time_iso from Clock automatically.
        Appends row to CSV immediately (autosave with fsync).
        """
        event = Event(
            time_s=self._clock.now_relative(),
            time_iso=self._clock.now_iso(),
            event=event_type,
            essai=essai,
            stimulus=stimulus,
            response=response,
            correct=correct,
            tr_s=tr_s,
            touch_x=touch_x,
            touch_y=touch_y,
            notes=notes,
        )
        self._csv_writer.write(event)
        self._cache.append(event)

        if self._trigger is not None:
            try:
                self._trigger.send_event(event_type)
            except Exception:
                pass  # trigger failure never aborts a session

        if event_type == EventType.IMAGE_ON and essai is not None:
            self._image_on_times[essai] = event.time_s

        return event

    def get_by_trial(self, essai: int) -> list[Event]:
        return [e for e in self._cache if e.essai == essai]

    def get_image_on_time(self, essai: int) -> Optional[float]:
        return self._image_on_times.get(essai)

    def close(self) -> None:
        self._csv_writer.close()
