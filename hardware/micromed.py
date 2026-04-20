"""
Micromed SystemPLUS trigger interface.

The Battery software sends a TTL pulse ONLY at IMAGE_ON.
It NEVER triggers stimulation start or end — that is handled externally
by the medical team pressing the dedicated button on the Micromed unit.

RealTrigger requires pyserial and a connected Micromed device.
MockTrigger prints to console and is used when MOCK_HARDWARE=True.
"""

from __future__ import annotations

import config
from core.error_log import log_error, log_info

TTL_IMAGE_ON: int = 1  # code sent at IMAGE_ON


# ─── Interface ────────────────────────────────────────────────────────────────

class _BaseTrigger:
    def send(self, code: int) -> None:
        raise NotImplementedError

    def close(self) -> None:
        pass


# ─── Real hardware trigger ────────────────────────────────────────────────────

class RealTrigger(_BaseTrigger):
    """
    Sends a TTL pulse to Micromed via USB-to-serial.

    The Micromed SystemPLUS EVOLUTION interprets a byte written to the
    serial port as a parallel-port value.  Code 1 = IMAGE_ON marker.
    """

    def __init__(self, port: str = "/dev/tty.usbserial-FTXXXXX") -> None:
        try:
            import serial  # type: ignore
            self._ser = serial.Serial(port, baudrate=115200, timeout=1)
            log_info(f"[Micromed] serial port opened: {port}")
        except Exception as exc:
            log_error(f"[Micromed] Failed to open serial port {port}: {exc}", exc)
            raise

    def send(self, code: int) -> None:
        try:
            self._ser.write(bytes([code]))
            self._ser.flush()
        except Exception as exc:
            log_error(f"[Micromed] TTL send failed (code={code}): {exc}", exc)

    def close(self) -> None:
        try:
            self._ser.close()
        except Exception:
            pass


# ─── Mock trigger (console) ───────────────────────────────────────────────────

class MockTrigger(_BaseTrigger):
    """Prints TTL events to console. Used in mock / laptop-testing mode."""

    def send(self, code: int) -> None:
        print(f"[TTL] code={code}")

    def close(self) -> None:
        pass


# ─── Factory ──────────────────────────────────────────────────────────────────

def make_trigger(mock: bool | None = None, port: str | None = None) -> _BaseTrigger:
    """Return the appropriate trigger based on MOCK_HARDWARE or the *mock* flag."""
    use_mock = mock if mock is not None else config.MOCK_HARDWARE
    if use_mock:
        return MockTrigger()
    return RealTrigger(port=port or "/dev/tty.usbserial-FTXXXXX")
