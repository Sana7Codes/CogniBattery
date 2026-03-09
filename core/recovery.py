"""
Session recovery utilities.

Detects sessions that ended without SESSION_END (app crash, power failure, …)
and provides helpers to resume from the last completed trial.

Typical flow
------------
1.  On app startup call ``find_incomplete_sessions(output_base_dir)``.
2.  If any are returned, show the clinician a recovery dialog.
3.  If clinician accepts, call ``build_recovery_context(csv_path, metadata_path,
    stimuli_base_dir)`` to obtain (config, stim_set, first_trial_to_run).
4.  Pass these to App + KivyApp instead of creating a new session.
"""
import csv
import os
from datetime import date, time
from typing import Optional

from data.session_metadata import read_metadata


# ─────────────────────────────────────────────────────────────
# Detection
# ─────────────────────────────────────────────────────────────

def find_incomplete_sessions(output_base_dir: str) -> list[dict]:
    """
    Walk *output_base_dir* and return metadata for every session that has a
    SESSION_START but no SESSION_END, sorted newest-first.

    Each entry in the returned list is a dict with keys:
        csv_path, metadata_path, patient_id, test_type, session_date,
        completed_trials, total_trials, mtime
    """
    results = []
    if not os.path.isdir(output_base_dir):
        return results

    for root, _dirs, files in os.walk(output_base_dir):
        for fname in sorted(files):
            if not fname.endswith("_events.csv"):
                continue
            csv_path  = os.path.join(root, fname)
            meta_path = csv_path.replace("_events.csv", "_metadata.json")
            if not os.path.exists(meta_path):
                continue

            has_start, has_end = _scan_csv(csv_path)
            if not (has_start and not has_end):
                continue

            meta = read_metadata(meta_path) or {}
            completed = get_last_completed_trial(csv_path)

            results.append({
                "csv_path":        csv_path,
                "metadata_path":   meta_path,
                "patient_id":      meta.get("patient_id", "?"),
                "test_type":       meta.get("test_type", "?"),
                "session_date":    meta.get("session_date", "?"),
                "completed_trials": completed,
                "total_trials":    meta.get("total_stimuli", "?"),
                "mtime":           os.path.getmtime(csv_path),
            })

    return sorted(results, key=lambda x: x["mtime"], reverse=True)


# ─────────────────────────────────────────────────────────────
# Recovery context builder
# ─────────────────────────────────────────────────────────────

def build_recovery_context(
    csv_path: str,
    metadata_path: str,
    stimuli_base_dir: str,
) -> Optional[tuple]:
    """
    Reconstruct a ``(SessionConfig, StimulusSet, resume_trial)`` tuple from a
    partial session so the app can continue where it left off.

    Returns ``None`` if the metadata is missing or cannot be parsed.

    Parameters
    ----------
    csv_path : str
        Path to the partial events CSV.
    metadata_path : str
        Path to the _metadata.json sidecar.
    stimuli_base_dir : str
        Root stimuli directory (e.g. ``project_root/stimuli``).
    """
    meta = read_metadata(metadata_path)
    if meta is None:
        return None

    try:
        config = _config_from_meta(meta)
    except Exception:
        return None

    # Re-load stimuli in the same order recorded in metadata
    stimuli_list: list[str] = meta.get("stimuli_list", [])
    test_type:    str        = meta.get("test_type", "")

    from core.stimulus import StimulusLibrary
    lib = StimulusLibrary()
    subdir = _test_type_to_subdir(test_type)
    stim_dir = os.path.join(stimuli_base_dir, subdir) if subdir else ""
    if stim_dir and os.path.isdir(stim_dir):
        lib.load_from_directory(stim_dir, test_type)

    # Build set in the exact order from metadata
    all_stim = {s.stimulus_id: s for s in lib.build_set()}
    ordered  = [all_stim[sid] for sid in stimuli_list if sid in all_stim]

    completed = get_last_completed_trial(csv_path)

    # Advance the set past completed trials
    from core.stimulus import StimulusSet
    remaining = StimulusSet(ordered[completed:])

    return config, remaining, completed


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def get_last_completed_trial(csv_path: str) -> int:
    """Count TRIAL_END events in *csv_path* → number of fully completed trials."""
    count = 0
    try:
        with open(csv_path, "r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                if row.get("Event", "") == "TRIAL_END":
                    count += 1
    except Exception:
        pass
    return count


def _scan_csv(csv_path: str) -> tuple[bool, bool]:
    """Return (has_SESSION_START, has_SESSION_END)."""
    has_start = has_end = False
    try:
        with open(csv_path, "r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                evt = row.get("Event", "")
                if evt == "SESSION_START":
                    has_start = True
                if evt == "SESSION_END":
                    has_end = True
    except Exception:
        pass
    return has_start, has_end


def _config_from_meta(meta: dict):
    """Reconstruct a SessionConfig from the metadata dict."""
    from core.session import SessionConfig, ProgressionMode

    return SessionConfig(
        patient_id         = meta["patient_id"],
        session_date       = date.fromisoformat(meta["session_date"]),
        session_start_time = time.fromisoformat(meta["session_start_time"]),
        test_type          = meta["test_type"],
        electrode          = meta.get("electrode", ""),
        contact            = meta.get("contact", ""),
        stim_intensity_mA  = float(meta.get("stim_intensity_mA", 1.0)),
        stim_duration_s    = float(meta.get("stim_duration_s", 1.0)),
        progression_mode   = ProgressionMode(meta.get("progression_mode", "ClinicianAction")),
        timer_duration_s   = meta.get("timer_duration_s"),
        stim_signal_key    = meta.get("stim_signal_key", "f12"),
        screen_width_px    = 1920,
        screen_height_px   = 1080,
        software_version   = meta.get("experiment_version", "1.0.0"),
        stimuli_included   = meta.get("stimuli_list", []),
        stimuli_excluded   = [],
    )


def _test_type_to_subdir(test_type: str) -> str:
    mapping = {
        "SemanticMatching": "semantic_matching",
        "FamousFace":       "famous_face",
        "UnknownFace":      "unknown_face",
    }
    return mapping.get(test_type, "")
