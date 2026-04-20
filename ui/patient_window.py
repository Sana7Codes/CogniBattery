"""
Patient window — PsychoPy, screen 1 (or 0 in single-screen mode).

Contains the main trial loop.  Called from run.py after the setup form
returns.  Communicates with the clinician window subprocess via queues.
"""

from __future__ import annotations

import math
import time
from queue import Empty
from pathlib import Path
from typing import Optional

from core.event_log import Event, EventLog, EventType
from core.session import Session
from core.stimulus import Stimulus, StimulusSet
from core.error_log import log_error, log_info, log_warning
from hardware.micromed import TTL_IMAGE_ON


# ── Zone classification helpers ───────────────────────────────────────────────

_TWO_CHOICE   = {"MUF_V1", "MUF_V2", "ASM_MOTS", "ASM_SEEG"}
_THREE_CHOICE = {"FFP_V1", "FFP_V2", "FNP"}
_VERBAL       = {"DI_SEEG"}


def _classify_zone(pos, task_code: str) -> Optional[str]:
    """
    Map a norm-coord mouse position to a hit-zone name, or None if outside zones.
    """
    x, y = pos
    if task_code in _TWO_CHOICE:
        if y < -0.1:
            if x < 0:
                return "left"
            if x > 0:
                return "right"
    elif task_code in _THREE_CHOICE:
        if x < -0.33:
            return "left"
        if x <= 0.33:
            return "center"
        return "right"
    return None


def _keyboard_zone(keys: list[str], task_code: str) -> Optional[str]:
    """Map keyboard fallback keys to zone names."""
    if task_code in _TWO_CHOICE:
        if "q" in keys or "left" in keys:
            return "left"
        if "p" in keys or "right" in keys:
            return "right"
    elif task_code in _THREE_CHOICE:
        if "q" in keys:
            return "left"
        if "w" in keys:
            return "center"
        if "p" in keys:
            return "right"
    return None


def _norm_to_pix(pos_norm, win_size: tuple[int, int]) -> tuple[int, int]:
    """Convert PsychoPy norm coords to pixel coordinates."""
    x_n, y_n = pos_norm
    w, h = win_size
    px_x = int((x_n + 1) / 2 * w)
    px_y = int((1 - (y_n + 1) / 2) * h)
    return px_x, px_y


def _compute_image_size(img_path: str, win_size: tuple[int, int]) -> tuple[float, float]:
    """
    Return (width_norm, height_norm) for displaying the image with
    correct aspect ratio, filling the screen without cropping.
    """
    try:
        from PIL import Image as PILImage
        pil_img = PILImage.open(img_path)
        img_w, img_h = pil_img.size
    except Exception:
        # Fallback: fill screen
        return 2.0, 2.0

    screen_w, screen_h = win_size
    screen_aspect = screen_w / screen_h
    img_aspect    = img_w / img_h

    if img_aspect >= screen_aspect:
        # Fill width, letterbox height
        norm_w = 2.0
        norm_h = 2.0 * screen_aspect / img_aspect
    else:
        # Fill height, pillarbox width
        norm_h = 2.0
        norm_w = 2.0 * img_aspect / screen_aspect

    return norm_w, norm_h


# ── Queue helpers ─────────────────────────────────────────────────────────────

def _send(q, msg: dict) -> None:
    try:
        q.put_nowait(msg)
    except Exception as exc:
        log_warning(f"[IPC] send failed: {exc}")


def _recv(q) -> Optional[dict]:
    try:
        return q.get_nowait()
    except Empty:
        return None


def _drain(q) -> list[dict]:
    """Consume all pending messages from *q* without blocking."""
    msgs = []
    while True:
        msg = _recv(q)
        if msg is None:
            break
        msgs.append(msg)
    return msgs


# ── STIM_START / STIM_END handling ───────────────────────────────────────────

class _StimTracker:
    """Tracks pending STIM_END scheduling."""

    def __init__(self) -> None:
        self._end_at: Optional[float] = None   # session-clock time for STIM_END
        self._duration: float = 0.0

    def arm(self, now: float, duration_s: float) -> None:
        self._end_at = now + duration_s
        self._duration = duration_s

    def check(self, now: float) -> bool:
        """Return True and disarm if STIM_END is due."""
        if self._end_at is not None and now >= self._end_at:
            self._end_at = None
            return True
        return False

    @property
    def armed(self) -> bool:
        return self._end_at is not None


# ── Main trial loop ───────────────────────────────────────────────────────────

