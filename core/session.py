import traceback
import uuid
from dataclasses import dataclass, field
from datetime import date, time
from enum import Enum
from typing import Optional

from core.timing import Clock
from core.event_log import PersistentEventLog, EventType


class ProgressionMode(Enum):
    PATIENT_TOUCH    = "PatientTouch"
    CLINICIAN_ACTION = "ClinicianAction"
    TIMER            = "Timer"


@dataclass
class SessionConfig:
    patient_id:         str
    session_date:       date
    session_start_time: time
    test_type:          str
    electrode:          str
    contact:            str
    stim_intensity_mA:  float
    stim_duration_s:    float
    progression_mode:   ProgressionMode
    timer_duration_s:   Optional[float]
    stim_signal_key:    str
    screen_width_px:    int
    screen_height_px:   int
    software_version:   str
    stimuli_included:   list = field(default_factory=list)
    stimuli_excluded:   list = field(default_factory=list)
    randomize_order:    bool = False


class Session:
    def __init__(self, config: SessionConfig, event_log: PersistentEventLog, clock: Clock):
        self.config = config
        self.session_id = str(uuid.uuid4())
        self.clock = clock
        self.event_log = event_log
        self.current_trial: int = 0
        self.is_stim_active: bool = False
        self._stim_counter: int = 0
        self._pending_stim: Optional[dict] = None

    def start(self) -> None:
        """Initializes clock, sets Time_s=0, logs SESSION_START."""
        self.clock.start()
        self.event_log.record(
            EventType.SESSION_START,
            notes=(
                f"SessionID={self.session_id};"
                f"PatientID={self.config.patient_id};"
                f"TestType={self.config.test_type};"
                f"Electrode={self.config.electrode};"
                f"Contact={self.config.contact};"
                f"Intensity_mA={self.config.stim_intensity_mA};"
                f"Duration_s={self.config.stim_duration_s};"
                f"ProgressionMode={self.config.progression_mode.value};"
                f"SoftwareVersion={self.config.software_version}"
            ),
        )

    def record_stim_start(self, notes: str = "") -> None:
        """
        Records STIM_START event (does not trigger stimulation).
        Schedules STIM_END at Time_s + config.stim_duration_s.
        Captures stim params snapshot and StimID for traceability.
        """
        self._stim_counter += 1
        stim_id = self._stim_counter
        self.is_stim_active = True

        end_time_s = self.clock.now_relative() + self.config.stim_duration_s
        self._pending_stim = {
            "stim_id":    stim_id,
            "end_time_s": end_time_s,
            "electrode":  self.config.electrode,
            "contact":    self.config.contact,
            "intensity":  self.config.stim_intensity_mA,
            "duration":   self.config.stim_duration_s,
            "signal_key": self.config.stim_signal_key,
        }

        stim_notes = (
            f"StimID={stim_id};"
            f"Electrode={self.config.electrode};"
            f"Contact={self.config.contact};"
            f"Intensity_mA={self.config.stim_intensity_mA};"
            f"Duration_s={self.config.stim_duration_s};"
            f"Signal={self.config.stim_signal_key}"
        )
        if notes:
            stim_notes += f";{notes}"

        self.event_log.record(EventType.STIM_START, notes=stim_notes)

    def check_and_fire_stim_end(self) -> bool:
        """
        Polled from App event loop.
        If now >= pending end time, records STIM_END with same StimID.
        Returns True if STIM_END was fired.
        """
        if self._pending_stim is None:
            return False
        if self.clock.now_relative() >= self._pending_stim["end_time_s"]:
            p = self._pending_stim
            self.event_log.record(
                EventType.STIM_END,
                notes=f"StimID={p['stim_id']};AutoComputed=True",
            )
            self.is_stim_active = False
            self._pending_stim = None
            return True
        return False

    def note(self, text: str) -> None:
        """Records a NOTE event."""
        self.event_log.record(EventType.NOTE, notes=text)

    def error(self, exc: Exception) -> None:
        """Records an ERROR event with message and truncated traceback."""
        msg = f"{type(exc).__name__}: {exc}"
        tb = traceback.format_exc()
        self.event_log.record(EventType.ERROR, notes=f"{msg}|Traceback={tb[:500]}")

    def end(self) -> None:
        """Logs SESSION_END and closes the event log."""
        self.event_log.record(
            EventType.SESSION_END,
            notes=f"SessionID={self.session_id};TotalTrials={self.current_trial}",
        )
        self.event_log.close()
