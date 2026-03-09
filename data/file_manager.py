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
        contact: str = "",
        intensity_mA: float = 0.0,
        duration_s: float = 0.0,
    ) -> str:
        """
        Returns the CSV path for this session.

        Layout:
          <base_dir>/<patient_id>/<YYYY-MM-DD>/<test_type>/
            <patient_id>_<YYYY-MM-DD>_<HH-MM>_<test_type>_Contact<contact>_<intensity>mA_<duration>s.csv

        Raises FileExistsError if the file already exists, to prevent silent overwrites.
        """
        time_part = session_start_time.strftime("%H-%M") if session_start_time else "00-00"

        session_dir = os.path.join(
            self._base_dir,
            patient_id,
            session_date.isoformat(),
            test_type,
        )
        os.makedirs(session_dir, exist_ok=True)

        safe_contact = contact.replace("/", "-").replace("\\", "-")
        filename = (
            f"{patient_id}_{session_date.isoformat()}_{time_part}"
            f"_{test_type}_Contact{safe_contact}"
            f"_{intensity_mA}mA_{duration_s}s.csv"
        )
        path = os.path.join(session_dir, filename)

        if os.path.exists(path):
            raise FileExistsError(
                f"Session file already exists: {path}\n"
                "Use a different session time to avoid overwriting data."
            )
        return path

    def ensure_dirs(self, path: str) -> None:
        """Ensure all parent directories for a given file path exist."""
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
