"""
csv_loader — loads per-task trial lists from stimuli/.

Folder names in stimuli/ match stimuli_raw/ exactly (no renaming).
Task codes map to those exact folder names.
"""
import csv
from pathlib import Path

# Project root: Battery/  (this file lives at Battery/tasks/csv_loader.py)
_ROOT = Path(__file__).resolve().parent.parent
STIMULI_DIR = _ROOT / "stimuli"

# Exact folder names as they exist in stimuli/ (copied verbatim from stimuli_raw/)
TASK_FOLDERS: dict[str, str] = {
    "FFP_V1":   "Famous-face-pointing-V1.jpg",
    "FFP_V2":   "Famous-face-pointing-V2",
    "MUF_V1":   "matching-unknown-face-V1",
    "MUF_V2":   "matching-unknown-face-V2",
    "ASM_MOTS": "Appariement-seumantique-mots",
    "ASM_SEEG": "Appariement-seumantique-SEEG_sansDeunoV2_2",
    "DI_SEEG":  "Deunomination-dCOimages-SEEG-2024",
    "FNP":      "famous-names-pointing",
}


def task_folder(task_code: str) -> Path:
    """Return the absolute path to the task's stimuli folder."""
    try:
        return STIMULI_DIR / TASK_FOLDERS[task_code]
    except KeyError:
        raise ValueError(
            f"Unknown task code: {task_code!r}. Valid codes: {sorted(TASK_FOLDERS)}"
        )


def load_trials(task_code: str) -> list[dict]:
    """
    Return the trial list for *task_code* as a list of dicts.

    Each dict has the columns defined in that task's trials.csv:
      MUF_V1 / MUF_V2  → filename, correct_side
      ASM_MOTS / ASM_SEEG → filename, stimulus, correct
      DI_SEEG           → filename, correct_label, item_number
      FFP_V1 / FFP_V2   → filename, target_person, target_position
      FNP               → filename, target_person, target_position
    """
    csv_path = task_folder(task_code) / "trials.csv"
    if not csv_path.exists():
        raise FileNotFoundError(
            f"trials.csv not found for task {task_code!r}: {csv_path}"
        )
    with csv_path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def image_path(task_code: str, filename: str) -> Path:
    """Return the absolute path to an image file inside the task folder."""
    return task_folder(task_code) / filename
