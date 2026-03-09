from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label
from kivy.graphics import Color, Rectangle

from ui.theme import BG_COLOR, FONT_SIZE_XL


class FixationWidget(FloatLayout):
    """
    Black screen with a centred fixation cross (+).
    Displayed between trials to prevent spurious touch input.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        with self.canvas.before:
            Color(*BG_COLOR)
            self._bg_rect = Rectangle(pos=self.pos, size=self.size)

        self.bind(pos=self._update_bg, size=self._update_bg)

        self._cross = Label(
            text="+",
            font_size=48,
            color=(1, 1, 1, 1),
            size_hint=(None, None),
            size=(60, 60),
            pos_hint={"center_x": 0.5, "center_y": 0.5},
        )
        self.add_widget(self._cross)

    def _update_bg(self, *_):
        self._bg_rect.pos = self.pos
        self._bg_rect.size = self.size

    def on_touch_down(self, touch):
        # Consume all touches while the fixation cross is showing.
        if self.collide_point(*touch.pos):
            return True
        return super().on_touch_down(touch)
