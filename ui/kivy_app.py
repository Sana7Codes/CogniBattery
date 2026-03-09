"""
KivyApp — orchestrator bridging the domain App and Kivy's UI framework.

New flow (v2):
  - No domain_app or stim_set at init.
  - ClinicianView starts in browser/config mode.
  - When ConfigScreen fires on_start_session, KivyApp creates the domain App,
    calls setup(), starts session, builds task, switches to session mode.
  - On "Terminer", session is ended, app returns to browser mode.
"""
import threading
from typing import Optional

from kivy.app import App as KivyBaseApp
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.uix.boxlayout import BoxLayout

import os

from ui.clinician_screen import ClinicianView
from ui.patient_screen import KivyPatientScreen
from core.session import ProgressionMode, SessionConfig
from core.stimulus import StimulusSet
from tasks.base_task import BaseTask


class KivyApp(KivyBaseApp):
    """
    Kivy application orchestrator.

    Parameters
    ----------
    base_dir : str
        Project root directory.
    images_base : str
        Absolute path to stimuli/images/.
    clinician_w : int
        Clinician monitor width in pixels.
    patient_w : int
        Patient monitor width in pixels.
    screen_h : int
        Shared height of both monitors.
    """

    POLL_INTERVAL_S = 0.010

    def __init__(
        self,
        base_dir: str,
        images_base: str,
        clinician_w: int = 1280,
        patient_w: int   = 1920,
        screen_h: int    = 1080,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._base_dir    = base_dir
        self._images_base = images_base
        self._clinician_w = clinician_w
        self._patient_w   = patient_w
        self._screen_h    = screen_h

        # Runtime state (populated on session start)
        self._domain_app          = None
        self._task: Optional[BaseTask] = None
        self._stim_set: Optional[StimulusSet] = None

        self._clinician_view:  Optional[ClinicianView]     = None
        self._patient_screen:  Optional[KivyPatientScreen] = None
        self._clock_event      = None

        self._timer_start_s: Optional[float] = None
        self._awaiting_clinician_advance: bool = False

        # Optional trigger backend (TTL / LSL) — set externally before run()
        from core.trigger import CompositeTrigger
        self.trigger = CompositeTrigger()

    # ------------------------------------------------------------------
    # Kivy App lifecycle
    # ------------------------------------------------------------------

    def build(self):
        self.title = "Battery — Cognitive Testing Platform"

        # Get the actual screen dimensions in logical points.
        # Window.size on macOS SDL2 uses logical points, so we read NSScreen
        # in points (not physical pixels) to stay in the same unit.
        total_w_req = self._clinician_w + self._patient_w
        h_req       = self._screen_h

        try:
            from AppKit import NSScreen
            # NSScreen gives dimensions in logical points (same unit as Window.size).
            # Do NOT multiply by density — that would produce physical pixels, which
            # Kivy does not accept for Window.size on macOS (SDL2 uses logical pts).
            frame    = NSScreen.mainScreen().frame()
            screen_w = int(frame.size.width)
            screen_h = int(frame.size.height)
        except Exception:
            # Non-macOS or pyobjc not available — assume screen is large enough
            screen_w = screen_h = 999999

        # Fit within the available screen, preserving the clinician/patient ratio
        if total_w_req > screen_w or h_req > screen_h:
            scale   = min(screen_w / total_w_req, screen_h / h_req)
            total_w = int(total_w_req * scale)
            h       = int(h_req * scale)
        else:
            total_w, h = total_w_req, h_req

        Window.size = (total_w, h)
        Window.left = 0
        Window.top  = 0

        clinician_ratio = self._clinician_w / (self._clinician_w + self._patient_w)

        self._clinician_view = ClinicianView(
            kivy_app    = self,
            base_dir    = self._base_dir,
            images_base = self._images_base,
            size_hint_x = clinician_ratio,
        )
        self._patient_screen = KivyPatientScreen(
            images_base = self._images_base,
            size_hint_x = 1.0 - clinician_ratio,
        )
        self._patient_screen.on_response(self._on_patient_response)

        # Polling clock — ticks even when no session is active (noop then)
        self._clock_event = Clock.schedule_interval(
            self._tick, self.POLL_INTERVAL_S
        )

        root = BoxLayout(orientation="horizontal")
        root.add_widget(self._clinician_view)
        root.add_widget(self._patient_screen)

        # Offer session recovery if any incomplete sessions are found
        Clock.schedule_once(self._check_recovery, 0.5)
        return root

    def on_stop(self):
        if self._clock_event is not None:
            self._clock_event.cancel()
            self._clock_event = None
        self._teardown_session(save=True)
        self.trigger.close()

    # ------------------------------------------------------------------
    # Session recovery
    # ------------------------------------------------------------------

    def _check_recovery(self, dt: float) -> None:
        """Called once 0.5 s after startup — shows recovery popup if needed.
        File I/O runs on a background thread to avoid blocking the UI."""
        import os
        from core.recovery import find_incomplete_sessions
        output_dir = os.path.join(self._base_dir, "Data")

        def _scan():
            try:
                candidates = find_incomplete_sessions(output_dir)
            except Exception:
                candidates = []
            if candidates:
                Clock.schedule_once(lambda dt: self._offer_recovery(candidates[0]), 0)

        threading.Thread(target=_scan, daemon=True).start()

    def _offer_recovery(self, info: dict) -> None:
        from kivy.uix.popup import Popup
        from kivy.uix.button import Button
        from kivy.uix.label import Label
        from kivy.metrics import dp

        msg = (
            f"Séance incomplète détectée\n\n"
            f"Patient : {info['patient_id']}\n"
            f"Date : {info['session_date']}\n"
            f"Test : {info['test_type']}\n"
            f"Essais complétés : {info['completed_trials']} / {info['total_trials']}\n\n"
            f"Reprendre là où la séance s'est arrêtée ?"
        )
        content = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(8))
        lbl = Label(text=msg, halign="center", valign="top", color=(1, 1, 1, 1))
        lbl.bind(size=lambda inst, val: setattr(inst, "text_size", (val[0], None)))
        content.add_widget(lbl)

        row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6))
        btn_yes = Button(
            text="Oui, reprendre",
            background_normal="", background_color=(0.20, 0.60, 0.35, 1),
            color=(1, 1, 1, 1),
        )
        btn_no = Button(
            text="Non, nouvelle séance",
            background_normal="", background_color=(0.40, 0.40, 0.40, 1),
            color=(1, 1, 1, 1),
        )
        row.add_widget(btn_yes)
        row.add_widget(btn_no)
        content.add_widget(row)

        popup = Popup(
            title="Récupération de séance",
            content=content,
            size_hint=(0.55, 0.50),
        )

        def _resume(*_):
            popup.dismiss()
            self._do_recovery(info)

        btn_yes.bind(on_press=_resume)
        btn_no.bind(on_press=popup.dismiss)
        popup.open()

    def _do_recovery(self, info: dict) -> None:
        # Run the heavy file I/O (load stimulus JSON files, read CSV) on a
        # background thread so the main UI thread stays responsive.
        from core.recovery import build_recovery_context
        stimuli_dir = os.path.join(self._base_dir, "stimuli")

        def _run():
            try:
                result = build_recovery_context(
                    csv_path         = info["csv_path"],
                    metadata_path    = info["metadata_path"],
                    stimuli_base_dir = stimuli_dir,
                )
            except Exception as exc:
                result = None
            Clock.schedule_once(lambda dt: self._finish_recovery(info, result), 0)

        threading.Thread(target=_run, daemon=True).start()

    def _finish_recovery(self, info: dict, result) -> None:
        """Called on the main thread after background recovery context is built."""
        if result is None:
            self._clinician_view.show_error(
                "Impossible de récupérer la séance (métadonnées manquantes)."
            )
            return
        config, stim_set, resume_trial = result
        self._recovery_csv = info["csv_path"]
        self._on_start_session_recover(config, stim_set, resume_trial, info["csv_path"])

    def _on_start_session_recover(
        self, config, stim_set, resume_trial: int, csv_path: str
    ) -> None:
        """Like _on_start_session but reopens an existing CSV for appending.
        File I/O runs on a background thread."""
        from app import App
        from core.event_log import PersistentEventLog
        from core.timing import Clock
        from core.session import Session

        def _setup():
            try:
                domain_app = App(config, output_base_dir=os.path.join(
                    self._base_dir, "Data"
                ))
                clock     = Clock()
                trigger   = self.trigger if self.trigger.is_active else None
                event_log = PersistentEventLog(clock, csv_path, trigger=trigger)
                session   = Session(config, event_log, clock)
                session.current_trial = resume_trial
                domain_app._session  = session
                domain_app._csv_path = csv_path
                session.start()
                task = self._make_task(config.test_type, session, stim_set)
                Clock.schedule_once(
                    lambda dt: self._finish_start_session(
                        config, stim_set, domain_app, session, task
                    ), 0
                )
            except Exception as exc:
                Clock.schedule_once(
                    lambda dt: self._clinician_view.show_error(
                        f"Récupération échouée: {exc}"
                    ), 0
                )

        threading.Thread(target=_setup, daemon=True).start()

    # ------------------------------------------------------------------
    # Session lifecycle (called from ClinicianView)
    # ------------------------------------------------------------------

    def _on_start_session(self, config: SessionConfig, stim_set: StimulusSet,
                          resume_trial: int = 0) -> None:
        """Create domain App, set up session, start first trial.

        File I/O (CSV creation, session.start fsync, metadata write) runs on
        a background thread.  UI updates happen on the main thread afterwards.
        """
        import os
        from app import App

        def _setup():
            try:
                domain_app = App(config, output_base_dir=os.path.join(
                    self._base_dir, "Data"
                ))
                domain_app.setup(
                    trigger=self.trigger if self.trigger.is_active else None
                )
                session = domain_app._session
                session.start()
                domain_app.write_session_metadata(stim_set)
                session.current_trial = resume_trial
                task = self._make_task(config.test_type, session, stim_set)
                Clock.schedule_once(
                    lambda dt: self._finish_start_session(
                        config, stim_set, domain_app, session, task
                    ), 0
                )
            except Exception as exc:
                Clock.schedule_once(
                    lambda dt: self._clinician_view.show_error(str(exc)), 0
                )

        threading.Thread(target=_setup, daemon=True).start()

    def _finish_start_session(self, config, stim_set, domain_app, session, task) -> None:
        """Called on main thread after background session setup completes."""
        self._domain_app = domain_app
        self._stim_set   = stim_set
        self._task       = task

        _listener = domain_app._stim_listener
        _key      = config.stim_signal_key
        def _start_listener():
            try:
                _listener.start_listening(
                    key=_key,
                    callback=self._on_stim_signal_safe,
                )
            except Exception as exc:
                def _warn(dt, _exc=exc):
                    session.error(_exc)
                    self._clinician_view.show_error(
                        f"Signal stimulation désactivé :\n{_exc}\n\n"
                        "La séance continue sans déclencheur externe."
                    )
                Clock.schedule_once(_warn, 0)
        threading.Thread(target=_start_listener, daemon=True).start()

        self._clinician_view.show_session_mode()

        if not stim_set.is_exhausted:
            stimulus = task.start_trial()
            self._patient_screen.show_stimulus(stimulus, self._images_base)
            if config.progression_mode == ProgressionMode.TIMER:
                self._patient_screen.start_timer(config.timer_duration_s)
                self._timer_start_s = session.clock.now_relative()

        self._clinician_view.update_session(self._build_state())

    def _on_end_session(self) -> None:
        self._teardown_session(save=True)
        self._clinician_view.show_browser_mode()

    def _teardown_session(self, save: bool = True) -> None:
        try:
            if self._domain_app and self._domain_app._stim_listener:
                self._domain_app._stim_listener.stop_listening()
        except Exception:
            pass
        try:
            if save and self._domain_app and self._domain_app._session:
                self._domain_app._session.end()
                # Write integrity hash after session is fully closed
                self._domain_app.write_integrity_hash()
        except Exception:
            pass
        self._domain_app  = None
        self._task        = None
        self._stim_set    = None
        self._timer_start_s = None
        self._awaiting_clinician_advance = False
        self._patient_screen.clear()

    # ------------------------------------------------------------------
    # Main tick
    # ------------------------------------------------------------------

    def _tick(self, dt: float) -> None:
        if self._task is None or self._domain_app is None:
            return
        config = self._config
        if config is None:
            return
        try:
            session = self._domain_app._session
            if session is None:
                return

            self._clinician_view.update_timer(session.clock.now_relative())

            fired = session.check_and_fire_stim_end()
            if fired:
                self._clinician_view.on_stim_ended()

            if session.is_stim_active and session._pending_stim is not None:
                remaining = max(
                    0.0,
                    session._pending_stim["end_time_s"] - session.clock.now_relative(),
                )
                self._clinician_view.update_stim_status(
                    active=True,
                    duration_s=config.stim_duration_s,
                    remaining_s=remaining,
                )

            if config.progression_mode == ProgressionMode.TIMER:
                if config.timer_duration_s is not None and self._timer_start_s is not None:
                    elapsed = session.clock.now_relative() - self._timer_start_s
                    if elapsed >= config.timer_duration_s:
                        self._advance_trial()

        except Exception as exc:
            try:
                self._domain_app._session.error(exc)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Stim signal bridge
    # ------------------------------------------------------------------

    def _on_stim_signal_safe(self) -> None:
        Clock.schedule_once(self._on_stim_signal_main, 0)

    def _on_stim_signal_main(self, dt: float) -> None:
        config = self._config
        if self._domain_app is None or config is None:
            return
        try:
            session   = self._domain_app._session
            session.record_stim_start()
            duration_s = config.stim_duration_s
            self._clinician_view.update_stim_status(
                active=True,
                duration_s=duration_s,
                remaining_s=duration_s,
            )
        except Exception as exc:
            try:
                self._domain_app._session.error(exc)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Clinician callbacks (wired by ClinicianView → SessionScreen)
    # ------------------------------------------------------------------

    def _on_advance(self) -> None:
        try:
            self._advance_trial()
        except Exception as exc:
            self._domain_app._session.error(exc)
            self._clinician_view.show_error(str(exc))

    def _on_skip(self) -> None:
        try:
            self._task.skip_trial()
            self._start_next_or_end()
        except Exception as exc:
            self._domain_app._session.error(exc)
            self._clinician_view.show_error(str(exc))

    def _on_replace_stimulus(self, reason: str = "") -> None:
        if self._task is None:
            return
        candidates = self._task.stimulus_set.get_remaining()
        if not candidates:
            self._clinician_view.show_error("Aucun stimulus de remplacement disponible.")
            return
        self._show_replace_popup(candidates, reason)

    def _show_replace_popup(self, candidates: list, reason: str) -> None:
        from kivy.uix.popup import Popup
        from kivy.uix.button import Button
        from kivy.uix.label import Label
        from kivy.uix.scrollview import ScrollView
        from kivy.metrics import dp

        content = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))
        content.add_widget(Label(text="Choisir un stimulus de remplacement :",
                                 size_hint_y=None, height=dp(30), color=(1, 1, 1, 1)))

        scroll = ScrollView(size_hint=(1, 1))
        btn_list = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(4))
        btn_list.bind(minimum_height=btn_list.setter("height"))

        popup = Popup(title="Remplacer le stimulus", content=content,
                      size_hint=(0.5, 0.60))

        for stim in candidates:
            b = Button(text=stim.stimulus_id, size_hint_y=None, height=dp(40),
                       background_normal="", background_color=(0.20, 0.50, 0.80, 1))
            def _pick(instance, s=stim):
                popup.dismiss()
                self._do_replace(s, reason)
            b.bind(on_press=_pick)
            btn_list.add_widget(b)

        scroll.add_widget(btn_list)
        content.add_widget(scroll)

        cancel = Button(text="Annuler", size_hint_y=None, height=dp(44))
        cancel.bind(on_press=popup.dismiss)
        content.add_widget(cancel)
        popup.open()

    def _do_replace(self, new_stimulus, reason: str = "") -> None:
        try:
            self._task.replace_stimulus(new_stimulus, reason)
            self._patient_screen.show_stimulus(new_stimulus, self._images_base)
            self._clinician_view.update_session(self._build_state())
        except Exception as exc:
            self._domain_app._session.error(exc)
            self._clinician_view.show_error(str(exc))

    def _on_exclude_stimulus(self, reason: str = "") -> None:
        try:
            stimulus = self._task.stimulus_set.current
            if stimulus is not None:
                self._task.exclude_stimulus(stimulus.stimulus_id, reason)
            self._clinician_view.update_session(self._build_state())
        except Exception as exc:
            self._domain_app._session.error(exc)
            self._clinician_view.show_error(str(exc))

    # ------------------------------------------------------------------
    # Patient response
    # ------------------------------------------------------------------

    def _on_patient_response(self, response: str, touch_x: int, touch_y: int) -> None:
        if self._task is None:
            return
        try:
            self._task.record_response(response, touch_x, touch_y)
            mode = self._config.progression_mode
            if mode == ProgressionMode.PATIENT_TOUCH:
                self._advance_trial()
            elif mode == ProgressionMode.CLINICIAN_ACTION:
                self._awaiting_clinician_advance = True
            self._clinician_view.update_session(self._build_state())
        except Exception as exc:
            self._domain_app._session.error(exc)
            self._clinician_view.show_error(str(exc))

    # ------------------------------------------------------------------
    # Trial advancement
    # ------------------------------------------------------------------

    def _advance_trial(self) -> None:
        try:
            self._task.end_trial()
            self._awaiting_clinician_advance = False
            self._patient_screen.clear()
            self._start_next_or_end()
        except Exception as exc:
            self._domain_app._session.error(exc)
            self._clinician_view.show_error(str(exc))

    def _start_next_or_end(self) -> None:
        if self._task.stimulus_set.is_exhausted:
            self._show_session_complete_popup()
            return
        stimulus = self._task.start_trial()
        self._patient_screen.show_stimulus(stimulus, self._images_base)
        if self._config.progression_mode == ProgressionMode.TIMER:
            self._patient_screen.start_timer(self._config.timer_duration_s)
            self._timer_start_s = self._domain_app._session.clock.now_relative()
        else:
            self._patient_screen.stop_timer()
        self._clinician_view.update_session(self._build_state())

    # ------------------------------------------------------------------
    # Session complete popup
    # ------------------------------------------------------------------

    def _show_session_complete_popup(self) -> None:
        # Clear _task immediately so _tick stops trying to advance trials.
        self._task = None
        self._timer_start_s = None

        from kivy.uix.popup import Popup
        from kivy.uix.button import Button
        from kivy.uix.label import Label
        content = BoxLayout(orientation="vertical", padding=10, spacing=10)
        lbl = Label(text="Tous les stimuli ont été présentés.\nSéance terminée.",
                    halign="center", color=(1, 1, 1, 1))
        lbl.bind(size=lambda inst, val: setattr(inst, "text_size", (val[0], None)))
        content.add_widget(lbl)
        btn = Button(text="Terminer et sauvegarder", size_hint_y=None, height=44)
        content.add_widget(btn)
        popup = Popup(title="Séance terminée", content=content, size_hint=(0.5, 0.35))
        btn.bind(on_press=lambda *_: (popup.dismiss(), self._on_end_session()))
        popup.open()

    # ------------------------------------------------------------------
    # State dict
    # ------------------------------------------------------------------

    def _build_state(self) -> dict:
        if self._domain_app is None or self._domain_app._session is None:
            return {}
        session  = self._domain_app._session
        config   = self._config
        stimulus = self._task.stimulus_set.current if self._task else None

        remaining_s = 0.0
        if session.is_stim_active and session._pending_stim is not None:
            remaining_s = max(
                0.0,
                session._pending_stim["end_time_s"] - session.clock.now_relative(),
            )

        return {
            "patient_id":                 config.patient_id,
            "test_type":                  config.test_type,
            "progression_mode":           config.progression_mode.value,
            "electrode":                  config.electrode,
            "contact":                    config.contact,
            "current_trial":              session.current_trial,
            "total_trials":               len(self._task.stimulus_set) if self._task else 0,
            "stimulus":                   stimulus,
            "images_base":                self._images_base,
            "is_stim_active":             session.is_stim_active,
            "stim_remaining_s":           remaining_s,
            "elapsed_s":                  session.clock.now_relative(),
            "recent_events":              session.event_log._cache[-10:],
            "awaiting_clinician_advance": self._awaiting_clinician_advance,
        }

    # ------------------------------------------------------------------
    # Task factory
    # ------------------------------------------------------------------

    def _make_task(self, test_type: str, session, stim_set) -> BaseTask:
        if test_type == "SemanticMatching":
            from tasks.semantic_matching import SemanticMatchingTask
            return SemanticMatchingTask(session, stim_set)
        elif test_type == "FamousFace":
            from tasks.famous_face import FamousFaceTask
            return FamousFaceTask(session, stim_set)
        elif test_type == "UnknownFace":
            from tasks.unknown_face import UnknownFaceTask
            return UnknownFaceTask(session, stim_set)
        else:
            raise ValueError(f"Unknown test type: {test_type!r}")

    # ------------------------------------------------------------------
    # Convenience property
    # ------------------------------------------------------------------

    @property
    def _config(self) -> Optional[SessionConfig]:
        if self._domain_app is None:
            return None
        return self._domain_app._config
