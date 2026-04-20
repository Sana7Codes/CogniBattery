"""
EyeLink 1000+ interface stubs.

Architecture allows future integration without refactoring callers:
replace MockEyeLink with RealEyeLink in make_eyelink() and all
call sites remain unchanged.
"""

from __future__ import annotations

import config
from core.error_log import log_info, log_warning


class _BaseEyeLink:
    def connect(self) -> None: ...
    def start_recording(self, trial: int) -> None: ...
    def stop_recording(self) -> None: ...
    def send_message(self, msg: str) -> None: ...
    def disconnect(self) -> None: ...


class RealEyeLink(_BaseEyeLink):
    """
    Full EyeLink 1000+ integration via pylink.
    Not yet implemented — raises NotImplementedError to prevent silent failure.
    """

    def connect(self) -> None:
        raise NotImplementedError(
            "RealEyeLink is not yet implemented. Use MockEyeLink for now."
        )

    def start_recording(self, trial: int) -> None:
        raise NotImplementedError

    def stop_recording(self) -> None:
        raise NotImplementedError

    def send_message(self, msg: str) -> None:
        raise NotImplementedError

    def disconnect(self) -> None:
        raise NotImplementedError


class MockEyeLink(_BaseEyeLink):
    """No-op implementation for sessions without an EyeLink."""

    def connect(self) -> None:
        log_info("[EyeLink] MockEyeLink — gaze tracking disabled")

    def start_recording(self, trial: int) -> None:
        pass

    def stop_recording(self) -> None:
        pass

    def send_message(self, msg: str) -> None:
        pass

    def disconnect(self) -> None:
        pass


def make_eyelink(mock: bool | None = None) -> _BaseEyeLink:
    use_mock = mock if mock is not None else config.MOCK_HARDWARE
    if use_mock:
        el = MockEyeLink()
        el.connect()
        return el
    # Future: return RealEyeLink() after implementation
    log_warning("[EyeLink] RealEyeLink not implemented — falling back to MockEyeLink")
    el = MockEyeLink()
    el.connect()
    return el
