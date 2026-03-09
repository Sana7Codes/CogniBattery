from abc import ABC, abstractmethod
from typing import Optional

from core.event_log import Event, EventType
from core.session import Session
from core.stimulus import Stimulus, StimulusSet


class BaseTask(ABC):
    """
    Abstract base for all cognitive tasks.
    Manages the trial lifecycle and emits structured events via the session log.
    All writes go through PersistentEventLog.record() and are autosaved.
    """

    def __init__(self, session: Session, stimulus_set: StimulusSet):
        self.session = session
        self.stimulus_set = stimulus_set

    def start_trial(self) -> Stimulus:
        """
        Advances trial counter, emits TRIAL_START then IMAGE_ON.
        Returns the current stimulus.
        """
        stimulus = self.stimulus_set.current
        if stimulus is None:
            raise RuntimeError("No more stimuli in the set.")

        self.session.current_trial += 1
        essai = self.session.current_trial

        self.session.event_log.record(
            EventType.TRIAL_START,
            essai=essai,
            stimulus=stimulus.stimulus_id,
        )
        self.session.event_log.record(
            EventType.IMAGE_ON,
            essai=essai,
            stimulus=stimulus.stimulus_id,
        )
        return stimulus

    def record_response(
        self,
        response: str,
        touch_x: Optional[int] = None,
        touch_y: Optional[int] = None,
    ) -> Event:
        """
        Records a RESPONSE event.
        TR_s is computed as time since the last IMAGE_ON for this trial.
        """
        essai = self.session.current_trial
        image_on_time = self.session.event_log.get_image_on_time(essai)
        now = self.session.clock.now_relative()
        tr_s = (now - image_on_time) if image_on_time is not None else None

        stimulus = self.stimulus_set.current
        correct = self._check_correct(response, stimulus)

        return self.session.event_log.record(
            EventType.RESPONSE,
            essai=essai,
            stimulus=stimulus.stimulus_id if stimulus else None,
            response=response,
            correct=correct,
            tr_s=tr_s,
            touch_x=touch_x,
            touch_y=touch_y,
        )

    def end_trial(self) -> None:
        """Emits TRIAL_END and advances the stimulus set."""
        self.session.event_log.record(
            EventType.TRIAL_END,
            essai=self.session.current_trial,
        )
        self.stimulus_set.advance()

    def skip_trial(self, reason: str = "") -> None:
        """Emits STIMULUS_SKIP and advances without recording a response."""
        stimulus = self.stimulus_set.current
        self.session.event_log.record(
            EventType.STIMULUS_SKIP,
            essai=self.session.current_trial,
            stimulus=stimulus.stimulus_id if stimulus else None,
            notes=f"Reason={reason}" if reason else None,
        )
        self.stimulus_set.advance()

    def replace_stimulus(self, new_stimulus, reason: str = "") -> None:
        """Log STIMULUS_REPLACE and swap in a replacement for the current stimulus."""
        old = self.stimulus_set.current
        notes = f"ReplacedWith={new_stimulus.stimulus_id}"
        if reason:
            notes += f";Reason={reason}"
        self.session.event_log.record(
            EventType.STIMULUS_REPLACE,
            essai=self.session.current_trial,
            stimulus=old.stimulus_id if old else None,
            notes=notes,
        )
        self.stimulus_set.replace_current(new_stimulus)

    def exclude_stimulus(self, stimulus_id: str, reason: str = "") -> None:
        """Records an exclusion event for a given stimulus."""
        self.session.event_log.record(
            EventType.STIMULUS_EXCLUDE,
            stimulus=stimulus_id,
            notes=f"Reason={reason}" if reason else None,
        )

    @abstractmethod
    def _check_correct(self, response: str, stimulus: Optional[Stimulus]) -> Optional[bool]:
        """Return True/False/None depending on whether the response is correct."""
        ...
