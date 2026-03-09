import os
import time
from typing import Optional

from core.event_log import PersistentEventLog
from core.session import Session, SessionConfig
from core.stim_signal import StimSignalListener
from core.timing import Clock
from data.file_manager import FileManager
from data.session_metadata import write_metadata
from data.integrity import write_hash


class App:
    """
    Entry point and orchestrator.

    Responsibilities:
    - Wire up Clock, PersistentEventLog, Session, and StimSignalListener.
    - Run the main event loop: poll stim-end, dispatch UI events.
    - Capture all exceptions and record them via session.error().

    Subclass and override _tick() to integrate a specific UI framework
    (Kivy, tkinter, pygame, etc.).
    """

    POLL_INTERVAL_S = 0.010  # 10 ms polling interval

    def __init__(self, config: Optional[SessionConfig] = None,
                 output_base_dir: str = "output"):
        self._config          = config
        self._output_base_dir = output_base_dir
        self._session:         Optional[Session] = None
        self._stim_listener    = StimSignalListener()
        self._running          = False
        self._csv_path:        Optional[str] = None  # set during setup()

    def set_config(self, config: SessionConfig) -> None:
        """Set or replace the session config before calling setup()."""
        self._config = config

    # ------------------------------------------------------------------ #
    # Setup                                                                #
    # ------------------------------------------------------------------ #

    def setup(self, trigger=None) -> None:
        """
        Create the output file and initialise the session.
        Must be called before run().

        Parameters
        ----------
        trigger : CompositeTrigger | None
            Optional hardware trigger backend forwarded to the event log.
        """
        file_manager = FileManager(self._output_base_dir)
        csv_path = file_manager.get_csv_path(
            self._config.patient_id,
            self._config.session_date,
            self._config.test_type,
            self._config.session_start_time,
        )
        file_manager.ensure_dirs(csv_path)

        clock     = Clock()
        event_log = PersistentEventLog(clock, csv_path, trigger=trigger)
        self._session  = Session(self._config, event_log, clock)
        self._csv_path = csv_path

    def write_session_metadata(self, stim_set, counterbalancing_report=None) -> None:
        """Write session_metadata.json sidecar.  Call after setup() and session.start()."""
        if self._csv_path and self._session:
            try:
                write_metadata(
                    csv_path                = self._csv_path,
                    session_id              = self._session.session_id,
                    config                  = self._config,
                    stim_set                = stim_set,
                    counterbalancing_report = counterbalancing_report,
                )
            except Exception:
                pass  # metadata failure never aborts a session

    def write_integrity_hash(self) -> None:
        """Write SHA-256 hash sidecar for the session CSV.  Call after session.end()."""
        if self._csv_path and os.path.exists(self._csv_path):
            try:
                write_hash(self._csv_path)
            except Exception:
                pass  # hash failure is non-critical

    # ------------------------------------------------------------------ #
    # Run                                                                  #
    # ------------------------------------------------------------------ #

    def run(self) -> None:
        """
        Start the session and enter the main event loop.
        Always calls session.end() on exit, even after an exception.
        """
        if self._session is None:
            raise RuntimeError("Call setup() before run().")

        self._session.start()
        self._stim_listener.start_listening(
            key=self._config.stim_signal_key,
            callback=self._on_stim_signal,
        )
        self._running = True

        try:
            self._event_loop()
        except Exception as exc:
            self._session.error(exc)
            raise
        finally:
            self._running = False
            self._stim_listener.stop_listening()
            self._session.end()

    def stop(self) -> None:
        """Signal the event loop to exit cleanly."""
        self._running = False

    # ------------------------------------------------------------------ #
    # Internal                                                             #
    # ------------------------------------------------------------------ #

    def _on_stim_signal(self) -> None:
        """Called from StimSignalListener thread on trigger keypress."""
        try:
            self._session.record_stim_start()
        except Exception as exc:
            self._session.error(exc)

    def _event_loop(self) -> None:
        """
        Main event loop.
        - Polls session.check_and_fire_stim_end() every tick.
        - Calls _tick() for UI-framework-specific work.
        - Wraps each tick in try/except → session.error().
        """
        while self._running:
            try:
                self._session.check_and_fire_stim_end()
                self._tick()
            except Exception as exc:
                self._session.error(exc)
            time.sleep(self.POLL_INTERVAL_S)

    def _tick(self) -> None:
        """
        Override in a subclass to drive UI-framework-specific per-tick logic.
        Example: call kivy's Clock.tick(), pump a pygame event queue, etc.
        """
        pass

    # ------------------------------------------------------------------ #
    # Convenience property                                                 #
    # ------------------------------------------------------------------ #

    @property
    def session(self) -> Optional[Session]:
        return self._session
