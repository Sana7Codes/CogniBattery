from typing import Optional

from core.session import Session
from core.stimulus import Stimulus, StimulusSet
from tasks.base_task import BaseTask


class SemanticMatchingTask(BaseTask):
    """
    Task: Patient matches a central image to one of two peripheral images
    by semantic category.

    Expected response: the stimulus_id or label of the chosen image
    (must match stimulus.correct_response).
    """

    def __init__(self, session: Session, stimulus_set: StimulusSet):
        super().__init__(session, stimulus_set)

    def _check_correct(self, response: str, stimulus: Optional[Stimulus]) -> Optional[bool]:
        if stimulus is None or stimulus.correct_response is None:
            return None
        return response.strip() == stimulus.correct_response.strip()