def run_session(
    session:       Session,
    stimulus_set:  StimulusSet,
    event_log:     EventLog,
    trigger,                    # RealTrigger | MockTrigger
    task,                       # BaseTask subclass instance
    to_clin_q,                  # multiprocessing.Queue (patient → clinician)
    from_clin_q,                # multiprocessing.Queue (clinician → patient)
    screen:        int  = 1,
    fullscreen:    bool = True,
) -> None:
    """
    Open the PsychoPy patient window and run the full trial loop.
    Blocks until session ends (normal completion or abort).
    """
    from psychopy import visual, event as psy_event, core as psy_core

    # ── Open window ───────────────────────────────────────────────────────────
    win = visual.Window(
        screen=screen,
        fullscr=fullscreen,
        units="norm",
        color=(-1, -1, -1),   # black
        allowGUI=False,
        checkTiming=False,
    )
    win_size = tuple(win.size)

    mouse   = psy_event.Mouse(win=win, visible=False)
    stim_tracker = _StimTracker()
    stim_key_lower = session.stim_key.lower()

    # Announce session start to clinician
    _send(to_clin_q, {
        "type": "session_started",
        "task_display_name": session.task_display_name,
    })
    _send(to_clin_q, {
        "type": "stim_params",
        "electrode":    session.current_stim_params.electrode,
        "contact":      session.current_stim_params.contact,
        "intensity_ma": session.current_stim_params.intensity_ma,
        "duration_s":   session.current_stim_params.duration_s,
    })

    # ── Session counters ──────────────────────────────────────────────────────
    n_correct = 0
    n_total   = 0

    def _send_stats() -> None:
        _send(to_clin_q, {
            "type":       "stats",
            "n_correct":  n_correct,
            "n_total":    n_total,
            "n_skipped":  stimulus_set.n_skipped,
            "n_excluded": stimulus_set.n_excluded,
            "pct_correct": round(n_correct / n_total * 100, 1) if n_total else 0.0,
        })

    # ── Helper: handle STIM_START from F12 key ────────────────────────────────
    def _handle_stim_start() -> None:
        nonlocal stim_tracker
        now_s   = session.now()
        now_iso = session.now_iso()
        p = session.current_stim_params
        notes = p.notes_string(session.stim_key)
        event_log.log(Event(
            time_s=now_s, time_iso=now_iso,
            event=EventType.STIM_START,
            notes=notes,
        ))
        stim_tracker.arm(now_s, p.duration_s)
        _send(to_clin_q, {
            "type":     "stim_event",
            "event":    "STIM_START",
            "duration_s": p.duration_s,
        })
        log_info(f"STIM_START logged: {notes}")

    def _handle_stim_end() -> None:
        event_log.log(Event(
            time_s=session.now(), time_iso=session.now_iso(),
            event=EventType.STIM_END,
            notes="AutoComputed",
        ))
        _send(to_clin_q, {"type": "stim_event", "event": "STIM_END"})

    # ── Helper: build image stimulus ──────────────────────────────────────────
    def _make_image(path: str):
        norm_w, norm_h = _compute_image_size(path, win_size)
        return visual.ImageStim(
            win, image=path, pos=(0, 0),
            size=(norm_w, norm_h), units="norm",
        )

    def _show_fixation(duration_s: float = 0.3) -> None:
        fix = visual.TextStim(win, text="+", color="white",
                               height=0.12, units="norm")
        t0 = session.now()
        while session.now() - t0 < duration_s:
            fix.draw()
            win.flip()
            _check_global_keys(psy_event.getKeys())

    # ── Per-frame global key checker (STIM_START, abort) ─────────────────────
    def _check_global_keys(keys: list[str]) -> Optional[str]:
        """Check F12 for STIM_START and escape for dev abort. Returns 'abort' or None."""
        if stim_key_lower in keys or stim_key_lower.upper() in keys:
            _handle_stim_start()
        return None

    def _check_stim_end(now_s: float) -> None:
        if stim_tracker.check(now_s):
            _handle_stim_end()

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # Main trial loop
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    abort_session = False

    while stimulus_set.has_next() and not abort_session:
        stim = stimulus_set.current()
        if stim is None:
            break

        # ── Pre-trial: drain clinician commands ───────────────────────────────
        for cmd in _drain(from_clin_q):
            t = cmd.get("type", "")
            if t == "abort":
                abort_session = True
                break
            elif t == "skip":
                event_log.log(Event(
                    time_s=session.now(), time_iso=session.now_iso(),
                    event=EventType.STIMULUS_SKIP,
                    essai=n_total + 1,
                    stimulus=stim.planche_id,
                ))
                stimulus_set.skip(stim)
                _send_stats()
                continue
            elif t == "exclude":
                event_log.log(Event(
                    time_s=session.now(), time_iso=session.now_iso(),
                    event=EventType.STIMULUS_EXCLUDE,
                    essai=n_total + 1,
                    stimulus=stim.planche_id,
                    notes="Clinician excluded before trial",
                ))
                stimulus_set.exclude(stim)
                _send_stats()
                continue
            elif t == "update_params":
                session.update_stim_params(
                    cmd.get("electrode", ""),
                    cmd.get("contact", ""),
                    float(cmd.get("intensity_ma", 0)),
                    float(cmd.get("duration_s", 0)),
                )

        if abort_session or not stimulus_set.has_next():
            break

        stim = stimulus_set.current()
        if stim is None:
            break

        n_total += 1
        session.trial_index = n_total

        # ── TRIAL_START ───────────────────────────────────────────────────────
        event_log.log(Event(
            time_s=session.now(), time_iso=session.now_iso(),
            event=EventType.TRIAL_START,
            essai=n_total, stimulus=stim.planche_id,
        ))

        _send(to_clin_q, {
            "type":           "trial_start",
            "trial_n":        n_total,
            "total":          stimulus_set.n_total,
            "stimulus_path":  stim.image_path,
            "correct_answer": str(stim.correct_answer or ""),
            "planche_id":     stim.planche_id,
            "remaining":      [
                {"planche_id": s.planche_id, "path": s.image_path}
                for s in stimulus_set.remaining
            ],
        })

        # ── Show fixation, then image ─────────────────────────────────────────
        _show_fixation(0.3)
        mouse.clickReset()
        psy_event.clearEvents()

        try:
            img_stim = _make_image(stim.image_path)
        except Exception as exc:
            log_error(f"Failed to load image {stim.image_path}: {exc}", exc)
            stimulus_set.advance()
            continue

        img_stim.draw()
        win.flip()
        image_on_ts  = session.now()
        image_on_iso = session.now_iso()

        # ── IMAGE_ON ──────────────────────────────────────────────────────────
        event_log.log(Event(
            time_s=image_on_ts, time_iso=image_on_iso,
            event=EventType.IMAGE_ON,
            essai=n_total, stimulus=stim.planche_id,
        ))
        trigger.send(TTL_IMAGE_ON)
        _send(to_clin_q, {"type": "image_on", "time_s": image_on_ts})

        # ── Response collection loop ──────────────────────────────────────────
        response_zone:  Optional[str] = None
        response_ts:    Optional[float] = None
        response_iso:   Optional[str] = None
        touch_x:        Optional[int] = None
        touch_y:        Optional[int] = None
        is_correct:     Optional[bool] = None
        skip_this:      bool = False
        exclude_this:   bool = False

        while True:
            now_s = session.now()

            # Frame keys
            keys = psy_event.getKeys(keyList=[
                "q", "p", "w", "left", "right",
                stim_key_lower, stim_key_lower.upper(),
                "escape",
            ])
            _check_global_keys(keys)
            _check_stim_end(now_s)

            # Clinician queue
            for cmd in _drain(from_clin_q):
                t = cmd.get("type", "")
                if t == "abort":
                    abort_session = True
                elif t == "skip":
                    skip_this = True
                elif t == "exclude":
                    exclude_this = True
                elif t == "replace":
                    old_pid = stim.planche_id
                    new_pid = cmd.get("planche_id", "")
                    if stimulus_set.replace(stim, new_pid):
                        event_log.log(Event(
                            time_s=session.now(), time_iso=session.now_iso(),
                            event=EventType.STIMULUS_REPLACE,
                            essai=n_total, stimulus=old_pid,
                            notes=f"Replaced: {old_pid} → {new_pid}",
                        ))
                        skip_this = True  # restart this trial slot with new stim
                elif t == "update_params":
                    session.update_stim_params(
                        cmd.get("electrode", ""),
                        cmd.get("contact", ""),
                        float(cmd.get("intensity_ma", 0)),
                        float(cmd.get("duration_s", 0)),
                    )
                elif t == "stim_key":
                    _handle_stim_start()
                elif t == "next_trial" and session.progression_mode == "ClinicianAction":
                    if response_zone is not None:
                        break  # clinician confirmed, advance
                elif t == "di_correct" and stim.task_code == "DI_SEEG":
                    response_zone  = "correct"
                    response_ts    = session.now()
                    response_iso   = session.now_iso()
                    is_correct     = True
                elif t == "di_incorrect" and stim.task_code == "DI_SEEG":
                    response_zone  = "incorrect"
                    response_ts    = session.now()
                    response_iso   = session.now_iso()
                    is_correct     = False

            if abort_session or skip_this or exclude_this:
                break

            # DI_SEEG: wait until clinician marks K/X; no mouse zones
            if stim.task_code not in _VERBAL and response_zone is None:
                # Mouse click?
                if mouse.getPressed()[0]:
                    pos = mouse.getPos()
                    zone = _classify_zone(pos, stim.task_code)
                    if zone is not None:
                        response_zone = zone
                        response_ts   = session.now()
                        response_iso  = session.now_iso()
                        px, py        = _norm_to_pix(pos, win_size)
                        touch_x, touch_y = px, py
                        mouse.clickReset()

                # Keyboard fallback
                if response_zone is None:
                    kz = _keyboard_zone(keys, stim.task_code)
                    if kz:
                        response_zone = kz
                        response_ts   = session.now()
                        response_iso  = session.now_iso()

            # Response obtained — check ProgressionMode
            if response_zone is not None:
                if is_correct is None:
                    is_correct = task.check_correct(response_zone, stim)

                # Log RESPONSE immediately
                tr_s = (response_ts - image_on_ts) if response_ts else None
                event_log.log(Event(
                    time_s=response_ts or session.now(),
                    time_iso=response_iso or session.now_iso(),
                    event=EventType.RESPONSE,
                    essai=n_total,
                    stimulus=stim.planche_id,
                    response=response_zone,
                    correct="Yes" if is_correct is True else ("No" if is_correct is False else None),
                    tr_s=tr_s,
                    touch_x=touch_x,
                    touch_y=touch_y,
                ))

                if is_correct is True:
                    n_correct += 1

                _send(to_clin_q, {
                    "type":       "response",
                    "response":   response_zone,
                    "is_correct": is_correct,
                    "tr_s":       tr_s,
                })
                _send_stats()

                # PatientTouch or DI_SEEG: advance immediately
                if session.progression_mode == "PatientTouch" or stim.task_code in _VERBAL:
                    break
                # Timer: response recorded, wait for timer expiry
                if session.progression_mode == "Timer":
                    response_zone = response_zone  # keep, handled in Timer block below
                    # Fall through to timer wait

            # Timer mode: check if time is up (whether or not response received)
            if session.progression_mode == "Timer":
                elapsed = now_s - image_on_ts
                remaining = session.timer_delay_s - elapsed
                _send(to_clin_q, {
                    "type":        "timer_tick",
                    "elapsed_s":   elapsed,
                    "remaining_s": max(remaining, 0),
                })
                if remaining <= 0:
                    break

            # ClinicianAction: stay on screen until clinician clicks "Essai suivant"
            # (handled via the queue check above — 'next_trial' causes break)

            img_stim.draw()
            win.flip()

        # ── Post-response actions ─────────────────────────────────────────────
        if skip_this:
            event_log.log(Event(
                time_s=session.now(), time_iso=session.now_iso(),
                event=EventType.STIMULUS_SKIP,
                essai=n_total, stimulus=stim.planche_id,
            ))
            stimulus_set.skip(stim)
            n_total -= 1  # skipped trial doesn't count
            _send_stats()
            continue

        if exclude_this:
            event_log.log(Event(
                time_s=session.now(), time_iso=session.now_iso(),
                event=EventType.STIMULUS_EXCLUDE,
                essai=n_total, stimulus=stim.planche_id,
                notes="Clinician excluded during trial",
            ))
            stimulus_set.exclude(stim)
            n_total -= 1
            _send_stats()
            continue

        if abort_session:
            break

        # ── TRIAL_END ─────────────────────────────────────────────────────────
        event_log.log(Event(
            time_s=session.now(), time_iso=session.now_iso(),
            event=EventType.TRIAL_END,
            essai=n_total, stimulus=stim.planche_id,
        ))
        stimulus_set.advance()

        # Brief inter-trial blank
        win.flip()
        t_iti = session.now()
        while session.now() - t_iti < 0.3:
            _check_global_keys(psy_event.getKeys())
            _check_stim_end(session.now())
            win.flip()

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # Session end
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    event_log.log(Event(
        time_s=session.now(), time_iso=session.now_iso(),
        event=EventType.SESSION_END,
        notes=f"n_trials={n_total} n_correct={n_correct} aborted={abort_session}",
    ))

    win.flip()
    psy_core.wait(0.5)
    win.close()

    log_info(f"Session ended. Trials: {n_total}, Correct: {n_correct}")
    return n_total, n_correct
