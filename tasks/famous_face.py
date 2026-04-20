from typing import Optional

from core.session import Session
from core.stimulus import Stimulus, StimulusSet
from tasks.base_task import BaseTask


class FamousFaceTask(BaseTask):
    """
    Task: Patient identifies whether a face belongs to a famous person.

    Expected responses: 'yes' / 'no'  (or 'familiar' / 'unfamiliar').
    Correct answer is derived from stimulus.is_familiar.
    """

    _FAMILIAR_RESPONSES   = {"yes", "familiar", "oui", "connu"}
    _UNFAMILIAR_RESPONSES = {"no", "unfamiliar", "non", "inconnu"}

    def __init__(self, session: Session, stimulus_set: StimulusSet):
        super().__init__(session, stimulus_set)

    def _check_correct(self, response: str, stimulus: Optional[Stimulus]) -> Optional[bool]:
        if stimulus is None or stimulus.is_familiar is None:
            return None
        r = response.lower().strip()
        if stimulus.is_familiar:
            return r in self._FAMILIAR_RESPONSES
        else:
            return r in self._UNFAMILIAR_RESPONSES
