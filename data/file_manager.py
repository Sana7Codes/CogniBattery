import os
from datetime import date, time


class FileManager:
    """
    Creates and manages output file paths for a session.
    Ensures directories exist before the session starts.
    Refuses to overwrite an existing session file (no data loss by accident).
    """

    def __init__(self, base_dir: str):
        self._base_dir = base_dir

    def get_csv_path(
        self,
        patient_id: str,
        session_date: date,
        test_type: str,
        session_start_time: time = None,
    ) -> str:
        """
        Returns the CSV path for this session.
        Layout: <base_dir>/<patient_id>/<YYYY-MM-DD>_<HHMM>_<test_type>_events.csv

        Including the start time means multiple sessions on the same day never
        collide unless started at the exact same minute.
        Raises FileExistsError if the file already exists, to prevent silent overwrites.
        """
        patient_dir = os.path.join(self._base_dir, patient_id)
        os.makedirs(patient_dir, exist_ok=True)

        time_part = session_start_time.strftime("%H%M") if session_start_time else "0000"
        filename = f"{session_date.isoformat()}_{time_part}_{test_type}_events.csv"
        path = os.path.join(patient_dir, filename)

        if os.path.exists(path):
            raise FileExistsError(
                f"Session file already exists: {path}\n"
                "Use a different test_type or session_date to avoid overwriting data."
            )
        return path

    def ensure_dirs(self, path: str) -> None:
        """Ensure all parent directories for a given file path exist."""
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
