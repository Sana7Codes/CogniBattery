import os
from typing import Callable, Optional

from kivy.uix.floatlayout import FloatLayout
from kivy.uix.image import Image
from kivy.uix.button import Button
from kivy.graphics import Color, Rectangle

from ui.theme import BG_COLOR, ACCENT_GREEN, ACCENT_RED, TEXT_COLOR, FONT_SIZE_LG


class FaceWidget(FloatLayout):
    """
    Displays a face image with Oui / Non response buttons.
    Used for both FamousFace and UnknownFace tasks.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self._response_cb: Optional[Callable] = None

        with self.canvas.before:
            Color(*BG_COLOR)
            self._bg_rect = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._update_bg, size=self._update_bg)

        self._face_img = Image(
            source="",
            fit_mode="contain",
            size_hint=(0.65, 0.78),
            pos_hint={"center_x": 0.5, "top": 0.97},
        )

        self._btn_oui = Button(
            text="Oui",
            font_size=FONT_SIZE_LG,
            size_hint=(0.30, 0.14),
            pos_hint={"x": 0.04, "y": 0.02},
            background_color=ACCENT_GREEN,
            color=TEXT_COLOR,
        )
        self._btn_non = Button(
            text="Non",
            font_size=FONT_SIZE_LG,
            size_hint=(0.30, 0.14),
            pos_hint={"right": 0.96, "y": 0.02},
            background_color=ACCENT_RED,
            color=TEXT_COLOR,
        )

        self.add_widget(self._face_img)
        self.add_widget(self._btn_oui)
        self.add_widget(self._btn_non)

        self._btn_oui.bind(on_press=self._oui_pressed)
        self._btn_non.bind(on_press=self._non_pressed)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self, stimulus, images_base: str) -> None:
        """Load face image from stimulus payload."""
        image_rel = stimulus.payload.get("face_image", "")
        abs_path = _resolve(image_rel, images_base)
        self._face_img.source = abs_path

    def on_response(self, callback: Callable) -> None:
        self._response_cb = callback

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _oui_pressed(self, instance) -> None:
        # Use last touch position (if available) for coordinate logging.
        touch = getattr(instance, "_last_touch", None)
        tx = int(touch.x) if touch else 0
        ty = int(touch.y) if touch else 0
        if self._response_cb:
            self._response_cb("oui", tx, ty)

    def _non_pressed(self, instance) -> None:
        touch = getattr(instance, "_last_touch", None)
        tx = int(touch.x) if touch else 0
        ty = int(touch.y) if touch else 0
        if self._response_cb:
            self._response_cb("non", tx, ty)

    def on_touch_down(self, touch):
        # Capture touch coords on buttons for coordinate logging.
        if self._btn_oui.collide_point(*touch.pos):
            self._btn_oui._last_touch = touch
        elif self._btn_non.collide_point(*touch.pos):
            self._btn_non._last_touch = touch
        return super().on_touch_down(touch)

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
