"""
ClinicianView — left panel of the spanning window.

Two modes:
  Browser mode  (no active session): NavBar + ScreenManager (config/bank/history)
  Session mode  (session active):    SessionScreen full height
"""
from typing import Callable, Optional

from kivy.graphics import Color, Rectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.screenmanager import ScreenManager, Screen, NoTransition

from ui.screens.nav_bar import NavBar
from ui.screens.config_screen import ConfigScreen
from ui.screens.session_screen import SessionScreen
from ui.screens.bank_screen import BankScreen
from ui.screens.history_screen import HistoryScreen
from ui.theme import BG_COLOR


class ClinicianView(BoxLayout):
    """
    Vertical BoxLayout that switches between browser and session modes.

    Parameters
    ----------
    kivy_app : KivyApp
        Parent Kivy app — used for callback wiring.
    base_dir : str
        Project root (for loading stimuli / reading history CSV).
    images_base : str
        Absolute path to stimuli/images/.
    """

    def __init__(self, kivy_app, base_dir: str, images_base: str, **kwargs):
        kwargs.setdefault("orientation", "vertical")
        super().__init__(**kwargs)

        self._kivy_app    = kivy_app
        self._base_dir    = base_dir
        self._images_base = images_base

        self._nav_bar:        Optional[NavBar]         = None
        self._screen_manager: Optional[ScreenManager]  = None
        self._session_screen: Optional[SessionScreen]  = None
        self._config_screen:  Optional[ConfigScreen]   = None

        with self.canvas.before:
            Color(*BG_COLOR)
            rect = Rectangle(pos=self.pos, size=self.size)
        self.bind(
            pos=lambda i, v: setattr(rect, "pos", v),
            size=lambda i, v: setattr(rect, "size", v),
        )

        self.show_browser_mode()

    # ------------------------------------------------------------------
    # Mode switching
    # ------------------------------------------------------------------

    def show_browser_mode(self) -> None:
        """Show NavBar + tabbed ScreenManager (config / bank / history)."""
        self.clear_widgets()
        self._session_screen = None

        self._nav_bar = NavBar(size_hint_y=None, height=dp(56))
        self._nav_bar.on_tab_change(self._on_tab_change)
        self._nav_bar.on_quit(self._kivy_app.stop)
        self.add_widget(self._nav_bar)

        self._screen_manager = ScreenManager(transition=NoTransition())

        # Config tab
        config_screen_wrap = Screen(name="config")
        self._config_screen = ConfigScreen(
            base_dir=self._base_dir,
            images_base=self._images_base,
        )
        self._config_screen.on_start_session(self._on_start_session)
        config_screen_wrap.add_widget(self._config_screen)
        self._screen_manager.add_widget(config_screen_wrap)

        # Bank tab
        bank_screen_wrap = Screen(name="bank")
        bank_screen_wrap.add_widget(BankScreen(base_dir=self._base_dir))
        self._screen_manager.add_widget(bank_screen_wrap)

        # History tab
        history_screen_wrap = Screen(name="history")
        history_screen_wrap.add_widget(HistoryScreen(base_dir=self._base_dir))
        self._screen_manager.add_widget(history_screen_wrap)

        self._screen_manager.current = "config"
        self.add_widget(self._screen_manager)

    def show_session_mode(self) -> None:
        """Replace browser widgets with full-height SessionScreen."""
        self.clear_widgets()
        self._nav_bar        = None
        self._screen_manager = None

        self._session_screen = SessionScreen()
        self._session_screen.on_end_session(self._on_end_session)
        self._session_screen.on_advance(self._kivy_app._on_advance)
        self._session_screen.on_skip(self._kivy_app._on_skip)
        self._session_screen.on_exclude(self._kivy_app._on_exclude_stimulus)
        self._session_screen.on_replace(self._kivy_app._on_replace_stimulus)
        self.add_widget(self._session_screen)

    # ------------------------------------------------------------------
    # Forwarded rendering API (called by KivyApp)
    # ------------------------------------------------------------------

    def update_session(self, state: dict) -> None:
        if self._session_screen is not None:
            self._session_screen.update(state)

    def update_timer(self, elapsed_s: float) -> None:
        if self._session_screen is not None:
            self._session_screen.update_timer(elapsed_s)

    def update_stim_status(
        self,
        active: bool,
        duration_s: float = 0.0,
        remaining_s: float = 0.0,
    ) -> None:
        if self._session_screen is not None:
            self._session_screen.set_stim_active(active, remaining_s)

    def on_stim_ended(self) -> None:
        if self._session_screen is not None:
            self._session_screen.on_stim_ended()

    def show_error(self, message: str) -> None:
        if self._session_screen is not None:
            self._session_screen.show_error(message)
        else:
            # Fallback popup when in browser mode
            from kivy.uix.popup import Popup
            from kivy.uix.label import Label
            from kivy.uix.button import Button
            content = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(10))
            content.add_widget(Label(text=message, color=(0.8, 0.2, 0.2, 1)))
            btn = Button(text="OK", size_hint_y=None, height=dp(40))
            content.add_widget(btn)
            popup = Popup(title="Erreur", content=content, size_hint=(0.6, 0.4))
            btn.bind(on_press=popup.dismiss)
            popup.open()

    # ------------------------------------------------------------------
    # Internal callbacks
    # ------------------------------------------------------------------

    def _on_tab_change(self, tab_id: str) -> None:
        if self._screen_manager is not None:
            self._screen_manager.current = tab_id

    def _on_start_session(self, config, stim_set) -> None:
        """Called from ConfigScreen — passed up to KivyApp."""
        self._kivy_app._on_start_session(config, stim_set)

    def _on_end_session(self) -> None:
        """Called from SessionScreen — passed up to KivyApp."""
        self._kivy_app._on_end_session()


# ---------------------------------------------------------------------------
# Legacy alias — keeps any import of KivyClinicianScreen working
# ---------------------------------------------------------------------------
KivyClinicianScreen = ClinicianView
