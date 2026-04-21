from typing import Optional

from core.session import Session
from core.stimulus import Stimulus, StimulusSet
from tasks.base_task import BaseTask


class FamousFaceTask(BaseTask):
    """
    Task: Patient points to the famous face on a composite image.

    The image contains three faces (gauche / centre / droite).
    Correct answer is stimulus.correct_response (= target_position from trials.csv).
    """

    def __init__(self, session: Session, stimulus_set: StimulusSet):
        super().__init__(session, stimulus_set)

    def _check_correct(self, response: str, stimulus: Optional[Stimulus]) -> Optional[bool]:
        if stimulus is None or stimulus.correct_response is None:
            return None
        return response.strip() == stimulus.correct_response.strip()
