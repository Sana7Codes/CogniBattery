import csv

from core.event_log import CSV_COLUMNS, Event


class CSVExporter:
    """
    Optional utility: rebuilds or validates a CSV from an in-memory event list.

    In MVP, events are written incrementally by PersistentEventLog (disk is the
    source of truth). This class is useful for post-hoc validation, format
    conversion, or generating a clean export from the in-memory cache.
    """

    @staticmethod
    def export(events: list, output_path: str) -> None:
        """Write a list of Event objects to a CSV file (overwrites if exists)."""
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(CSV_COLUMNS)
            for event in events:
                writer.writerow([
                    round(event.time_s, 6),
                    event.time_iso,
                    event.event.value,
                    event.essai,
                    event.stimulus,
                    event.response,
                    event.correct,
                    round(event.tr_s, 6) if event.tr_s is not None else None,
                    event.touch_x,
                    event.touch_y,
                    event.notes,
                ])
