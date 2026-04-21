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
from data.session_writer import write_summary
from hardware.micromed import TTL_IMAGE_ON


# ── Zone classification helpers ───────────────────────────────────────────────

_TWO_CHOICE   = {"MUF_V1", "MUF_V2", "ASM_MOTS", "ASM_SEEG"}
_THREE_CHOICE = {"FFP_V1", "FFP_V2", "FNP"}
_VERBAL       = {"DI_SEEG"}

# Ignore mouse/keyboard responses within this many seconds of IMAGE_ON.
# Prevents phantom clicks carried over from the previous trial response.
_MIN_RESPONSE_GUARD_S = 0.150


def _classify_zone(pos, task_code: str) -> Optional[str]:
    """
    Map a norm-coord mouse position to a hit-zone name, or None if outside zones.
    Returns French zone names: gauche / droite / centre.
    """
    x, y = pos
    if task_code in _TWO_CHOICE:
        if y < -0.1:
            if x < 0:
                return "gauche"
            if x > 0:
                return "droite"
    elif task_code in _THREE_CHOICE:
        if x < -0.33:
            return "gauche"
        if x <= 0.33:
            return "centre"
        return "droite"
    return None


def _keyboard_zone(keys: list[str], task_code: str) -> Optional[str]:
    """Map keyboard fallback keys to zone names (French)."""
    if task_code in _TWO_CHOICE:
        if "q" in keys or "left" in keys:   # "left" = PsychoPy left-arrow key name
            return "gauche"
        if "p" in keys or "right" in keys:  # "right" = PsychoPy right-arrow key name
            return "droite"
    elif task_code in _THREE_CHOICE:
        if "q" in keys:
            return "gauche"
        if "w" in keys:
            return "centre"
        if "p" in keys:
            return "droite"
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
    csv_path:      str  = "",
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

    # Announce session start to clinician (include full stimulus list for Banque tab)
    _send(to_clin_q, {
        "type": "session_started",
        "task_display_name": session.task_display_name,
        "stimuli": [
            {
                "planche_id": s.planche_id,
                "path":       s.image_path,
                "label":      (getattr(s, "stimulus_label", None) or s.planche_id),
            }
            for s in stimulus_set.all_stimuli
        ],
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
            "type":       "stim_event",
            "event":      "STIM_START",
            "duration_s": p.duration_s,
            "time_s":     now_s,
            "time_iso":   now_iso,
        })
        log_info(f"STIM_START logged: {notes}")

    def _handle_stim_end() -> None:
        event_log.log(Event(
            time_s=session.now(), time_iso=session.now_iso(),
            event=EventType.STIM_END,
            notes="AutoComputed",
        ))
        _send(to_clin_q, {
            "type":     "stim_event",
            "event":    "STIM_END",
            "time_s":   session.now(),
            "time_iso": session.now_iso(),
        })

    # ── Helper: build image stimulus ──────────────────────────────────────────
    def _make_image(path: str):
        norm_w, norm_h = _compute_image_size(path, win_size)
        return visual.ImageStim(
            win, image=path, pos=(0, 0),
            size=(norm_w, norm_h), units="norm",
        )

    # ── Per-frame global key checker (STIM_START, abort) ─────────────────────
    def _check_global_keys(keys: list[str]) -> Optional[str]:
        """Check F12 for STIM_START and escape for dev abort. Returns 'abort' or None."""
        if stim_key_lower in keys or stim_key_lower.upper() in keys:
            _handle_stim_start()
        return None

    def _check_stim_end(now_s: float) -> None:
        if stim_tracker.check(now_s):
            _handle_stim_end()

    # ── Pre-load: all stimulus images ────────────────────────────────────────
    _loading_txt = visual.TextStim(win, text="Chargement…", color="white", height=0.08, units="norm")
    _loading_txt.draw()
    win.flip()

    _loaded_images: dict[str, "visual.ImageStim"] = {}
    for _s in stimulus_set.all_stimuli:
        try:
            _nw, _nh = _compute_image_size(_s.image_path, win_size)
            _loaded_images[_s.planche_id] = visual.ImageStim(
                win, image=_s.image_path, pos=(0, 0),
                size=(_nw, _nh), units="norm",
            )
        except Exception as _exc:
            log_warning(f"Pre-load failed for {_s.planche_id}: {_exc}")
    log_info(f"Pre-loaded {len(_loaded_images)}/{len(stimulus_set.all_stimuli)} images")

    # GPU warmup: force one invisible draw of every image so PsychoPy uploads all
    # textures before the first trial, preventing a loading delay on IMAGE_ON.
    for _img in _loaded_images.values():
        _img.opacity = 0
        _img.draw()
    for _img in _loaded_images.values():
        _img.opacity = 1
    _loading_txt.draw()
    win.flip()

    # Notify clinician window to come to front (patient window may have grabbed focus)
    _send(to_clin_q, {"type": "bring_to_front"})

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
            if t in ("abort", "abort_session"):
                abort_session = True
                print(f"[ABORT] patient received {t!r} (pre-trial drain)")
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
            elif t == "annotate":
                ann_text = cmd.get("text", "").strip()
                if ann_text:
                    event_log.log(Event(
                        time_s=session.now(), time_iso=session.now_iso(),
                        event=EventType.NOTE,
                        essai=n_total,
                        notes=ann_text,
                    ))

        if abort_session or not stimulus_set.has_next():
            break

        stim = stimulus_set.current()
        if stim is None:
            break

        n_total += 1
        session.trial_index = n_total

        if n_total > stimulus_set.n_total:
            log_warning(f"n_total overflow {n_total}/{stimulus_set.n_total} — forcing session end")
            n_total = stimulus_set.n_total
            break

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
            "time_s":         session.now(),
            "time_iso":       session.now_iso(),
            "remaining":      [
                {
                    "planche_id": s.planche_id,
                    "path":       s.image_path,
                    "label":      (getattr(s, "stimulus_label", None) or s.planche_id),
                }
                for s in stimulus_set.remaining
            ],
        })

        mouse.clickReset()
        psy_event.clearEvents()

        img_stim = _loaded_images.get(stim.planche_id)
        if img_stim is None:
            log_error(f"Image not pre-loaded for {stim.planche_id}", None)
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
        _send(to_clin_q, {"type": "image_on", "time_s": image_on_ts, "time_iso": image_on_iso})

        # ── Response collection loop ──────────────────────────────────────────
        response_zone:       Optional[str]   = None
        response_ts:         Optional[float] = None
        response_iso:        Optional[str]   = None
        touch_x:             Optional[int]   = None
        touch_y:             Optional[int]   = None
        is_correct:          Optional[bool]  = None
        skip_this:           bool = False
        exclude_this:        bool = False
        response_logged:     bool = False   # guard: log RESPONSE only once per trial
        next_trial_received: bool = False   # ClinicianAction: clinician clicked "Essai suivant"

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
                if t in ("abort", "abort_session"):
                    abort_session = True
                    print(f"[ABORT] patient received {t!r} (mid-trial queue drain)")
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
                        next_trial_received = True   # break AFTER the for-loop
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
                elif t == "annotate":
                    ann_text = cmd.get("text", "").strip()
                    if ann_text:
                        event_log.log(Event(
                            time_s=session.now(), time_iso=session.now_iso(),
                            event=EventType.NOTE,
                            essai=n_total,
                            stimulus=stim.planche_id,
                            notes=ann_text,
                        ))

            if abort_session or skip_this or exclude_this or next_trial_received:
                break

            # DI_SEEG: wait until clinician marks K/X; no mouse zones
            if stim.task_code not in _VERBAL and response_zone is None:
                # Enforce minimum response guard to block phantom clicks from
                # the previous trial's response being carried into this one.
                if now_s - image_on_ts >= _MIN_RESPONSE_GUARD_S:
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

            # Response obtained — log exactly once, then check ProgressionMode
            if response_zone is not None:
                if not response_logged:
                    if is_correct is None:
                        is_correct = task.check_correct(response_zone, stim)
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
                        "time_s":     response_ts or session.now(),
                        "time_iso":   response_iso or session.now_iso(),
                    })
                    _send_stats()
                    response_logged = True

                # PatientTouch or DI_SEEG: advance immediately after first logged response
                if session.progression_mode == "PatientTouch" or stim.task_code in _VERBAL:
                    break
                # Timer/ClinicianAction: keep image on screen, wait for timer or next_trial

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

        _send(to_clin_q, {
            "type":     "trial_end",
            "trial_n":  n_total,
            "time_s":   session.now(),
            "time_iso": session.now_iso(),
        })

        _check_global_keys(psy_event.getKeys())
        _check_stim_end(session.now())

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # Session end
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    print(f"[END] step 1 — outer loop exited (abort={abort_session}, n_total={n_total})")

    session.finalized   = True
    session.was_aborted = abort_session
    print("[END] step 2 — session.finalized = True")

    # ── Session end overlay ───────────────────────────────────────────────────
    _end_msg = "Session interrompue" if abort_session else "Session terminée"
    visual.TextStim(win, text=_end_msg, color="white", height=0.12, units="norm").draw()
    win.flip()

    # ── Log SESSION_END, close, classify epochs ───────────────────────────────
    _end_notes = (
        f"Aborted by clinician | n_trials={n_total} n_correct={n_correct}"
        if abort_session else
        f"n_trials={n_total} n_correct={n_correct}"
    )
    print("[END] step 3 — logging SESSION_END")
    event_log.log(Event(
        time_s=session.now(), time_iso=session.now_iso(),
        event=EventType.SESSION_END,
        notes=_end_notes,
    ))

    print("[END] step 4 — closing event_log (flush to disk)")
    event_log.close()

    print("[END] step 4b — computing stim epochs")
    event_log.finalize_epochs()

    # ── Build shared stats payload ────────────────────────────────────────────
    _resp_evs = [ev for ev in event_log.events if ev.event == EventType.RESPONSE]
    _trs      = [ev.tr_s for ev in _resp_evs if ev.tr_s is not None]
    _mean_tr  = round(sum(_trs) / len(_trs), 3) if _trs else None
    _n_stim   = sum(1 for ev in event_log.events if ev.event == EventType.STIM_START)

    def _ep(label):
        evs = [ev for ev in _resp_evs if ev.stim_epoch == label]
        n   = len(evs)
        ok  = sum(1 for ev in evs if ev.correct == "Yes")
        trs = [ev.tr_s for ev in evs if ev.tr_s is not None]
        return n, ok, (round(sum(trs) / len(trs), 3) if trs else None)

    _n_pre,  _ok_pre,  _mtr_pre  = _ep("pré-stim")
    _n_per,  _ok_per,  _mtr_per  = _ep("per-stim")
    _n_post, _ok_post, _mtr_post = _ep("post-stim")

    _stats_payload = dict(
        csv_path          = csv_path,
        n_total           = n_total,
        n_correct         = n_correct,
        n_skipped         = stimulus_set.n_skipped,
        n_excluded        = stimulus_set.n_excluded,
        mean_tr           = _mean_tr,
        patient_id        = session.patient_id,
        task_display_name = session.task_display_name,
        n_stim_events     = _n_stim,
        n_trials_pre      = _n_pre,  n_correct_pre  = _ok_pre,  mean_TR_pre  = _mtr_pre,
        n_trials_per      = _n_per,  n_correct_per  = _ok_per,  mean_TR_per  = _mtr_per,
        n_trials_post     = _n_post, n_correct_post = _ok_post, mean_TR_post = _mtr_post,
    )

    if abort_session:
        # Abort: save files immediately, show end dialog
        print("[END] step 5 — abort: writing summary + Excel before signalling clinician")
        if csv_path:
            try:
                write_summary(
                    session=session, event_log=event_log,
                    n_trials=n_total, n_correct=n_correct,
                    n_skipped=stimulus_set.n_skipped,
                )
            except Exception as _exc:
                log_error("write_summary failed (abort)", _exc)
            try:
                from data.session_writer import write_excel_report as _write_xl
                _write_xl(
                    session=session, event_log=event_log,
                    n_trials=n_total, n_correct=n_correct,
                    n_skipped=stimulus_set.n_skipped,
                )
            except Exception as _exc:
                log_error("write_excel_report failed (abort)", _exc)
        print("[END] step 6 — sending session_end (abort)")
        _send(to_clin_q, {"type": "session_end", **_stats_payload})
    else:
        # Natural end: no file I/O in PsychoPy thread; run.py handles save after notes
        print("[END] step 6 — sending session_end_pending (natural end)")
        _send(to_clin_q, {"type": "session_end_pending", **_stats_payload})

    print("[END] step 7 — waiting 1.5s then closing PsychoPy window")
    psy_core.wait(1.5)
    win.close()
    print("[END] step 8 — PsychoPy window closed, returning to run.py")

    log_info(f"Session ended. Trials: {n_total}, Correct: {n_correct}")
    return n_total, n_correct
