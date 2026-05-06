"""
Battery — clinical cognitive testing application.
Entry point.

Usage examples:
  python run.py --mock --single-screen --no-fullscreen --task MUF_V1 --patient TEST
  python run.py --no-mock --task FFP_V1 --patient 023
  python run.py --mock --task DI_SEEG --patient TEST
"""

from __future__ import annotations

import argparse
import csv as _csv_mod
import datetime as _dt_mod
import multiprocessing
import sys
import time as _time_mod
from datetime import datetime
from pathlib import Path

# ── Error log must be the very first import after stdlib ─────────────────────
import core.error_log as _err_module
_early_session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
_err_module.init_error_log(_early_session_id)

import config
from core.error_log import log_error, log_info, log_warning
from core.session import Session
from core.stimulus import Stimulus, StimulusSet
from core.event_log import Event, EventType
from data.session_writer import resolve_csv_path, build_metadata, write_summary
from hardware.micromed import make_trigger
from hardware.eyelink import make_eyelink
from tasks.csv_loader import task_folder, TASK_FOLDERS
from tasks.famous_face import FamousFaceTask
from tasks.semantic_matching import SemanticMatchingTask
from tasks.unknown_face import UnknownFaceTask


# ── Task class registry ───────────────────────────────────────────────────────

def _get_task_class(task_code: str):
    pointing   = {"FFP_V1", "FFP_V2", "FNP"}
    matching   = {"MUF_V1", "MUF_V2", "ASM_MOTS", "ASM_SEEG"}
    verbal     = {"DI_SEEG"}
    if task_code in pointing:
        return FamousFaceTask
    if task_code in matching:
        return SemanticMatchingTask
    if task_code in verbal:
        return SemanticMatchingTask
    return SemanticMatchingTask


# ── Argument parsing ──────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Battery — Clinical Cognitive Testing")
    p.add_argument("--mock",          action="store_true", default=True,
                   help="Mock hardware (default ON)")
    p.add_argument("--no-mock",       dest="mock", action="store_false",
                   help="Use real hardware (Micromed TTL)")
    p.add_argument("--single-screen", action="store_true",
                   help="Both windows on screen 0 (laptop testing)")
    p.add_argument("--no-fullscreen", dest="fullscreen", action="store_false",
                   default=True, help="Windowed mode (laptop testing)")
    p.add_argument("--task",    default=None, help="Task code (e.g. MUF_V1)")
    p.add_argument("--patient", default="TEST", help="Patient ID")
    return p.parse_args()


# ── Clinician subprocess launcher ─────────────────────────────────────────────

def _launch_clinician(
    from_patient_q,
    to_patient_q,
    session: Session,
    mock: bool = False,
) -> multiprocessing.Process:
    from ui.clinician_window import run_clinician_process
    p = session.current_stim_params
    proc = multiprocessing.Process(
        target=run_clinician_process,
        args=(
            from_patient_q,
            to_patient_q,
            session.task_code,
            session.task_display_name,
            session.progression_mode,
            session.stim_key,
            p.electrode,
            p.contact,
            p.intensity_ma,
            p.duration_s,
            mock,
        ),
        daemon=True,
        name="ClinicianWindow",
    )
    proc.start()
    return proc


# ── Emergency finalization helper ────────────────────────────────────────────

