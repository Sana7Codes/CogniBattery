"""
Stimulus and StimulusSet — unified wrappers around trials.csv rows.

Each task has its own trials.csv column schema; Stimulus normalises all of
them into a single object that the UI and task classes can use uniformly.

Column schemas per task:
  MUF_V1 / MUF_V2   → filename, correct_side
  ASM_MOTS / ASM_SEEG → filename, stimulus, correct
  DI_SEEG            → filename, correct_label, item_number
  FFP_V1 / FFP_V2 / FNP → filename, target_person, target_position
"""

import random
from pathlib import Path
from typing import Optional


# Tasks that use 2-choice left/right zones
_TWO_CHOICE   = {"MUF_V1", "MUF_V2", "ASM_MOTS", "ASM_SEEG"}
# Tasks that use 3-choice left/center/right zones
_THREE_CHOICE = {"FFP_V1", "FFP_V2", "FNP"}
# Tasks that are verbal (clinician records correctness via keyboard)
_VERBAL       = {"DI_SEEG"}


class Stimulus:
    """
    Wraps one trials.csv row for a given task.

    Attributes that task classes rely on:
      .is_familiar      — bool | None  (FFP: set by familiarity pre-check)
      .correct_response — str | None   (MUF/ASM: 'left'|'right'; None if unknown)
      .image_path       — str          (absolute path to JPEG)
      .correct_answer   — str | None   (human-readable; used for clinician display)
      .stimulus_label   — str | None   (center word/concept for ASM)
      .zone_type        — str          ('2-choice'|'3-choice'|'verbal')
      .planche_id       — str          (unique ID == filename stem)
    """

    def __init__(self, task_code: str, row: dict, folder: Path) -> None:
        self.task_code  = task_code
        self._row       = row
        self.filename   = row["filename"]
        self.image_path = str(folder / self.filename)
        self.planche_id = Path(self.filename).stem

        # Zone type
        if task_code in _TWO_CHOICE:
            self.zone_type = "2-choice"
        elif task_code in _THREE_CHOICE:
            self.zone_type = "3-choice"
        else:
            self.zone_type = "verbal"

        # ── Parse task-specific fields ────────────────────────────────────────

        if task_code in ("MUF_V1", "MUF_V2"):
            side = row.get("correct_side", "").lower().strip()
            self.correct_response: Optional[str] = side if side in ("gauche", "droite") else None
            self.correct_answer:   Optional[str] = self.correct_response
            self.stimulus_label:   Optional[str] = self.planche_id
            self.is_familiar:      Optional[bool] = None

        elif task_code in ("ASM_MOTS", "ASM_SEEG"):
            self.stimulus_label   = row.get("stimulus", "")
            self.correct_answer   = row.get("correct", "")
            side = row.get("correct_side", "").lower().strip()
            self.correct_response = side if side in ("gauche", "droite") else None
            self.is_familiar      = None

        elif task_code == "DI_SEEG":
            # Verbal naming task — no touch zones
            self.correct_answer   = row.get("correct_label", "")
            self.correct_response = None   # clinician marks K/X manually
            self.stimulus_label   = self.planche_id
            self.is_familiar      = None
            self.item_number      = row.get("item_number", "")

        elif task_code in ("FFP_V1", "FFP_V2"):
            # Famous face pointing — familiarity set by pre-check
            self.target_person    = row.get("target_person", "")
            self.target_position  = row.get("target_position", "") or None
            self.correct_answer   = self.target_position   # None if PPTX missing
            self.correct_response = self.target_position
            self.stimulus_label   = self.target_person
            self.is_familiar      = True   # default; overridden by pre-check

        elif task_code == "FNP":
            # Famous names pointing — no auto-score without PPTX
            self.target_person    = row.get("target_person", "")
            self.target_position  = row.get("target_position", "") or None
            self.correct_answer   = self.target_position
            self.correct_response = self.target_position
            self.stimulus_label   = self.target_person
            self.is_familiar      = None

        else:
            self.correct_response = None
            self.correct_answer   = None
            self.stimulus_label   = self.planche_id
            self.is_familiar      = None

    def __repr__(self) -> str:
        return f"<Stimulus {self.planche_id} zone={self.zone_type}>"


