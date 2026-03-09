"""
NavBar — top navigation bar for browser mode (no active session).

Tabs: "Nouvelle Séance" | "Banque de stimuli" | "Historique"
Right: "↗ Quitter" button
"""
from typing import Callable, Optional

from kivy.graphics import Color, Rectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label

from ui.theme import (
    NAV_BG, BTN_PRIMARY, BTN_GHOST, TEXT_DARK, TEXT_WHITE,
    FONT_MD, FONT_SM, NAV_H, BTN_H,
)

TABS = [
    ("config",  "Nouvelle Séance"),
    ("bank",    "Banque de stimuli"),
    ("history", "Historique"),
]


class NavBar(BoxLayout):
    """Height=56dp navigation bar with 3 tabs and a Quitter button."""

    def __init__(self, **kwargs):
        kwargs.setdefault("orientation", "horizontal")
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", dp(NAV_H))
        kwargs.setdefault("spacing", 0)
        super().__init__(**kwargs)

        self._on_tab_change_cb: Optional[Callable[[str], None]] = None
        self._on_quit_cb:       Optional[Callable[[], None]]    = None
        self._active_tab: str = "config"
        self._tab_buttons: dict[str, Button] = {}

        with self.canvas.before:
            Color(*NAV_BG)
            rect = Rectangle(pos=self.pos, size=self.size)
        self.bind(
            pos=lambda i, v: setattr(rect, "pos", v),
            size=lambda i, v: setattr(rect, "size", v),
        )

        # Left spacer
        self.add_widget(BoxLayout(size_hint_x=0.05))

        # Centre: tab buttons
        centre = BoxLayout(orientation="horizontal", size_hint_x=0.70, spacing=dp(4))
        for tab_id, tab_label in TABS:
            btn = Button(
                text=tab_label,
                font_size=dp(FONT_MD),
                background_normal="",
                background_color=(0, 0, 0, 0),
                color=TEXT_DARK,
                bold=False,
            )
            btn.bind(on_press=lambda inst, tid=tab_id: self._on_tab_press(tid))
            self._tab_buttons[tab_id] = btn
            centre.add_widget(btn)
        self.add_widget(centre)

        # Right: Quitter
        right = BoxLayout(orientation="horizontal", size_hint_x=0.25,
                          padding=(0, dp(8), dp(8), dp(8)))
        quit_btn = Button(
            text="↗ Quitter",
            font_size=dp(FONT_SM),
            size_hint=(None, None),
            size=(dp(120), dp(BTN_H)),
            background_normal="",
            background_color=BTN_GHOST,
            color=TEXT_DARK,
        )
        quit_btn.bind(on_press=lambda *_: self._on_quit_cb and self._on_quit_cb())
        right.add_widget(quit_btn)
        self.add_widget(right)

        self.set_active("config")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_active(self, tab_id: str) -> None:
        self._active_tab = tab_id
        for tid, btn in self._tab_buttons.items():
            btn.bold = (tid == tab_id)
            btn.color = TEXT_DARK

    def on_tab_change(self, callback: Callable[[str], None]) -> None:
        self._on_tab_change_cb = callback

    def on_quit(self, callback: Callable[[], None]) -> None:
        self._on_quit_cb = callback

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _on_tab_press(self, tab_id: str) -> None:
        self.set_active(tab_id)
        if self._on_tab_change_cb:
            self._on_tab_change_cb(tab_id)
