from kivy.uix.boxlayout import BoxLayout
from kivy.uix.progressbar import ProgressBar
from kivy.uix.label import Label
from kivy.clock import Clock

from ui.theme import TEXT_COLOR, FONT_SIZE_SM


class TimerBarWidget(BoxLayout):
    """
    Horizontal progress bar that drains over `duration_s` seconds.
    Shown only in TIMER progression mode.
    """

    def __init__(self, **kwargs):
        kwargs.setdefault("orientation", "horizontal")
        kwargs.setdefault("size_hint_y", 0.04)
        super().__init__(**kwargs)

        self._duration_s: float = 0.0
        self._elapsed_s: float = 0.0
        self._clock_event = None

        self._bar = ProgressBar(max=100, value=100, size_hint_x=0.80)
        self._label = Label(
            text="",
            size_hint_x=0.20,
            font_size=FONT_SIZE_SM,
            color=TEXT_COLOR,
        )
        self.add_widget(self._bar)
        self.add_widget(self._label)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self, duration_s: float) -> None:
        """Begin countdown from `duration_s` seconds."""
        self.reset()
        self._duration_s = duration_s
        self._elapsed_s = 0.0
        self._bar.value = 100
        self._update_label()
        self._clock_event = Clock.schedule_interval(self._tick, 0.05)

    def reset(self) -> None:
        """Stop the timer and reset the bar to full."""
        if self._clock_event is not None:
            self._clock_event.cancel()
            self._clock_event = None
        self._bar.value = 100
        self._label.text = ""

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _tick(self, dt: float) -> None:
        self._elapsed_s += dt
        remaining = max(0.0, self._duration_s - self._elapsed_s)
        fraction = remaining / self._duration_s if self._duration_s > 0 else 0.0
        self._bar.value = fraction * 100
        self._update_label()
        if remaining <= 0:
            if self._clock_event is not None:
                self._clock_event.cancel()
                self._clock_event = None

    def _update_label(self) -> None:
        remaining = max(0.0, self._duration_s - self._elapsed_s)
        self._label.text = f"{remaining:.1f}s"
