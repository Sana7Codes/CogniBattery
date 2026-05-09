"""
Abstract base class for all Battery tasks.

Concrete task classes (FamousFaceTask, SemanticMatchingTask, etc.) only need
to implement _check_correct().  Everything else — counterbalance checking,
response logging, session bookkeeping — lives here.
"""

from typing import Optional

from core.error_log import log_error, log_warning, log_info
from core.session import Session
from core.stimulus import Stimulus, StimulusSet


class BaseTask:
    """
    Base for all 8 clinical tasks.

    Responsibilities:
      - Own the StimulusSet for this session
      - Verify counterbalancing at session start
      - Provide check_correct() wrapping _check_correct()
    """

    def __init__(self, session: Session, stimulus_set: StimulusSet) -> None:
        self.session      = session
        self.stimulus_set = stimulus_set
        self._cb_notes    = self._check_counterbalance()

    # ── Public API ────────────────────────────────────────────────────────────

    def check_correct(
        self,
        response: str,
        stimulus: Optional[Stimulus],
    ) -> Optional[bool]:
        """Evaluate a response, catching any errors from the subclass."""
        try:
            return self._check_correct(response, stimulus)
        except Exception as exc:
            log_error(
                f"Error in _check_correct (task={self.session.task_code} "
                f"stim={getattr(stimulus, 'planche_id', None)}): {exc}",
                exc,
            )
            return None

    @property
    def counterbalance_notes(self) -> str:
        return self._cb_notes

    # ── Subclass interface ────────────────────────────────────────────────────

    def _check_correct(
        self,
        response: str,
        stimulus: Optional[Stimulus],
    ) -> Optional[bool]:
        raise NotImplementedError

    # ── Counterbalancing ──────────────────────────────────────────────────────

    def _check_counterbalance(self) -> str:
        """
        Verify left/right balance across the trial list loaded for this session.

        Rules:
          - For tasks with correct_response ∈ {left, right, center}: compute ratio.
          - If target_position is blank (FFP/FNP without PPTX data): log warning only.
          - Log the ratio to the session metadata Notes field.

        Returns a notes string describing the balance (stored in session metadata).
        """
        task_code = self.session.task_code
        stimuli   = self.stimulus_set.all_stimuli

        three_choice = {"FFP_V1", "FFP_V2", "FNP"}
        verbal       = {"DI_SEEG"}

        if task_code in verbal:
            return "CounterBalance=N/A (verbal task)"

        if task_code in three_choice:
            filled = [s for s in stimuli if getattr(s, "target_position", None)]
            if not filled:
                msg = f"CounterBalance=Unknown (target_position blank; N={len(stimuli)})"
                log_warning(f"[{task_code}] target_position is blank for all stimuli.")
                return msg
            counts: dict[str, int] = {"gauche": 0, "centre": 0, "droite": 0}
            for s in filled:
                pos = (s.target_position or "").lower()
                if pos in counts:
                    counts[pos] += 1
            total = sum(counts.values())
            ratios = {k: round(v / total * 100, 1) for k, v in counts.items()}
            msg = (
                f"CounterBalance: gauche={counts['gauche']} ({ratios['gauche']}%) "
                f"centre={counts['centre']} ({ratios['centre']}%) "
                f"droite={counts['droite']} ({ratios['droite']}%)"
            )
            log_info(f"[{task_code}] {msg}")
            return msg

        # Two-choice tasks: MUF_V1/V2 and ASM_MOTS/ASM_SEEG
        gauche_n = sum(1 for s in stimuli if getattr(s, "correct_response", None) == "gauche")
        droite_n = sum(1 for s in stimuli if getattr(s, "correct_response", None) == "droite")
        total    = gauche_n + droite_n
        if total == 0:
            return "CounterBalance=N/A (no correct_response values)"
        pct_gauche = round(gauche_n / total * 100, 1)
        pct_droite = round(droite_n / total * 100, 1)
        msg = (
            f"CounterBalance: gauche={gauche_n} ({pct_gauche}%) "
            f"droite={droite_n} ({pct_droite}%)"
        )
        log_info(f"[{task_code}] {msg}")
        return msg
