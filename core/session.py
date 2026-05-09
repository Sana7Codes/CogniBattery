"""
Session state for one patient testing session.

A Session is created once the clinician clicks "Start Session" and holds
all the information that persists across the trial loop:
  - Patient / task identification
  - Current stimulation parameters (editable mid-session)
  - The global session clock (t=0 at session start)
  - Counters used by the event log
"""

from dataclasses import dataclass, field
from datetime import datetime

from core.timing import Clock


# ─── Stimulation parameters ───────────────────────────────────────────────────

@dataclass
class StimParams:
    electrode:    str   = ""
    contact:      str   = ""
    intensity_ma: float = 0.0
    duration_s:   float = 0.0

    def __str__(self) -> str:
        return (
            f"Electrode={self.electrode} Contact={self.contact} "
            f"Intensity={self.intensity_ma}mA Duration={self.duration_s}s"
        )

    def notes_string(self, signal_key: str = "f12") -> str:
        return (
            f"Signal={signal_key} | Electrode={self.electrode} "
            f"Contact={self.contact} "
            f"Intensity={self.intensity_ma}mA "
            f"Duration={self.duration_s}s"
        )


# ─── Session ──────────────────────────────────────────────────────────────────

class Session:
    """
    Holds all state for a single patient testing session.

    clock.now_relative() returns seconds since the clinician clicked
    "Start Session".  Use this for all Time_s values in the event log.
    """

    def __init__(
        self,
        patient_id:       str,
        task_code:        str,
        task_display_name: str,
        electrode:        str,
        contact:          str,
        intensity_ma:     float,
        duration_s:       float,
        progression_mode: str,
        timer_delay_s:    float = 0.0,
        stim_key:         str   = "f12",
        stimuli_order:    str   = "random",
        screen_width:     int   = 1280,
        screen_height:    int   = 800,
    ) -> None:
        self.patient_id        = patient_id
        self.task_code         = task_code
        self.task_display_name = task_display_name
        self.progression_mode  = progression_mode   # "PatientTouch" | "ClinicianAction" | "Timer"
        self.timer_delay_s     = timer_delay_s
        self.stim_key          = stim_key
        self.stimuli_order     = stimuli_order
        self.screen_width      = screen_width
        self.screen_height     = screen_height

        # Session ID is fixed at construction time
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_date = datetime.now().strftime("%Y-%m-%d")
        self.session_start_time = datetime.now().strftime("%H:%M:%S")

        # Current stimulation parameters (can be updated mid-session)
        self._stim_params = StimParams(
            electrode=electrode,
            contact=contact,
            intensity_ma=intensity_ma,
            duration_s=duration_s,
        )

        self.clock = Clock()
        self.trial_index = 0
        self.finalized = False   # set True after first SESSION_END finalization

    # ── Stim params ───────────────────────────────────────────────────────────

    @property
    def current_stim_params(self) -> StimParams:
        return self._stim_params

    def update_stim_params(
        self,
        electrode:    str,
        contact:      str,
        intensity_ma: float,
        duration_s:   float,
    ) -> None:
        """
        Update stimulation parameters mid-session.
        The new values will appear in the Notes of the next STIM_START event.
        """
        self._stim_params = StimParams(
            electrode=electrode,
            contact=contact,
            intensity_ma=intensity_ma,
            duration_s=duration_s,
        )

    # ── Clock shortcut ────────────────────────────────────────────────────────

    def start(self) -> None:
        self.clock.start()
        self.session_start_time = datetime.now().strftime("%H:%M:%S")

    def now(self) -> float:
        return self.clock.now_relative()

    def now_iso(self) -> str:
        return self.clock.now_iso()

    # ── CSV filename / folder helpers ─────────────────────────────────────────

    def csv_filename(self) -> str:
        p = self._stim_params
        date = datetime.now().strftime("%Y-%m-%d")
        hhmm = datetime.now().strftime("%H-%M")
        mA = str(p.intensity_ma).rstrip("0").rstrip(".")
        s  = str(p.duration_s).rstrip("0").rstrip(".")
        return (
            f"Patient_{self.patient_id}_{date}_{hhmm}_{self.task_code}"
            f"_Contact{p.electrode}-{p.contact}_{mA}mA_{s}s.csv"
        )

    def csv_folder(self) -> str:
        date = datetime.now().strftime("%Y-%m-%d")
        return f"data/Patient_{self.patient_id}/{date}/{self.task_code}/"

    def summary_filename(self) -> str:
        date = datetime.now().strftime("%Y-%m-%d")
        hhmm = datetime.now().strftime("%H-%M")
        return (
            f"Patient_{self.patient_id}_{date}_{hhmm}_{self.task_code}_summary.csv"
        )
