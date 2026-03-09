import sys
from typing import Callable, Optional

try:
    from pynput import keyboard
    _PYNPUT_AVAILABLE = True
except ImportError:
    _PYNPUT_AVAILABLE = False


def _check_permissions() -> None:
    """
    On macOS, pynput requires two separate permissions:
      1. Accessibility  (AXIsProcessTrusted)  — prevents SIGILL at startup
      2. Input Monitoring (CGPreflightListenEventAccess) — prevents the OS
         from showing a blocking system dialog when CGEventTap is created,
         which would freeze the entire app even from a background thread.
    Both are checked upfront and raise RuntimeError if absent.
    """
    if sys.platform != "darwin":
        return
    try:
        import ctypes

        # -- 1. Accessibility --
        appservices = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/ApplicationServices.framework"
            "/ApplicationServices"
        )
        fn = appservices.AXIsProcessTrusted
        fn.restype = ctypes.c_bool
        if not fn():
            raise RuntimeError(
                "macOS Accessibility permission not granted — "
                "stim signal listener disabled.\n"
                "To enable: System Settings → Privacy & Security → "
                "Accessibility → add your Terminal (or Python)."
            )

        # -- 2. Input Monitoring --
        # CGPreflightListenEventAccess() returns True if granted WITHOUT
        # showing any system dialog (unlike CGRequestListenEventAccess).
        cg = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
        )
        preflight = cg.CGPreflightListenEventAccess
        preflight.restype = ctypes.c_bool
        if not preflight():
            raise RuntimeError(
                "macOS Input Monitoring permission not granted — "
                "stim signal listener disabled.\n"
                "To enable: System Settings → Privacy & Security → "
                "Input Monitoring → add your Terminal (or Python)."
            )

    except RuntimeError:
        raise
    except Exception as exc:
        # If the permission check itself errors, do NOT let pynput proceed —
        # attempting CGEventTapCreate without a confirmed grant can trigger a
        # blocking macOS modal dialog that freezes the entire process.
        raise RuntimeError(
            f"macOS permission check failed ({exc}); "
            "stim signal listener disabled to prevent app freeze.\n"
            "Grant Accessibility + Input Monitoring in System Settings → Privacy & Security."
        ) from exc


class StimSignalListener:
    """
    Listens for an external keypress (e.g. F12 from a USB trigger button).
    Fires a callback when the configured STIM_START signal is received.

    Thread-safety note: the callback is invoked from the listener thread.
    The caller (App) is responsible for marshaling to the UI thread if needed.
    The listener must never write files directly; it only signals the session
    via the App/controller.
    """

    def __init__(self):
        self._listener = None
        self._key: str = ""
        self._callback: Optional[Callable] = None

    def start_listening(self, key: str, callback: Callable) -> None:
        if not _PYNPUT_AVAILABLE:
            raise RuntimeError(
                "pynput is required for StimSignalListener. "
                "Install with: pip install pynput"
            )
        _check_permissions()
        self._key = key
        self._callback = callback
        self._listener = keyboard.Listener(on_press=self._on_press)
        self._listener.start()

    def _on_press(self, key) -> None:
        try:
            key_str = key.name if hasattr(key, "name") else str(key)
        except AttributeError:
            key_str = str(key)
        if key_str == self._key and self._callback is not None:
            self._callback()

    def stop_listening(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None


# ---------------------------------------------------------------------------
# Subprocess-isolated listener (safe on Apple Silicon / macOS 15)
# ---------------------------------------------------------------------------

def _listener_subprocess_worker(key: str, queue) -> None:
    """
    Runs inside an isolated subprocess.
    A SIGILL or blocking macOS security dialog here cannot crash the parent process.
    """
    try:
        from pynput import keyboard

        def on_press(k):
            try:
                key_str = k.name if hasattr(k, "name") else str(k)
                if key_str == key:
                    queue.put_nowait("trigger")
            except Exception:
                pass

        with keyboard.Listener(on_press=on_press) as listener:
            listener.join()
    except Exception:
        pass  # Subprocess exits quietly on any error


class SubprocessStimSignalListener:
    """
    Runs pynput in an isolated subprocess so that a SIGILL (Accessibility
    permission missing on Apple Silicon) or a blocking macOS Input Monitoring
    security dialog cannot crash or freeze the main application process.

    Usage:
        listener = SubprocessStimSignalListener()
        listener.start_listening(key="f12", callback=my_callback)
        # In the main loop:
        listener.poll()          # fires callback for each queued trigger
        # On teardown:
        listener.stop_listening()
    """

    def __init__(self):
        self._process = None
        self._queue = None
        self._callback: Optional[Callable] = None

    def start_listening(self, key: str, callback: Callable) -> None:
        import multiprocessing
        self._callback = callback
        self._queue = multiprocessing.Queue()
        self._process = multiprocessing.Process(
            target=_listener_subprocess_worker,
            args=(key, self._queue),
            daemon=True,
        )
        self._process.start()

    def poll(self) -> None:
        """Call from the main event-loop tick to dispatch any queued triggers."""
        if self._queue is None or self._callback is None:
            return
        try:
            while not self._queue.empty():
                self._queue.get_nowait()
                self._callback()
        except Exception:
            pass

    def stop_listening(self) -> None:
        if self._process is not None:
            self._process.terminate()
            self._process = None
        self._queue = None
        self._callback = None
