"""
Session file management — names, folders, and the post-session summary CSV.
"""

from __future__ import annotations

import csv
import math
import re
from pathlib import Path
from typing import Optional

from core.event_log import Event, EventLog, EventType
from core.session import Session


def resolve_csv_path(session: Session) -> Path:
    """
    Return the full path for the session CSV, appending _2, _3 etc.
    if the filename already exists to prevent overwriting.
    """
    folder = Path(session.csv_folder())
    folder.mkdir(parents=True, exist_ok=True)
    base = session.csv_filename()
    stem = Path(base).stem
    suffix = Path(base).suffix

    candidate = folder / base
    counter = 2
    while candidate.exists():
        candidate = folder / f"{stem}_{counter}{suffix}"
        counter += 1
    return candidate


def build_metadata(
    session: Session,
    stimulus_set,
    counterbalance_notes: str = "",
) -> dict[str, str]:
    """Build the metadata dictionary written as # comments at the top of the CSV."""
    p = session.current_stim_params
    included = " | ".join(stimulus_set.included_ids[:30])
    if len(stimulus_set.included_ids) > 30:
        included += f" … (+{len(stimulus_set.included_ids) - 30} more)"
    excluded = " | ".join(stimulus_set.excluded_ids) or "none"

    return {
        "SessionID":               session.session_id,
        "SoftwareVersion":         _get_version(),
        "PatientID":               session.patient_id,
        "SessionDate":             session.session_date,
        "SessionStartTime":        session.session_start_time,
        "TestType":                session.task_code,
        "Electrode":               p.electrode,
        "Contact":                 p.contact,
        "StimulationIntensity_mA": str(p.intensity_ma),
        "StimulationDuration_s":   str(p.duration_s),
        "ProgressionMode":         session.progression_mode,
        "StimSignalKey":           session.stim_key,
        "StimuliOrder":            session.stimuli_order,
        "ScreenWidth_px":          str(session.screen_width),
        "ScreenHeight_px":         str(session.screen_height),
        "StimuliIncluded":         included,
        "StimuliExcluded":         excluded,
        "CounterBalance":          counterbalance_notes,
    }


def write_summary(
    session:     Session,
    event_log:   EventLog,
    n_trials:    int,
    n_correct:   int,
    n_skipped:   int,
) -> Path:
    """
    Write the post-session summary CSV and return its path.

    Columns: task, n_trials, n_correct, mean_TR_s, sd_TR_s, n_timeout, n_skipped
    """
    folder = Path(session.csv_folder())
    folder.mkdir(parents=True, exist_ok=True)
    summary_path = folder / session.summary_filename()

    response_events = [
        ev for ev in event_log.events if ev.event == EventType.RESPONSE
    ]
    trs = [ev.tr_s for ev in response_events if ev.tr_s is not None]
    mean_tr = sum(trs) / len(trs) if trs else None
    sd_tr   = (
        math.sqrt(sum((t - mean_tr) ** 2 for t in trs) / len(trs))
        if len(trs) > 1 else None
    )

    with summary_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow([
            "task", "n_trials", "n_correct",
            "mean_TR_s", "sd_TR_s", "n_timeout", "n_skipped"
        ])
        writer.writerow([
            session.task_code,
            n_trials,
            n_correct,
            round(mean_tr, 4) if mean_tr is not None else "",
            round(sd_tr,   4) if sd_tr   is not None else "",
            0,          # timeout tracking not yet implemented
            n_skipped,
        ])

    return summary_path


def _get_version() -> str:
    try:
        import config
        return config.SOFTWARE_VERSION
    except Exception:
        return "unknown"
