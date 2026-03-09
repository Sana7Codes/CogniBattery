"""
Session metadata writer / reader.

Writes a JSON sidecar alongside the CSV for each session.
The metadata file carries enough information to:
  - Identify the session unambiguously (session_id, patient_id, date/time)
  - Reconstruct the StimulusSet for session recovery
  - Validate experimental parameters post-hoc

File naming: <csv_stem>_metadata.json  (e.g. 2026-03-05_1400_SemanticMatching_metadata.json)
"""
import json
import os
from typing import Optional

METADATA_SUFFIX = "_metadata.json"


def metadata_path_from_csv(csv_path: str) -> str:
    """Return the metadata JSON path corresponding to a CSV path."""
    stem = os.path.splitext(csv_path)[0]
    return stem + METADATA_SUFFIX


def write_metadata(
    csv_path: str,
    session_id: str,
    config,
    stim_set,
    counterbalancing_report=None,
) -> str:
    """
    Write <csv_stem>_metadata.json alongside the CSV.

    Parameters
    ----------
    csv_path : str
        Path to the session event CSV (already created by FileManager).
    session_id : str
        UUID string from Session.session_id.
    config : SessionConfig
        Full session configuration dataclass.
    stim_set : StimulusSet
        Ordered set of stimuli (used for recovery).
    counterbalancing_report : dict | None
        Optional CounterbalancingReport serialised as dict.

    Returns
    -------
    str
        Path to the written metadata file.
    """
    stimuli_list = [s.stimulus_id for s in stim_set]

    meta = {
        "schema_version": "1.0",
        "session_id":            session_id,
        "patient_id":            config.patient_id,
        "session_date":          config.session_date.isoformat(),
        "session_start_time":    config.session_start_time.isoformat(),
        "test_type":             config.test_type,
        "experiment_version":    config.software_version,
        "electrode":             config.electrode,
        "contact":               config.contact,
        "stim_intensity_mA":     config.stim_intensity_mA,
        "stim_duration_s":       config.stim_duration_s,
        "progression_mode":      config.progression_mode.value,
        "timer_duration_s":      config.timer_duration_s,
        "stim_signal_key":       config.stim_signal_key,
        "stimuli_list":          stimuli_list,
        "total_stimuli":         len(stimuli_list),
        "counterbalancing_report": counterbalancing_report,
        "csv_filename":          os.path.basename(csv_path),
    }

    path = metadata_path_from_csv(csv_path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    return path


def read_metadata(metadata_path: str) -> Optional[dict]:
    """
    Load and return a metadata JSON as a dict.
    Returns None if the file is missing or cannot be parsed.
    """
    try:
        with open(metadata_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None