# ─── StimulusSet ──────────────────────────────────────────────────────────────

class StimulusSet:
    """
    Ordered, mutable collection of Stimulus objects for one session.

    Supports:
      - Random or fixed ordering
      - Skip (stimulus removed, not counted as excluded)
      - Exclude (stimulus permanently removed and logged)
      - Replace (swap current stimulus for another from remaining pool)
    """

    def __init__(
        self,
        stimuli: list[Stimulus],
        order:   str = "random",
    ) -> None:
        self._all      = list(stimuli)
        self._queue:   list[Stimulus] = list(stimuli)
        self._done:    list[Stimulus] = []
        self._skipped: list[Stimulus] = []
        self._excluded:list[Stimulus] = []

        if order == "random":
            random.shuffle(self._queue)

    # ── Iteration / access ────────────────────────────────────────────────────

    def __len__(self) -> int:
        return len(self._queue)

    def has_next(self) -> bool:
        return bool(self._queue)

    def current(self) -> Optional[Stimulus]:
        return self._queue[0] if self._queue else None

    def advance(self) -> None:
        """Mark current stimulus as done and move to the next."""
        if self._queue:
            self._done.append(self._queue.pop(0))

    @property
    def remaining(self) -> list[Stimulus]:
        """Stimuli still to be presented (excludes current)."""
        return list(self._queue[1:]) if len(self._queue) > 1 else []

    @property
    def all_stimuli(self) -> list[Stimulus]:
        return list(self._all)

    # ── Clinician actions ─────────────────────────────────────────────────────

    def skip(self, stimulus: Stimulus) -> None:
        """Remove stimulus from queue without counting it as excluded."""
        if stimulus in self._queue:
            self._queue.remove(stimulus)
            self._skipped.append(stimulus)

    def exclude(self, stimulus: Stimulus) -> None:
        """Permanently remove stimulus from queue."""
        if stimulus in self._queue:
            self._queue.remove(stimulus)
            self._excluded.append(stimulus)

    def replace(self, old: Stimulus, new_planche_id: str) -> bool:
        """
        Swap *old* (must be current) with the stimulus identified by
        *new_planche_id* from the remaining queue.
        Returns True on success, False if not found.
        """
        new_stim = next(
            (s for s in self._queue[1:] if s.planche_id == new_planche_id),
            None,
        )
        if new_stim is None:
            return False
        if old in self._queue:
            idx = self._queue.index(old)
            self._queue.remove(new_stim)
            self._queue[idx] = new_stim
            return True
        return False

    # ── Statistics ────────────────────────────────────────────────────────────

    @property
    def n_total(self) -> int:
        return len(self._all)

    @property
    def n_done(self) -> int:
        return len(self._done)

    @property
    def n_skipped(self) -> int:
        return len(self._skipped)

    @property
    def n_excluded(self) -> int:
        return len(self._excluded)

    @property
    def excluded_ids(self) -> list[str]:
        return [s.planche_id for s in self._excluded]

    @property
    def included_ids(self) -> list[str]:
        return [
            s.planche_id for s in self._all
            if s not in self._excluded
        ]

    # ── Counterbalancing ──────────────────────────────────────────────────────

    def counterbalance_ratio(self) -> dict:
        """
        Return counts of left/right/center across remaining + done stimuli
        (excluding skipped and excluded).
        """
        counts = {"gauche": 0, "droite": 0, "centre": 0, "none": 0}
        for s in self._queue + self._done:
            cr = getattr(s, "correct_response", None)
            if cr in counts:
                counts[cr] += 1
            else:
                counts["none"] += 1
        return counts
