"""
Hardware synchronisation backends for EEG / neurophysiology.

Supported backends
------------------
TTLTrigger  — serial TTL pulse via a USB-to-serial adapter (requires pyserial)
LSLTrigger  — LabStreamingLayer marker stream             (requires pylsl)

Both are optional dependencies; a RuntimeError is raised on instantiation if
the underlying library is missing.  CompositeTrigger swallows per-backend
failures at send time so a hardware glitch never crashes a session.

Usage example
-------------
    trigger = CompositeTrigger()
    trigger.add(TTLTrigger(port="/dev/tty.usbserial-XXXX"))
    trigger.add(LSLTrigger("Battery"))
    ...
    trigger.send_event(EventType.STIM_START)   # → sends code 40
    trigger.send_event(EventType.IMAGE_ON)     # → sends code 11
    trigger.close()

Default event codes
-------------------
SESSION_START  =  1     SESSION_END    =  2
TRIAL_START    = 10     IMAGE_ON       = 11
RESPONSE       = 20
TRIAL_END      = 30
STIM_START     = 40     STIM_END       = 41
STIMULUS_SKIP  = 50
"""
from __future__ import annotations

from typing import Optional

from core.event_log import EventType


# ─────────────────────────────────────────────────────────────
# Default event → integer code mapping
# ─────────────────────────────────────────────────────────────

DEFAULT_CODES: dict[EventType, int] = {
    EventType.SESSION_START:   1,
    EventType.SESSION_END:     2,
    EventType.TRIAL_START:    10,
    EventType.IMAGE_ON:       11,
    EventType.RESPONSE:       20,
    EventType.TRIAL_END:      30,
    EventType.STIM_START:     40,
    EventType.STIM_END:       41,
    EventType.STIMULUS_SKIP:  50,
}


# ─────────────────────────────────────────────────────────────
# Abstract base
# ─────────────────────────────────────────────────────────────

class TriggerBackend:
    """Abstract base for all trigger backends."""

    def send(self, code: int) -> None:
        raise NotImplementedError

    def close(self) -> None:
        pass


# ─────────────────────────────────────────────────────────────
# TTL via serial port
# ─────────────────────────────────────────────────────────────

class TTLTrigger(TriggerBackend):
    """
    Serial TTL trigger.

    Sends a 1-byte code, waits *duration_s*, then sends 0x00 to reset the line.
    Works with any USB-to-serial adapter (FTDI, CP2102, …) wired to a BNC or
    parallel-port breakout for your amplifier.

    Parameters
    ----------
    port : str
        Serial port path, e.g. "/dev/tty.usbserial-FT3J" or "COM3".
    baudrate : int
        Baud rate (default 115 200). Must match receiver.
    duration_s : float
        How long the TTL pulse stays HIGH (seconds, default 2 ms).
    """

    def __init__(self, port: str, baudrate: int = 115_200, duration_s: float = 0.002):
        try:
            import serial as _serial  # noqa: F401
        except ImportError:
            raise RuntimeError(
                "pyserial is not installed.  Run:  pip install pyserial"
            )
        import serial as _serial
        self._ser       = _serial.Serial(port, baudrate=baudrate, timeout=1)
        self._duration  = duration_s

    def send(self, code: int) -> None:
        import time
        self._ser.write(bytes([code & 0xFF]))
        time.sleep(self._duration)
        self._ser.write(bytes([0x00]))  # reset line

    def close(self) -> None:
        if self._ser and self._ser.is_open:
            self._ser.close()


# ─────────────────────────────────────────────────────────────
# LabStreamingLayer
# ─────────────────────────────────────────────────────────────

class LSLTrigger(TriggerBackend):
    """
    LabStreamingLayer marker stream.

    Opens a 1-channel integer stream named *stream_name*.  Compatible with
    BrainVision Recorder, EEGLab, MNE-Python and any LSL-aware recorder.

    Parameters
    ----------
    stream_name : str
        LSL stream name (shown in the recorder's stream list).
    stream_id : str
        Unique identifier for this stream (any string).
    """

    def __init__(
        self,
        stream_name: str = "Battery",
        stream_id:   str = "battery_markers",
    ):
        try:
            from pylsl import StreamInfo, StreamOutlet, cf_int32  # noqa: F401
        except ImportError:
            raise RuntimeError(
                "pylsl is not installed.  Run:  pip install pylsl"
            )
        from pylsl import StreamInfo, StreamOutlet, cf_int32
        info          = StreamInfo(stream_name, "Markers", 1, 0, cf_int32, stream_id)
        self._outlet  = StreamOutlet(info)

    def send(self, code: int) -> None:
        self._outlet.push_sample([int(code)])

    def close(self) -> None:
        pass  # outlet cleaned up by GC


# ─────────────────────────────────────────────────────────────
# Composite dispatcher
# ─────────────────────────────────────────────────────────────

class CompositeTrigger:
    """
    Dispatches trigger events to one or more backends.

    Individual backend failures are caught silently so that a hardware issue
    never crashes the session.
    """

    def __init__(self):
        self._backends: list[TriggerBackend] = []
        self._codes: dict[EventType, int]    = DEFAULT_CODES.copy()

    def add(self, backend: TriggerBackend) -> None:
        """Register a backend."""
        self._backends.append(backend)

    def set_code(self, event_type: EventType, code: int) -> None:
        """Override the integer code sent for a specific EventType."""
        self._codes[event_type] = code

    @property
    def is_active(self) -> bool:
        return len(self._backends) > 0

    def send_event(
        self,
        event_type: EventType,
        custom_code: Optional[int] = None,
    ) -> None:
        """
        Look up the code for *event_type* and dispatch to all backends.
        If *custom_code* is given it overrides the lookup table.
        Events with code 0 (not in the table) are silently skipped.
        """
        code = (
            custom_code
            if custom_code is not None
            else self._codes.get(event_type, 0)
        )
        if code == 0 or not self._backends:
            return
        for backend in self._backends:
            try:
                backend.send(code)
            except Exception:
                pass  # never propagate trigger failures to the session

    def close(self) -> None:
        """Close all backends gracefully."""
        for backend in self._backends:
            try:
                backend.close()
            except Exception:
                pass