def _emergency_save(session, event_log, csv_path, stimulus_set,
                    n_total, n_correct, to_clin_q) -> None:
    """Closes the event log, saves files, and notifies the clinician."""
    try:
        event_log.close()
    except Exception as exc:
        log_error("emergency_save: close failed", exc)
    try:
        event_log.finalize_epochs()
    except Exception as exc:
        log_error("emergency_save: finalize_epochs failed", exc)
    try:
        _sp = write_summary(
            session=session, event_log=event_log,
            n_trials=n_total, n_correct=n_correct,
            n_skipped=stimulus_set.n_skipped,
        )
        log_info(f"emergency_save: summary → {_sp}")
    except Exception as exc:
        log_error("emergency_save: write_summary failed", exc)
        _sp = None
    _xp = None
    try:
        from data.session_writer import write_excel_report as _xl
        _xp = _xl(
            session=session, event_log=event_log,
            n_trials=n_total, n_correct=n_correct,
            n_skipped=stimulus_set.n_skipped,
        )
        log_info(f"emergency_save: Excel → {_xp}")
    except Exception as exc:
        log_error("emergency_save: write_excel_report failed", exc)

    _resp_evs = [ev for ev in event_log.events if ev.event == EventType.RESPONSE]
    _trs      = [ev.tr_s for ev in _resp_evs if ev.tr_s is not None]
    _mean_tr  = sum(_trs) / len(_trs) if _trs else None
    _n_stim   = sum(1 for ev in event_log.events if ev.event == EventType.STIM_START)

    def _ep(label):
        evs = [ev for ev in _resp_evs if ev.stim_epoch == label]
        n   = len(evs); ok = sum(1 for ev in evs if ev.correct == "Yes")
        trs = [ev.tr_s for ev in evs if ev.tr_s is not None]
        return n, ok, (round(sum(trs)/len(trs), 3) if trs else None)

    _n_pre,  _ok_pre,  _mtr_pre  = _ep("pré-stim")
    _n_per,  _ok_per,  _mtr_per  = _ep("per-stim")
    _n_lim,  _ok_lim,  _mtr_lim  = _ep("limite-stim")
    _n_post, _ok_post, _mtr_post = _ep("post-stim")

    try:
        to_clin_q.put_nowait({
            "type":             "session_end",
            "csv_path":         str(csv_path),
            "n_total":          n_total,
            "n_correct":        n_correct,
            "n_skipped":        stimulus_set.n_skipped,
            "n_excluded":       getattr(stimulus_set, "n_excluded", 0),
            "mean_tr":          round(_mean_tr, 3) if _mean_tr is not None else None,
            "patient_id":       session.patient_id,
            "task_display_name": session.task_display_name,
            "n_stim_events":    _n_stim,
            "n_trials_pre":     _n_pre,  "n_correct_pre":    _ok_pre,  "mean_TR_pre":    _mtr_pre,
            "n_trials_per":     _n_per,  "n_correct_per":    _ok_per,  "mean_TR_per":    _mtr_per,
            "n_trials_limite":  _n_lim,  "n_correct_limite": _ok_lim,  "mean_TR_limite": _mtr_lim,
            "n_trials_post":    _n_post, "n_correct_post":   _ok_post, "mean_TR_post":   _mtr_post,
        })
    except Exception as exc:
        log_error("emergency_save: notify clinician failed", exc)


# ── Single-session runner ─────────────────────────────────────────────────────

