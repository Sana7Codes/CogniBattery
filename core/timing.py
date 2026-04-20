import time
from datetime import datetime


class Clock:
    """Single source of truth for all timestamps in a session."""

    def __init__(self):
        self.session_start_time: float = 0.0
        self.wall_start_time: datetime = datetime.now()

    def start(self) -> None:
        self.session_start_time = time.perf_counter()
        self.wall_start_time = datetime.now()

    def now_relative(self) -> float:
        """Seconds since session start (Time_s)."""
        return time.perf_counter() - self.session_start_time

    def now_iso(self) -> str:
        """ISO 8601 absolute timestamp (Time_iso)."""
        return datetime.now().isoformat()
