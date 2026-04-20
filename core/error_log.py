"""
Global error logging for the Battery application.

Initialise once at startup via init_error_log(session_id).
All unhandled exceptions and explicit log_error() calls are written to
  logs/error_{session_id}.log
The log file is opened immediately and survives application crashes.
"""

import logging
import sys
import traceback
from pathlib import Path

_logger: logging.Logger | None = None


def init_error_log(session_id: str) -> None:
    """
    Create the error log file and install the global exception hook.
    Must be called before any other application code runs.
    """
    global _logger

    logs_dir = Path("logs")
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"error_{session_id}.log"

    _logger = logging.getLogger("battery")
    _logger.setLevel(logging.DEBUG)

    fh = logging.FileHandler(str(log_path), encoding="utf-8", delay=False)
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s  %(levelname)-8s  %(name)s\n%(message)s\n",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )
    _logger.addHandler(fh)

    # Also echo errors to stderr so the operator can see them immediately
    sh = logging.StreamHandler(sys.stderr)
    sh.setLevel(logging.ERROR)
    sh.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    _logger.addHandler(sh)

    def _excepthook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        _logger.critical(
            "Unhandled exception — session may be incomplete",
            exc_info=(exc_type, exc_value, exc_tb),
        )

    sys.excepthook = _excepthook
    _logger.info("Error log initialised. Session: %s", session_id)


def log_error(message: str, exc: BaseException | None = None) -> None:
    """Log a runtime error with optional exception traceback."""
    if _logger is None:
        # Fallback if init was not called
        print(f"[ERROR before init] {message}", file=sys.stderr)
        if exc:
            traceback.print_exc()
        return
    if exc:
        _logger.error(message, exc_info=exc)
    else:
        _logger.error(message)


def log_warning(message: str) -> None:
    """Log a non-fatal warning."""
    if _logger is None:
        print(f"[WARN] {message}", file=sys.stderr)
        return
    _logger.warning(message)


def log_info(message: str) -> None:
    """Log an informational message."""
    if _logger is None:
        print(f"[INFO] {message}")
        return
    _logger.info(message)
