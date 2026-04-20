from typing import Optional

from core.session import Session
from core.stimulus import Stimulus, StimulusSet
from tasks.base_task import BaseTask


class UnknownFaceTask(BaseTask):
    """
    Task: Patient judges whether a face is familiar.
    All stimuli are unknown/unfamiliar faces; the correct response is always 'no'.

    Expected responses: 'yes' / 'no'.
    """

    _UNFAMILIAR_RESPONSES = {"no", "unfamiliar", "non", "inconnu"}

    def __init__(self, session: Session, stimulus_set: StimulusSet):
        super().__init__(session, stimulus_set)

    def _check_correct(self, response: str, stimulus: Optional[Stimulus]) -> Optional[bool]:
        if stimulus is None:
            return None
        return response.lower().strip() in self._UNFAMILIAR_RESPONSES