def _run_one_session(cfg: dict, args, trigger, eyelink) -> dict:
    """
    Run one complete session.
    Hardware (trigger, eyelink) are reused from the caller and NOT closed here.
    Returns a dict with session info for the next setup form banner.
    """
    # ── Build Session ─────────────────────────────────────────────────────────
    session = Session(
        patient_id        = cfg["patient_id"],
        task_code         = cfg["task_code"],
        task_display_name = cfg["task_display_name"],
        electrode         = cfg["electrode"],
        contact           = cfg["contact"],
        intensity_ma      = cfg["intensity_ma"],
        duration_s        = cfg["duration_s"],
        progression_mode  = cfg["progression_mode"],
        timer_delay_s     = cfg["timer_delay_s"],
        stim_key          = cfg["stim_key"],
        stimuli_order     = cfg["order"],
    )

    selected_stimuli: list[Stimulus] = cfg["selected_stimuli"]
    stimulus_set = StimulusSet(selected_stimuli, order=cfg["order"])

    task_class = _get_task_class(cfg["task_code"])
    task = task_class(session, stimulus_set)
    cb_notes = task.counterbalance_notes
    log_info(f"Counterbalance: {cb_notes}")

    session.start()
    csv_path = resolve_csv_path(session)

    metadata = build_metadata(session, stimulus_set, cb_notes)
    if cfg.get("excluded_ids"):
        metadata["StimuliExcluded"] += (
            " | PreCheck:" + " ".join(cfg["excluded_ids"])
        )

    if config.MOCK_HARDWARE:
        from core.event_log import MockEventLog
        event_log = MockEventLog(metadata, csv_path)
    else:
        from core.event_log import EventLog
        event_log = EventLog(metadata, csv_path)

    p = session.current_stim_params
    event_log.log(Event(
        time_s   = session.now(),
        time_iso = session.now_iso(),
        event    = EventType.SESSION_START,
        notes    = (
            f"SessionID={session.session_id} "
            f"PatientID={session.patient_id} "
            f"Task={session.task_code} "
            f"Electrode={p.electrode} Contact={p.contact} "
            f"Intensity={p.intensity_ma}mA Duration={p.duration_s}s "
            f"Mode={session.progression_mode} "
            f"Version={config.SOFTWARE_VERSION}"
        ),
    ))

    # ── Launch clinician window subprocess ────────────────────────────────────
    to_clin_q   = multiprocessing.Queue()
    from_clin_q = multiprocessing.Queue()
    clin_proc = _launch_clinician(to_clin_q, from_clin_q, session, mock=args.mock)

    patient_screen = 0 if args.single_screen else config.PATIENT_SCREEN
    use_fullscreen = args.fullscreen

    n_total, n_correct = 0, 0
    try:
        from ui.patient_window import run_session
        result = run_session(
            session      = session,
            stimulus_set = stimulus_set,
            event_log    = event_log,
            trigger      = trigger,
            task         = task,
            to_clin_q    = to_clin_q,
            from_clin_q  = from_clin_q,
            screen       = patient_screen,
            fullscreen   = use_fullscreen,
            csv_path     = str(csv_path),
        )
        n_total, n_correct = result if result else (0, 0)

    except Exception as exc:
        log_error("Unhandled exception in trial loop", exc)
        n_total, n_correct = 0, 0
    finally:
        # ── Finalization ───────────────────────────────────────────────────────
        if not getattr(session, "finalized", False):
            print("[END] safety-net — patient_window crashed, emergency finalization")
            _emergency_save(
                session, event_log, csv_path, stimulus_set,
                n_total, n_correct, to_clin_q,
            )

        elif getattr(session, "was_aborted", False):
            print("[END] session was aborted — finalization done in patient_window")

        else:
            print("[END] natural end — waiting for clinician finalize decision (up to 2 min)")
            _msg = None
            _deadline = _time_mod.monotonic() + 120
            while _time_mod.monotonic() < _deadline:
                try:
                    _msg = from_clin_q.get(timeout=2.0)
                    if _msg.get("type") in ("finalize_save", "finalize_abandon"):
                        break
                    _msg = None
                except Exception:
                    pass

            if _msg and _msg.get("type") == "finalize_save":
                # Files already written in patient_window — only append optional notes.
                notes = _msg.get("notes", "").strip()
                if notes and Path(csv_path).exists():
                    try:
                        _now = _dt_mod.datetime.now()
                        with open(csv_path, "a", newline="", encoding="utf-8") as _fh:
                            _w = _csv_mod.writer(_fh)
                            _w.writerow([
                                round(session.now(), 6),
                                _now.isoformat(timespec="microseconds"),
                                "SESSION_NOTES",
                                "", "", "", "", "", "", "", "", notes,
                            ])
                        log_info("SESSION_NOTES appended to CSV")
                    except Exception as exc:
                        log_error("Error appending notes to CSV", exc)

                to_clin_q.put_nowait({"type": "session_saved", "csv_path": str(csv_path)})
                log_info("session_saved sent to clinician")

            elif _msg and _msg.get("type") == "finalize_abandon":
                try:
                    Path(csv_path).unlink(missing_ok=True)
                    log_info(f"CSV deleted on abandon: {csv_path}")
                except Exception as exc:
                    log_error("Error deleting CSV on abandon", exc)
                log_info("Session abandoned by clinician")
                to_clin_q.put_nowait({"type": "session_abandoned"})

            else:
                log_warning(
                    "Clinician finalize dialog timed out after 120s — "
                    "session data already saved, exiting cleanly"
                )
                try:
                    to_clin_q.put_nowait({"type": "session_abandoned"})
                except Exception as _exc:
                    log_error("timeout: session_abandoned notify failed", _exc)

        clin_proc.join(timeout=10)
        if clin_proc.is_alive():
            clin_proc.terminate()
            clin_proc.join()

        # Check if the clinician clicked "Quitter" in the results dialog.
        # The quit_app message arrives in from_clin_q after the subprocess exits.
        _action = "new_session"
        try:
            import queue as _q_mod
            while True:
                _m = from_clin_q.get_nowait()
                if _m.get("type") == "quit_app":
                    _action = "quit"
                    break
        except Exception:
            pass

        for _q in (to_clin_q, from_clin_q):
            try:
                _q.cancel_join_thread()
                _q.close()
            except Exception:
                pass

    p = session.current_stim_params
    return {
        "action":            _action,
        "patient_id":        session.patient_id,
        "task":              session.task_code,
        "task_display_name": session.task_display_name,
        "electrode":         p.electrode,
        "contact":           p.contact,
        "intensity_ma":      p.intensity_ma,
        "duration_s":        p.duration_s,
        "n_trials":          n_total,
        "n_correct":         n_correct,
        "filename_stem":     Path(csv_path).stem,
        "csv_path":          str(csv_path),
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    args = parse_args()
    config.MOCK_HARDWARE = args.mock

    log_info(
        f"Battery starting. mock={args.mock} single_screen={args.single_screen} "
        f"fullscreen={args.fullscreen} task={args.task} patient={args.patient}"
    )

    # CLI presets applied only to the first session
    cli_presets: dict = {}
    if args.task:
        cli_presets["task_code"] = args.task
    if args.patient:
        cli_presets["patient_id"] = args.patient

    # Hardware created once and kept alive across all sessions
    trigger = make_trigger(mock=args.mock)
    eyelink = make_eyelink(mock=args.mock)

    prev_session_info: dict | None = None

    try:
        while True:
            # Build form presets: start from CLI args, overlay previous-session
            # hardware params (but not task_code — clinician picks a new task).
            presets = dict(cli_presets)
            if prev_session_info is not None:
                presets.setdefault("patient_id", prev_session_info["patient_id"])
                presets["electrode"] = prev_session_info["electrode"]
                presets["contact"]   = prev_session_info["contact"]
                presets["intensity"] = str(prev_session_info["intensity_ma"])
                presets["duration"]  = str(prev_session_info["duration_s"])
                presets.pop("task_code", None)

            from ui.setup_form import SetupForm
            form = SetupForm(presets=presets, prev_session_info=prev_session_info)
            cfg  = form.run()

            if cfg is None:
                log_info("Setup form: clinician quit — exiting.")
                break

            log_info(f"Setup complete: {cfg['patient_id']} / {cfg['task_code']}")

            try:
                prev_session_info = _run_one_session(cfg, args, trigger, eyelink)
            except Exception as exc:
                log_error("Session crashed — returning to setup form", exc)
                prev_session_info = None  # no banner for crash

            if prev_session_info and prev_session_info.get("action") == "quit":
                log_info("Clinician chose Quitter — exiting.")
                break

            # Clear the one-time CLI task preset after the first session
            cli_presets.pop("task_code", None)

    finally:
        try:
            trigger.close()
            eyelink.disconnect()
        except Exception:
            pass

    log_info("Battery exiting.")


if __name__ == "__main__":
    multiprocessing.set_start_method("spawn", force=True)
    main()
