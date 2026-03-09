import os
from typing import Callable, Optional

from kivy.uix.floatlayout import FloatLayout

from core.stimulus import Stimulus
from ui.widgets.fixation_widget import FixationWidget
from ui.widgets.semantic_matching_widget import SemanticMatchingWidget
from ui.widgets.face_widget import FaceWidget
from ui.widgets.timer_bar_widget import TimerBarWidget


class KivyPatientScreen(FloatLayout):
    """
    Patient-side view. Fills the right portion of the spanning window.
    All task sub-widgets are built at construction time; visibility is
    toggled via opacity/disabled rather than add/remove.
    """

    def __init__(self, images_base: str, **kwargs):
        super().__init__(**kwargs)

        self._images_base = images_base
        self._response_cb: Optional[Callable] = None

        # --- Build all sub-widgets ---
        self._fixation = FixationWidget(size_hint=(1, 1), pos_hint={"x": 0, "y": 0})

        self._sm_widget = SemanticMatchingWidget(size_hint=(1, 1), pos_hint={"x": 0, "y": 0})
        self._sm_widget.opacity = 0
        self._sm_widget.disabled = True
        self._sm_widget.on_response(self._forward_response)

        self._face_widget = FaceWidget(size_hint=(1, 1), pos_hint={"x": 0, "y": 0})
        self._face_widget.opacity = 0
        self._face_widget.disabled = True
        self._face_widget.on_response(self._forward_response)

        self._timer_bar = TimerBarWidget(
            size_hint=(1, 0.04),
            pos_hint={"x": 0, "y": 0},
        )
        self._timer_bar.opacity = 0
        self._timer_bar.disabled = True

        # Render order: fixation at the back, timer bar at the front.
        self.add_widget(self._fixation)
        self.add_widget(self._sm_widget)
        self.add_widget(self._face_widget)
        self.add_widget(self._timer_bar)

    # ------------------------------------------------------------------
    # Public API — preserves original stub interface
    # ------------------------------------------------------------------

    def show_stimulus(self, stimulus: Stimulus, images_base: Optional[str] = None) -> None:
        """Route stimulus to the correct sub-widget and hide fixation."""
        base = images_base or self._images_base

        if stimulus.task_type == "SemanticMatching":
            self._sm_widget.load(stimulus, base)
            self._set_visible(self._sm_widget)
        elif stimulus.task_type in ("FamousFace", "UnknownFace"):
            self._face_widget.load(stimulus, base)
            self._set_visible(self._face_widget)
        else:
            # Unknown task type — fall back to fixation.
            self.clear()

    def clear(self) -> None:
        """Hide task widgets and show the fixation cross."""
        for w in (self._sm_widget, self._face_widget):
            w.opacity = 0
            w.disabled = True
        self._fixation.opacity = 1
        self._fixation.disabled = False
        self.stop_timer()

    def on_response(self, callback: Callable) -> None:
        """
        Register callback for patient response.
        Signature: callback(response: str, touch_x: int, touch_y: int)
        """
        self._response_cb = callback

    def start_timer(self, duration_s: float) -> None:
        self._timer_bar.opacity = 1
        self._timer_bar.disabled = False
        self._timer_bar.start(duration_s)

    def stop_timer(self) -> None:
        self._timer_bar.opacity = 0
        self._timer_bar.disabled = True
        self._timer_bar.reset()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _set_visible(self, widget) -> None:
        """Hide fixation, hide all task widgets, then show the given one."""
        self._fixation.opacity = 0
        self._fixation.disabled = True
        for w in (self._sm_widget, self._face_widget):
            w.opacity = 0
            w.disabled = True
        widget.opacity = 1
        widget.disabled = False

    def _forward_response(self, response: str, tx: float, ty: float) -> None:
        if self._response_cb:
            self._response_cb(response, int(tx), int(ty))
