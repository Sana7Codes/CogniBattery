import os
from typing import Callable, Optional

from kivy.uix.floatlayout import FloatLayout
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.clock import Clock
from kivy.graphics import Color, Rectangle, Line

from ui.theme import BG_COLOR, TEXT_COLOR, ACCENT_GREEN, FONT_SIZE_MD


class SemanticMatchingWidget(FloatLayout):
    """
    Displays:
      - One centre image (the probe)
      - Two choice images (left / right)
      - Labels beneath each image
    Patient taps a choice image to record a "left" or "right" response.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self._response_cb: Optional[Callable] = None

        with self.canvas.before:
            Color(*BG_COLOR)
            self._bg_rect = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._update_bg, size=self._update_bg)

        # --- Centre probe ---
        self._center_img = Image(
            source="",
            fit_mode="contain",
            size_hint=(0.38, 0.48),
            pos_hint={"center_x": 0.50, "top": 0.92},
        )
        self._center_lbl = Label(
            text="",
            size_hint=(0.38, 0.07),
            pos_hint={"center_x": 0.50, "top": 0.43},
            font_size=FONT_SIZE_MD,
            color=TEXT_COLOR,
        )

        # --- Left choice ---
        self._left_img = Image(
            source="",
            fit_mode="contain",
            size_hint=(0.28, 0.38),
            pos_hint={"x": 0.04, "top": 0.40},
        )
        self._left_lbl = Label(
            text="",
            size_hint=(0.28, 0.07),
            pos_hint={"x": 0.04, "top": 0.07},
            font_size=FONT_SIZE_MD,
            color=TEXT_COLOR,
        )

        # --- Right choice ---
        self._right_img = Image(
            source="",
            fit_mode="contain",
            size_hint=(0.28, 0.38),
            pos_hint={"right": 0.96, "top": 0.40},
        )
        self._right_lbl = Label(
            text="",
            size_hint=(0.28, 0.07),
            pos_hint={"right": 0.96, "top": 0.07},
            font_size=FONT_SIZE_MD,
            color=TEXT_COLOR,
        )

        for w in (
            self._center_img, self._center_lbl,
            self._left_img, self._left_lbl,
            self._right_img, self._right_lbl,
        ):
            self.add_widget(w)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self, stimulus, images_base: str) -> None:
        """Populate images and labels from the stimulus payload."""
        payload = stimulus.payload

        center_rel = payload.get("center_image", "")
        left_rel   = payload.get("left_image",   "")
        right_rel  = payload.get("right_image",  "")

        self._center_img.source = _resolve(center_rel, images_base)
        self._left_img.source   = _resolve(left_rel,   images_base)
        self._right_img.source  = _resolve(right_rel,  images_base)

        self._center_lbl.text = payload.get("center_label", "")
        self._left_lbl.text   = payload.get("left_label",   "")
        self._right_lbl.text  = payload.get("right_label",  "")

    def on_response(self, callback: Callable) -> None:
        self._response_cb = callback

    # ------------------------------------------------------------------
    # Touch handling
    # ------------------------------------------------------------------

    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos):
            return super().on_touch_down(touch)

        if self._left_img.collide_point(*touch.pos):
            self._flash(self._left_img)
            if self._response_cb:
                self._response_cb("left", touch.x, touch.y)
            return True

        if self._right_img.collide_point(*touch.pos):
            self._flash(self._right_img)
            if self._response_cb:
                self._response_cb("right", touch.x, touch.y)
            return True

        return super().on_touch_down(touch)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _flash(self, img_widget: Image) -> None:
        """Draw a green border around the selected image for 300 ms."""
        with img_widget.canvas.after:
            Color(*ACCENT_GREEN)
            self._highlight_line = Line(
                rectangle=(
                    img_widget.x, img_widget.y,
                    img_widget.width, img_widget.height,
                ),
                width=3,
            )
        Clock.schedule_once(lambda dt: img_widget.canvas.after.clear(), 0.3)

    def _update_bg(self, *_):
        self._bg_rect.pos = self.pos
        self._bg_rect.size = self.size


def _resolve(relative_path: str, images_base: str) -> str:
    if not relative_path:
        return os.path.join(images_base, "placeholder.png")
    abs_path = os.path.join(images_base, relative_path)
    if not os.path.exists(abs_path):
        return os.path.join(images_base, "placeholder.png")
    return abs_path
