"""
Clinician window — tkinter, runs in a separate subprocess during the session.

Receives state updates from the patient process via *from_patient_q* and sends
clinician commands back via *to_patient_q*.

Message protocol
────────────────
Patient → Clinician  (from_patient_q):
  {'type': 'session_started', 'task_display_name': str,
           'stimuli': [{'planche_id': str, 'path': str, 'label': str}]}
  {'type': 'trial_start', 'trial_n': int, 'total': int,
           'stimulus_path': str, 'correct_answer': str,
           'planche_id': str, 'time_s': float, 'time_iso': str,
           'remaining': [{'planche_id', 'path'}]}
  {'type': 'image_on',   'time_s': float, 'time_iso': str}
  {'type': 'response',   'response': str, 'is_correct': bool|None,
           'tr_s': float, 'time_s': float, 'time_iso': str}
  {'type': 'trial_end',  'trial_n': int, 'time_s': float, 'time_iso': str}
  {'type': 'stim_event', 'event': 'STIM_START'|'STIM_END',
           'duration_s': float, 'time_s': float, 'time_iso': str}
  {'type': 'stats',      'n_correct': int, 'n_total': int, 'n_skipped': int,
                          'n_excluded': int, 'pct_correct': float}
  {'type': 'timer_tick', 'elapsed_s': float, 'remaining_s': float}
  {'type': 'session_end', 'csv_path': str, 'n_total': int, 'n_correct': int,
           'n_skipped': int, 'n_excluded': int, 'mean_tr': float|None}
  {'type': 'error',      'message': str}

Clinician → Patient  (to_patient_q):
  {'type': 'skip'}
  {'type': 'exclude'}
  {'type': 'replace',        'planche_id': str}
  {'type': 'update_params',  'electrode': str, 'contact': str,
                              'intensity_ma': float, 'duration_s': float}
  {'type': 'next_trial'}
  {'type': 'abort'}
  {'type': 'stim_key'}        # F12 pressed by clinician
  {'type': 'di_correct'}      # K pressed (DI_SEEG correct)
  {'type': 'di_incorrect'}    # X pressed (DI_SEEG incorrect)
  {'type': 'annotate',       'text': str}
"""

from __future__ import annotations

import csv
import datetime
import os
import platform
import subprocess
import time
import tkinter as tk
from pathlib import Path
from queue import Empty
from tkinter import ttk, messagebox, filedialog
from typing import Optional


# ─── Colour palette ───────────────────────────────────────────────────────────

BG       = "#1a1a2e"
BG2      = "#16213e"
BG3      = "#0f3460"
FG       = "#e0e0e0"
FG_DIM   = "#888888"
GREEN    = "#00cc44"
RED      = "#cc3300"
ORANGE   = "#cc7700"
STIM_ON  = "#cc0000"
STIM_OFF = "#334455"


# ─── Clinician application ────────────────────────────────────────────────────

class ClinicianApp:
    POLL_MS = 50  # queue poll interval in milliseconds

    def __init__(
        self,
        from_patient_q,   # multiprocessing.Queue: patient → clinician
        to_patient_q,     # multiprocessing.Queue: clinician → patient
        task_code: str,
        task_display_name: str,
        progression_mode: str,
        stim_key: str = "f12",
        mock: bool = False,
    ) -> None:
        self._from_q = from_patient_q
        self._to_q   = to_patient_q
        self._task_code       = task_code
        self._task_display    = task_display_name
        self._prog_mode       = progression_mode
        self._stim_key        = stim_key.lower()
        self._mock            = mock

        # Session state
        self._trial_n          = 0
        self._total_trials     = 0
        self._stim_path        = ""
        self._current_pid      = ""
        self._correct_answer   = ""
        self._last_response    = ""
        self._last_correct     = None      # bool | None
        self._image_on_ts      = None      # float | None (monotonic)
        self._stim_on          = False
        self._stim_start_ts    = None      # float | None (monotonic, for countdown)
        self._stim_duration    = 0.0
        self._elapsed_s        = 0.0
        self._remaining_s      = None      # float | None (Timer mode)
        self._n_correct        = 0
        self._n_total          = 0
        self._n_skipped        = 0
        self._n_excluded       = 0
        self._tr_values: list[float] = []  # for TR moyen (item 6)
        self._remaining_stimuli: list[dict] = []
        self._session_ended: bool = False
        self._session_active: bool = True

        # Banque de stimuli (item 11-12)
        self._all_stimuli: list[dict] = []   # {planche_id, path, label}
        self._presented_pids: set[str] = set()

        # Historique (item 13-15)
        self._history_events: list[dict] = []

        self._root = tk.Tk()

        # Stim params (editable mid-session)
        self._electrode   = tk.StringVar()
        self._contact     = tk.StringVar()
        self._intensity   = tk.StringVar()
        self._duration    = tk.StringVar()

        # UI state
        self._params_collapsed = False
        self._build_ui()
        self._bind_keys()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = self._root
        root.title("Battery — Opérateur")
        root.configure(bg=BG)
        root.geometry("1000x720")

        # ── Top bar: task name ────────────────────────────────────────────────
        top = tk.Frame(root, bg=BG2, pady=6)
        top.pack(fill="x")

        self._task_lbl = tk.Label(
            top, text=self._task_display,
            font=("Helvetica", 16, "bold"),
            fg=FG, bg=BG2,
        )
        self._task_lbl.pack(side="left", padx=16)

        # Item 5: Full-width STIM banner ──────────────────────────────────────
        self._stim_banner = tk.Label(
            root,
            text="  STIMULATION OFF  ",
            font=("Helvetica", 13, "bold"),
            fg=FG_DIM, bg=STIM_OFF,
            anchor="center",
            pady=6,
        )
        self._stim_banner.pack(fill="x")

        # ── Notebook tabs ─────────────────────────────────────────────────────
        nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=True, padx=6, pady=4)

        tab_session = ttk.Frame(nb)
        tab_banque  = ttk.Frame(nb)
        tab_hist    = ttk.Frame(nb)
        nb.add(tab_session, text="Session en cours")
        nb.add(tab_banque,  text="Banque de stimuli")
        nb.add(tab_hist,    text="Historique")

        self._build_session_tab(tab_session)
        self._build_banque_tab(tab_banque)
        self._build_historique_tab(tab_hist)

        # ── Bottom controls (always visible) ──────────────────────────────────
        ctrl = tk.Frame(root, bg=BG2, pady=4)
        ctrl.pack(fill="x", padx=6)

        btn_cfg = dict(pady=5, padx=2)

        self._skip_btn = tk.Button(
            ctrl, text="Passer (Skip)", command=self._cmd_skip,
            bg="#444455", fg=FG, width=15, **btn_cfg,
        )
        self._skip_btn.grid(row=0, column=0, padx=5)

        self._excl_btn = tk.Button(
            ctrl, text="Exclure", command=self._cmd_exclude,
            bg="#884400", fg=FG, width=12, **btn_cfg,
        )
        self._excl_btn.grid(row=0, column=1, padx=5)

        self._repl_btn = tk.Button(
            ctrl, text="Remplacer…", command=self._cmd_replace,
            bg="#003366", fg=FG, width=12, **btn_cfg,
        )
        self._repl_btn.grid(row=0, column=2, padx=5)

        self._abort_btn = tk.Button(
            ctrl, text="Arrêter session", command=self._cmd_abort,
            bg="#770000", fg=FG, width=15, **btn_cfg,
        )
        self._abort_btn.grid(row=0, column=3, padx=5)

        self._next_btn = tk.Button(
            ctrl, text="Essai suivant ▶", command=self._cmd_next_trial,
            bg="#005500", fg=FG, width=15, **btn_cfg,
            state="disabled",
        )
        self._next_btn.grid(row=0, column=4, padx=5)
        if self._prog_mode == "ClinicianAction":
            self._next_btn.config(state="normal")

        if self._mock:
            self._mock_stim_btn = tk.Button(
                ctrl, text="Test STIM (F12)", command=self._cmd_stim_key,
                bg="#663300", fg=FG, width=15, **btn_cfg,
            )
            self._mock_stim_btn.grid(row=0, column=5, padx=5)

    # ── Session tab ───────────────────────────────────────────────────────────

    def _build_session_tab(self, parent: ttk.Frame) -> None:
        main = tk.Frame(parent, bg=BG)
        main.pack(fill="both", expand=True, padx=6, pady=4)

        # Left: image mirror
        img_frame = tk.LabelFrame(main, text="Stimulus actuel", bg=BG, fg=FG, font=("Helvetica", 10))
        img_frame.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)

        self._img_label = tk.Label(img_frame, bg="black")
        self._img_label.pack(padx=4, pady=4)
        self._mirror_img = None  # prevent GC

        # Right: info panels
        info = tk.Frame(main, bg=BG)
        info.grid(row=0, column=1, sticky="nsew", padx=4, pady=4)
        main.columnconfigure(0, weight=3)
        main.columnconfigure(1, weight=2)

        # ── Trial panel ───────────────────────────────────────────────────────
        trial_frame = tk.LabelFrame(info, text="Essai en cours", bg=BG, fg=FG, font=("Helvetica", 10))
        trial_frame.pack(fill="x", pady=(0, 4))

        self._trial_lbl = tk.Label(
            trial_frame, text="—",
            fg=FG, bg=BG, font=("Helvetica", 13, "bold"),
        )
        self._trial_lbl.pack(anchor="w", padx=8, pady=(4, 0))

        # Item 8: Réponse attendue prominently shown
        self._correct_lbl = tk.Label(
            trial_frame, text="Réponse attendue: —",
            fg="#aaddff", bg=BG, font=("Helvetica", 10),
        )
        self._correct_lbl.pack(anchor="w", padx=8)

        self._resp_lbl = tk.Label(
            trial_frame, text="Réponse patient: —",
            fg=FG, bg=BG, font=("Helvetica", 12, "bold"),
        )
        self._resp_lbl.pack(anchor="w", padx=8)

        self._timer_lbl = tk.Label(trial_frame, text="", fg=FG_DIM, bg=BG)
        self._timer_lbl.pack(anchor="w", padx=8, pady=(0, 4))

        # ── Item 6: Stats with TR moyen ───────────────────────────────────────
        stats_frame = tk.LabelFrame(info, text="Statistiques", bg=BG, fg=FG, font=("Helvetica", 10))
        stats_frame.pack(fill="x", pady=4)

        self._stats_lbl = tk.Label(stats_frame, text="—", fg=FG, bg=BG)
        self._stats_lbl.pack(anchor="w", padx=8, pady=4)

        # ── Item 9: Collapsible stim params ───────────────────────────────────
        self._params_toggle_btn = tk.Button(
            info,
            text="▼ Paramètres de stimulation",
            command=self._toggle_params,
            bg=BG2, fg=FG_DIM,
            relief="flat", anchor="w",
            font=("Helvetica", 9),
        )
        self._params_toggle_btn.pack(fill="x", pady=(4, 0))

        self._params_frame = tk.LabelFrame(info, text="", bg=BG, fg=FG)
        self._params_frame.pack(fill="x", pady=(0, 4))

        for i, (lbl, var) in enumerate([
            ("Électrode",      self._electrode),
            ("Contact",        self._contact),
            ("Intensité (mA)", self._intensity),
            ("Durée (s)",      self._duration),
        ]):
            tk.Label(self._params_frame, text=lbl, fg=FG, bg=BG).grid(
                row=i, column=0, sticky="w", padx=8, pady=2,
            )
            tk.Entry(self._params_frame, textvariable=var, width=10,
                     bg="#222233", fg=FG, insertbackground=FG).grid(
                row=i, column=1, sticky="w", padx=4,
            )

        ttk.Button(
            self._params_frame, text="Mettre à jour",
            command=self._send_update_params,
        ).grid(row=4, column=0, columnspan=2, pady=4)

        # ── Item 10: Annotation field ─────────────────────────────────────────
        annot_frame = tk.LabelFrame(info, text="Annotation clinicien", bg=BG, fg=FG, font=("Helvetica", 10))
        annot_frame.pack(fill="x", pady=4)

        annot_inner = tk.Frame(annot_frame, bg=BG)
        annot_inner.pack(fill="x", padx=4, pady=4)

        self._annot_entry = tk.Entry(
            annot_inner, width=22,
            bg="#222233", fg=FG, insertbackground=FG,
        )
        self._annot_entry.pack(side="left", padx=(0, 4))
        self._annot_entry.bind("<Return>", lambda _: self._cmd_annotate())

        tk.Button(
            annot_inner, text="Ajouter →",
            command=self._cmd_annotate,
            bg="#334466", fg=FG,
        ).pack(side="left")

    # ── Banque de stimuli tab (items 11-12) ───────────────────────────────────

    def _build_banque_tab(self, parent: ttk.Frame) -> None:
        # Filter row
        filter_row = tk.Frame(parent, bg=BG)
        filter_row.pack(fill="x", padx=6, pady=4)

        tk.Label(filter_row, text="Afficher:", fg=FG, bg=BG).pack(side="left")
        self._banque_filter = tk.StringVar(value="Tous")
        filter_cb = ttk.Combobox(
            filter_row, textvariable=self._banque_filter,
            values=["Tous", "Restants", "Présentés"],
            width=12, state="readonly",
        )
        filter_cb.pack(side="left", padx=6)
        filter_cb.bind("<<ComboboxSelected>>", lambda _: self._refresh_banque())

        # Main area
        main = tk.Frame(parent, bg=BG)
        main.pack(fill="both", expand=True, padx=6, pady=4)

        # Listbox
        lb_frame = tk.Frame(main, bg=BG)
        lb_frame.pack(side="left", fill="y")

        tk.Label(lb_frame, text="Stimuli", fg=FG_DIM, bg=BG,
                 font=("Helvetica", 9)).pack(anchor="w")

        sb = tk.Scrollbar(lb_frame)
        sb.pack(side="right", fill="y")

        self._banque_lb = tk.Listbox(
            lb_frame, width=32, height=24,
            bg="#222233", fg=FG,
            selectbackground="#334488",
            yscrollcommand=sb.set,
        )
        self._banque_lb.pack(side="left", fill="y")
        sb.config(command=self._banque_lb.yview)
        self._banque_lb.bind("<<ListboxSelect>>", self._on_banque_select)

        # Image preview
        preview = tk.Frame(main, bg=BG)
        preview.pack(side="left", fill="both", expand=True, padx=8)

        self._banque_img_label = tk.Label(preview, bg="black", width=36, height=20)
        self._banque_img_label.pack(pady=4)
        self._banque_img_tk = None

        self._banque_name_lbl = tk.Label(
            preview, text="", fg=FG, bg=BG,
            font=("Helvetica", 11, "bold"), wraplength=280,
        )
        self._banque_name_lbl.pack(pady=2)

        self._banque_status_lbl = tk.Label(
            preview, text="", fg=FG_DIM, bg=BG,
            font=("Helvetica", 9),
        )
        self._banque_status_lbl.pack()

    # ── Historique tab (items 13-15) ──────────────────────────────────────────

    def _build_historique_tab(self, parent: ttk.Frame) -> None:
        # Treeview for event log
        tree_frame = tk.Frame(parent, bg=BG)
        tree_frame.pack(fill="both", expand=True, padx=6, pady=(6, 2))

        cols = ("time_s", "time_iso", "event", "details")
        self._hist_tree = ttk.Treeview(
            tree_frame, columns=cols, show="headings", height=16,
        )
        self._hist_tree.heading("time_s",   text="Time_s")
        self._hist_tree.heading("time_iso", text="Time_iso")
        self._hist_tree.heading("event",    text="Événement")
        self._hist_tree.heading("details",  text="Détails")

        self._hist_tree.column("time_s",   width=75,  stretch=False)
        self._hist_tree.column("time_iso", width=155, stretch=False)
        self._hist_tree.column("event",    width=130, stretch=False)
        self._hist_tree.column("details",  width=380, stretch=True)

        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self._hist_tree.yview)
        self._hist_tree.configure(yscrollcommand=vsb.set)
        self._hist_tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        # Summary card
        self._hist_summary_lbl = tk.Label(
            parent, text="", fg=FG, bg=BG,
            font=("Helvetica", 10), justify="left", anchor="w",
        )
        self._hist_summary_lbl.pack(fill="x", padx=8, pady=4)

        # Item 15: Export button
        ttk.Button(
            parent, text="Exporter CSV",
            command=self._export_historique,
        ).pack(pady=4)

    # ── Key bindings ──────────────────────────────────────────────────────────

    def _bind_keys(self) -> None:
        # tkinter function-key keysyms must be uppercase: <F12> not <f12>.
        # For letter keys (e.g. stim_key="s") both cases are bound.
        upper_seq = f"<{self._stim_key.upper()}>"
        try:
            self._root.bind(upper_seq, lambda e: self._cmd_stim_key())
        except tk.TclError:
            pass
        if len(self._stim_key) == 1:  # single letter — also bind lowercase
            try:
                self._root.bind(f"<{self._stim_key}>", lambda e: self._cmd_stim_key())
            except tk.TclError:
                pass
        self._root.bind("<k>",     lambda e: self._cmd_di_correct())
        self._root.bind("<K>",     lambda e: self._cmd_di_correct())
        self._root.bind("<x>",     lambda e: self._cmd_di_incorrect())
        self._root.bind("<X>",     lambda e: self._cmd_di_incorrect())
        self._root.bind("<Return>", lambda e: self._cmd_next_trial())
        self._root.protocol("WM_DELETE_WINDOW", self._cmd_abort)

    # ── Queue polling ─────────────────────────────────────────────────────────

    def _poll(self) -> None:
        try:
            while True:
                msg = self._from_q.get_nowait()
                self._handle_message(msg)
        except Empty:
            pass
        finally:
            if not self._session_ended:
                self._root.after(self.POLL_MS, self._poll)

        # Live elapsed timer
        if self._image_on_ts is not None and not self._session_ended:
            self._elapsed_s = time.monotonic() - self._image_on_ts
            self._update_timer_display()

        # Item 5: STIM banner countdown
        self._update_stim_banner()

    def _handle_message(self, msg: dict) -> None:
        t = msg.get("type", "")

        if t == "session_started":
            self._task_lbl.config(text=msg.get("task_display_name", self._task_display))
            self._all_stimuli = msg.get("stimuli", [])
            self._refresh_banque()
            self._root.lift()
            self._root.attributes("-topmost", True)
            for _ms in (200, 600):
                self._root.after(_ms, lambda: self._root.lift())

        elif t == "bring_to_front":
            self._root.lift()
            self._root.attributes("-topmost", True)
            for _ms in (300, 800, 1500):
                self._root.after(_ms, lambda: self._root.lift())

        elif t == "trial_start":
            # Mark previous as presented
            if self._current_pid:
                self._presented_pids.add(self._current_pid)

            self._trial_n          = msg["trial_n"]
            self._total_trials     = msg["total"]
            self._stim_path        = msg["stimulus_path"]
            self._current_pid      = msg["planche_id"]
            self._correct_answer   = msg.get("correct_answer", "")
            self._last_response    = "—"
            self._last_correct     = None
            self._image_on_ts      = None
            self._remaining_stimuli = msg.get("remaining", [])

            self._update_trial_display()
            self._update_image()
            self._refresh_banque()
            self._add_history_event(
                msg.get("time_s", ""), msg.get("time_iso", ""),
                "TRIAL_START", f"Essai {self._trial_n}  {self._current_pid}",
            )

        elif t == "image_on":
            self._image_on_ts = time.monotonic()
            self._add_history_event(
                msg.get("time_s", ""), msg.get("time_iso", ""),
                "IMAGE_ON", f"Essai {self._trial_n}",
            )

        elif t == "response":
            self._last_response = msg.get("response", "")
            self._last_correct  = msg.get("is_correct")
            tr_s = msg.get("tr_s")
            if tr_s is not None:
                self._tr_values.append(tr_s)
            self._update_response_display()
            self._update_stats_display()  # update TR moyen immediately
            verdict = "✓ Correct" if self._last_correct is True else ("✗ Incorrect" if self._last_correct is False else "")
            self._add_history_event(
                msg.get("time_s", ""), msg.get("time_iso", ""),
                "RESPONSE",
                f"{self._last_response}  {verdict}  TR={f'{tr_s:.3f}s' if tr_s else '—'}",
            )

        elif t == "trial_end":
            self._presented_pids.add(self._current_pid)
            self._refresh_banque()
            self._add_history_event(
                msg.get("time_s", ""), msg.get("time_iso", ""),
                "TRIAL_END", f"Essai {msg.get('trial_n', '')}",
            )

        elif t == "stim_event":
            ev = msg.get("event", "")
            if ev == "STIM_START":
                self._stim_on       = True
                self._stim_start_ts = time.monotonic()
                self._stim_duration = msg.get("duration_s", 0.0)
            elif ev == "STIM_END":
                self._stim_on       = False
                self._stim_start_ts = None
            self._update_stim_banner()
            self._add_history_event(
                msg.get("time_s", ""), msg.get("time_iso", ""),
                ev,
                f"durée={msg.get('duration_s', '')}s" if ev == "STIM_START" else "",
            )

        elif t == "stats":
            self._n_correct  = msg.get("n_correct",  self._n_correct)
            self._n_total    = msg.get("n_total",     self._n_total)
            self._n_skipped  = msg.get("n_skipped",  self._n_skipped)
            self._n_excluded = msg.get("n_excluded", self._n_excluded)
            self._update_stats_display()

        elif t == "timer_tick":
            self._remaining_s = msg.get("remaining_s")

        elif t == "session_end":
            # Abort path: files already saved; show summary immediately
            print("[END] clinician received session_end (abort/emergency)")
            self._session_ended = True
            self._show_session_end_dialog(msg)

        elif t == "session_end_pending":
            # Natural end: show Finaliser dialog; run.py waits for save/abandon
            print("[END] clinician received session_end_pending — showing finalise dialog")
            self._disable_all_controls()
            self._pending_end_msg = msg
            self._show_finalise_dialog(msg)

        elif t == "session_saved":
            print("[END] clinician received session_saved")
            if hasattr(self, "_finalise_dlg"):
                try:
                    if self._finalise_dlg.winfo_exists():
                        self._finalise_dlg.destroy()
                except Exception:
                    pass
            self._session_ended = True
            combined = {**(getattr(self, "_pending_end_msg", {})), **msg}
            self._show_session_end_dialog(combined)

        elif t == "session_abandoned":
            print("[END] clinician received session_abandoned — closing")
            if hasattr(self, "_finalise_dlg"):
                try:
                    if self._finalise_dlg.winfo_exists():
                        self._finalise_dlg.destroy()
                except Exception:
                    pass
            self._session_ended = True
            self._root.destroy()

        elif t == "error":
            messagebox.showerror("Erreur", msg.get("message", "Erreur inconnue"))

        elif t == "stim_params":
            self._electrode.set(msg.get("electrode", ""))
            self._contact.set(msg.get("contact", ""))
            self._intensity.set(str(msg.get("intensity_ma", "")))
            self._duration.set(str(msg.get("duration_s", "")))

    # ── Display updates ───────────────────────────────────────────────────────

    def _update_trial_display(self) -> None:
        self._trial_lbl.config(text=f"Essai {self._trial_n} / {self._total_trials}")
        ans = self._correct_answer or "—"
        self._correct_lbl.config(text=f"Réponse attendue: {ans}")
        self._resp_lbl.config(text="Réponse patient: —", fg=FG)

    def _update_response_display(self) -> None:
        cr = self._last_correct
        if cr is True:
            colour  = GREEN
            verdict = "  ✓ Correct"
        elif cr is False:
            colour  = RED
            verdict = "  ✗ Incorrect"
        else:
            colour  = FG_DIM
            verdict = ""
        self._resp_lbl.config(
            text=f"Réponse patient: {self._last_response}{verdict}",
            fg=colour,
        )

    def _update_stats_display(self) -> None:
        pct = (
            round(self._n_correct / self._n_total * 100, 1)
            if self._n_total > 0 else 0.0
        )
        # Item 6: TR moyen
        mean_tr_str = ""
        if self._tr_values:
            mean_tr = sum(self._tr_values) / len(self._tr_values)
            mean_tr_str = f"\nTR moyen: {mean_tr:.3f}s  (n={len(self._tr_values)})"

        self._stats_lbl.config(
            text=(
                f"{self._n_correct}/{self._n_total} corrects  ({pct}%)\n"
                f"Passés: {self._n_skipped}   Exclus: {self._n_excluded}"
                f"{mean_tr_str}"
            )
        )

    def _update_timer_display(self) -> None:
        if self._image_on_ts is None:
            self._timer_lbl.config(text="")
            return
        t_str = f"Temps: {self._elapsed_s:.1f}s"
        if self._remaining_s is not None:
            t_str += f"   Restant: {self._remaining_s:.1f}s"
        self._timer_lbl.config(text=t_str)

    def _update_image(self) -> None:
        if not self._stim_path:
            return
        try:
            from PIL import Image as PILImage, ImageTk
            pil_img = PILImage.open(self._stim_path)
            pil_img.thumbnail((420, 300))
            mirror_img = ImageTk.PhotoImage(pil_img)
            self._img_label.config(image=mirror_img, text="", width=0, height=0)
            self._mirror_img = mirror_img
            self._root.update_idletasks()
        except Exception:
            name = Path(self._stim_path).name if self._stim_path else "—"
            self._img_label.config(image="", text=f"[{name}]", fg=FG, bg="black")

    # Item 5: Full-width STIM banner with countdown ───────────────────────────

    def _update_stim_banner(self) -> None:
        if self._stim_on:
            elapsed  = time.monotonic() - self._stim_start_ts if self._stim_start_ts else 0
            remaining = max(0.0, self._stim_duration - elapsed)
            elec = self._electrode.get() or "?"
            cont = self._contact.get()   or "?"
            mA   = self._intensity.get() or "?"
            dur  = self._duration.get()  or "?"
            text = (
                f"■  STIMULATION EN COURS  —  {elec}-{cont} | {mA}mA | {dur}s"
                f"  |  ▼ {remaining:.1f}s"
            )
            self._stim_banner.config(text=text, bg=STIM_ON, fg="white")
        else:
            self._stim_banner.config(text="  STIMULATION OFF  ", bg=STIM_OFF, fg=FG_DIM)

    # Item 9: Collapsible params ──────────────────────────────────────────────

    def _toggle_params(self) -> None:
        if self._params_collapsed:
            self._params_frame.pack(fill="x", pady=(0, 4))
            self._params_toggle_btn.config(text="▼ Paramètres de stimulation")
        else:
            self._params_frame.pack_forget()
            self._params_toggle_btn.config(text="▶ Paramètres de stimulation")
        self._params_collapsed = not self._params_collapsed

    # Item 11-12: Banque de stimuli ───────────────────────────────────────────

    def _refresh_banque(self) -> None:
        filt = self._banque_filter.get() if hasattr(self, "_banque_filter") else "Tous"

        if filt == "Restants":
            remaining_pids = {s["planche_id"] for s in self._remaining_stimuli}
            if self._current_pid:
                remaining_pids.add(self._current_pid)
            stimuli = [s for s in self._all_stimuli if s["planche_id"] in remaining_pids]
        elif filt == "Présentés":
            stimuli = [s for s in self._all_stimuli if s["planche_id"] in self._presented_pids]
        else:
            stimuli = self._all_stimuli

        if not hasattr(self, "_banque_lb"):
            return

        self._banque_lb.delete(0, "end")
        for s in stimuli:
            marker = " ●" if s["planche_id"] == self._current_pid else ""
            done   = " ✓" if s["planche_id"] in self._presented_pids else ""
            label  = s.get("label", s["planche_id"])
            self._banque_lb.insert("end", f"{label}{marker}{done}")

        self._banque_lb_stimuli = stimuli  # for selection mapping

    def _on_banque_select(self, _event=None) -> None:
        sel = self._banque_lb.curselection()
        if not sel or not hasattr(self, "_banque_lb_stimuli"):
            return
        idx = sel[0]
        if idx >= len(self._banque_lb_stimuli):
            return
        s = self._banque_lb_stimuli[idx]

        # Status label
        pid = s["planche_id"]
        if pid == self._current_pid:
            status = "En cours"
        elif pid in self._presented_pids:
            status = "Présenté"
        else:
            status = "En attente"
        label = s.get("label", pid)
        self._banque_name_lbl.config(text=f"{label}\n[{pid}]")
        self._banque_status_lbl.config(text=status)

        # Image preview
        path = s.get("path", "")
        if path:
            try:
                from PIL import Image as PILImage, ImageTk
                pil = PILImage.open(path)
                pil.thumbnail((340, 220))
                tk_img = ImageTk.PhotoImage(pil)
                self._banque_img_label.config(image=tk_img, text="")
                self._banque_img_tk = tk_img
            except Exception:
                self._banque_img_label.config(image="", text=f"[{pid}]", fg=FG, bg="black")

    # Historique helpers (items 13-15) ────────────────────────────────────────

    def _add_history_event(
        self, time_s, time_iso: str, event_type: str, details: str,
    ) -> None:
        ts_str  = f"{time_s:.3f}" if isinstance(time_s, (int, float)) else str(time_s)
        self._history_events.append({
            "time_s":   ts_str,
            "time_iso": str(time_iso),
            "event":    event_type,
            "details":  details,
        })
        if hasattr(self, "_hist_tree"):
            self._hist_tree.insert(
                "", "end",
                values=(ts_str, str(time_iso), event_type, details),
            )
            # Auto-scroll to bottom
            self._hist_tree.yview_moveto(1.0)

        self._update_hist_summary()

    def _update_hist_summary(self) -> None:
        if not hasattr(self, "_hist_summary_lbl"):
            return
        pct = round(self._n_correct / self._n_total * 100, 1) if self._n_total else 0
        mean_tr_str = ""
        if self._tr_values:
            mean_tr = sum(self._tr_values) / len(self._tr_values)
            mean_tr_str = f"  |  TR moyen: {mean_tr:.3f}s"
        self._hist_summary_lbl.config(
            text=(
                f"Essais: {self._n_total}   Corrects: {self._n_correct} ({pct}%)"
                f"  |  Passés: {self._n_skipped}   Exclus: {self._n_excluded}"
                f"{mean_tr_str}"
            )
        )

    def _export_historique(self) -> None:
        """Item 15: Export event history to CSV."""
        path = filedialog.asksaveasfilename(
            title="Exporter l'historique",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv"), ("Tous", "*")],
            initialfile=f"historique_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        )
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=["time_s", "time_iso", "event", "details"])
                writer.writeheader()
                writer.writerows(self._history_events)
            messagebox.showinfo("Exporté", f"Historique enregistré:\n{path}")
        except Exception as exc:
            messagebox.showerror("Erreur export", str(exc))

    # Item 15b: Finaliser la session dialog (natural end) ─────────────────────

    def _show_finalise_dialog(self, msg: dict) -> None:
        n_total    = msg.get("n_total",    self._n_total)
        n_correct  = msg.get("n_correct",  self._n_correct)
        patient_id = msg.get("patient_id", "—")
        task_name  = msg.get("task_display_name", self._task_display)

        dlg = tk.Toplevel(self._root)
        dlg.title("Finaliser la session")
        dlg.configure(bg="white")
        dlg.resizable(False, False)
        dlg.minsize(480, 1)
        dlg.protocol("WM_DELETE_WINDOW", lambda: None)   # block window-close button
        self._finalise_dlg = dlg
        dlg.transient(self._root)
        dlg.grab_set()
        dlg.lift()
        dlg.attributes("-topmost", True)
        dlg.focus_force()
        dlg.update()

        PAD = 24

        tk.Label(dlg, text="Finaliser la session",
                 font=("Helvetica", 18, "bold"), fg="black", bg="white").pack(pady=(20, 4))

        subtitle = (
            f"Patient : {patient_id}  —  {task_name}  "
            f"—  {n_total} essais  —  {n_correct} corrects"
        )
        tk.Label(dlg, text=subtitle,
                 font=("Helvetica", 10), fg="#666666", bg="white",
                 wraplength=440).pack(fill="x", padx=PAD)

        tk.Frame(dlg, bg="#cccccc", height=1).pack(fill="x", padx=PAD, pady=12)

        tk.Label(dlg, text="Notes clinicien (optionnel)",
                 font=("Helvetica", 11, "bold"), fg="#333333", bg="white",
                 anchor="w").pack(fill="x", padx=PAD)

        notes_box = tk.Text(dlg, width=52, height=4, wrap="word",
                            font=("Helvetica", 11),
                            bg="#f8f8f8", fg="#333333", relief="groove",
                            padx=4, pady=4)
        notes_box.pack(fill="x", padx=PAD, pady=(4, 2))

        tk.Label(
            dlg,
            text='Ex : "Patient fatigué", "Stimulation non tolérée", "Essai 12 interrompu"',
            font=("Helvetica", 9), fg="#999999", bg="white",
            anchor="w", justify="left",
        ).pack(fill="x", padx=PAD, pady=(0, 12))

        tk.Frame(dlg, bg="#cccccc", height=1).pack(fill="x", padx=PAD, pady=(0, 10))

        status_lbl = tk.Label(dlg, text="", font=("Helvetica", 10),
                               fg="#555555", bg="white")
        status_lbl.pack()

        btn_frame = tk.Frame(dlg, bg="white")
        btn_frame.pack(pady=(8, 20))

        save_btn = tk.Button(
            btn_frame, text="Sauvegarder et fermer",
            bg="#005500", fg="white", font=("Helvetica", 11),
            padx=12, pady=8,
        )
        abandon_btn = tk.Button(
            btn_frame, text="Abandonner la session",
            bg="#770000", fg="white", font=("Helvetica", 11),
            padx=12, pady=8,
        )
        save_btn.pack(side="left", padx=8)
        abandon_btn.pack(side="left", padx=8)

        def _do_save():
            notes = notes_box.get("1.0", "end-1c").strip()
            save_btn.config(state="disabled")
            abandon_btn.config(state="disabled")
            status_lbl.config(text="Génération du rapport Excel…")
            dlg.update_idletasks()
            self._send({"type": "finalize_save", "notes": notes})
            # dlg stays open; _handle_message('session_saved') will close it

        def _do_abandon():
            conf_dlg = tk.Toplevel(dlg)
            conf_dlg.title("Confirmer abandon")
            conf_dlg.configure(bg=BG)
            conf_dlg.resizable(False, False)
            conf_dlg.transient(dlg)
            conf_dlg.grab_set()
            conf_dlg.lift()
            conf_dlg.attributes("-topmost", True)
            conf_dlg.focus_force()
            conf_dlg.update()

            tk.Label(conf_dlg,
                     text="Les données ne seront PAS sauvegardées.",
                     fg=FG, bg=BG, font=("Helvetica", 12, "bold")).pack(padx=20, pady=(16, 6))
            tk.Label(conf_dlg, text="Confirmer l'abandon ?",
                     fg=FG_DIM, bg=BG, font=("Helvetica", 11)).pack(padx=20, pady=(0, 12))

            confirmed = []
            b = tk.Frame(conf_dlg, bg=BG)
            b.pack(pady=(0, 16))
            tk.Button(b, text="Oui, abandonner",
                      command=lambda: [confirmed.append(True), conf_dlg.destroy()],
                      bg="#770000", fg=FG, font=("Helvetica", 11),
                      padx=10, pady=5).pack(side="left", padx=8)
            tk.Button(b, text="Annuler", command=conf_dlg.destroy,
                      bg="#334455", fg=FG, font=("Helvetica", 11),
                      padx=10, pady=5).pack(side="left", padx=8)

            conf_dlg.grab_set()
            dlg.wait_window(conf_dlg)

            if confirmed:
                save_btn.config(state="disabled")
                abandon_btn.config(state="disabled")
                status_lbl.config(text="Session abandonnée…")
                dlg.update_idletasks()
                self._send({"type": "finalize_abandon"})
                # _handle_message('session_abandoned') will destroy root

        save_btn.config(command=_do_save)
        abandon_btn.config(command=_do_abandon)

    # Item 16: Session end dialog ─────────────────────────────────────────────

    def _show_session_end_dialog(self, msg: dict) -> None:
        n_total       = msg.get("n_total",   self._n_total)
        n_correct     = msg.get("n_correct", self._n_correct)
        n_skipped     = msg.get("n_skipped", self._n_skipped)
        n_excl        = msg.get("n_excluded", self._n_excluded)
        mean_tr       = msg.get("mean_tr")
        csv_path      = msg.get("csv_path", "")
        patient_id    = msg.get("patient_id", "—")
        task_name     = msg.get("task_display_name", self._task_display)
        n_stim_events = msg.get("n_stim_events", 0)

        n_pre  = msg.get("n_trials_pre",  0)
        ok_pre = msg.get("n_correct_pre", 0)
        tr_pre = msg.get("mean_TR_pre")
        n_per  = msg.get("n_trials_per",  0)
        ok_per = msg.get("n_correct_per", 0)
        tr_per = msg.get("mean_TR_per")
        n_post = msg.get("n_trials_post", 0)
        ok_post= msg.get("n_correct_post",0)
        tr_post= msg.get("mean_TR_post")

        now      = datetime.datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M")

        dlg = tk.Toplevel(self._root)
        dlg.title("Session terminée")
        dlg.configure(bg="white")
        dlg.resizable(False, False)
        dlg.minsize(480, 1)
        dlg.transient(self._root)
        dlg.grab_set()
        dlg.lift()
        dlg.attributes("-topmost", True)
        dlg.focus_force()
        dlg.update()

        PAD = 24

        # ── Title ────────────────────────────────────────────────────────────
        tk.Label(
            dlg, text="Session terminée",
            font=("Helvetica", 20, "bold"), fg="black", bg="white",
        ).pack(fill="x", pady=(20, 4))

        subtitle = f"Patient : {patient_id}  |  Tâche : {task_name}  |  {date_str}  {time_str}"
        tk.Label(
            dlg, text=subtitle,
            font=("Helvetica", 10), fg="#666666", bg="white",
            wraplength=440,
        ).pack(fill="x", padx=PAD)

        # ── Separator ────────────────────────────────────────────────────────
        tk.Frame(dlg, bg="#cccccc", height=1).pack(fill="x", padx=PAD, pady=12)

        # ── Results block (3 columns) ─────────────────────────────────────────
        pct = round(n_correct / n_total * 100, 1) if n_total else 0.0
        if pct >= 70:
            pct_color = "#007700"
        elif pct >= 40:
            pct_color = "#996600"
        else:
            pct_color = "#cc0000"

        res_frame = tk.Frame(dlg, bg="white")
        res_frame.pack(fill="x", padx=PAD, pady=(0, 8))
        for col in range(3):
            res_frame.columnconfigure(col, weight=1, uniform="res")

        for col, hdr in enumerate(["Essais", "Corrects", "TR moyen"]):
            tk.Label(res_frame, text=hdr,
                     font=("Helvetica", 10), fg="#888888", bg="white",
                     anchor="center").grid(row=0, column=col, sticky="ew")

        tr_str = f"{mean_tr:.2f} s" if mean_tr is not None else "—"
        tk.Label(res_frame, text=str(n_total),
                 font=("Helvetica", 22, "bold"), fg="black", bg="white",
                 anchor="center").grid(row=1, column=0, sticky="ew")

        correct_inner = tk.Frame(res_frame, bg="white")
        correct_inner.grid(row=1, column=1, sticky="ew")
        tk.Label(correct_inner, text=f"{n_correct} ",
                 font=("Helvetica", 22, "bold"), fg="black", bg="white").pack(side="left", expand=True, anchor="e")
        tk.Label(correct_inner, text=f"({pct}%)",
                 font=("Helvetica", 13), fg=pct_color, bg="white").pack(side="left", anchor="s", pady=5)

        tk.Label(res_frame, text=tr_str,
                 font=("Helvetica", 22, "bold"), fg="black", bg="white",
                 anchor="center").grid(row=1, column=2, sticky="ew")

        # ── Separator ────────────────────────────────────────────────────────
        tk.Frame(dlg, bg="#cccccc", height=1).pack(fill="x", padx=PAD, pady=(4, 10))

        # ── Stimulation block ─────────────────────────────────────────────────
        if n_stim_events > 0:
            s_label = "s" if n_stim_events != 1 else ""
            tk.Label(
                dlg, text=f"Stimulations : {n_stim_events} événement{s_label}",
                font=("Helvetica", 11, "bold"), fg="black", bg="white", anchor="w",
            ).pack(fill="x", padx=PAD, pady=(0, 6))

            tbl = tk.Frame(dlg, bg="white")
            tbl.pack(fill="x", padx=PAD, pady=(0, 10))
            for col in range(3):
                tbl.columnconfigure(col, weight=1, uniform="tbl")

            # Header row
            for col, hdr in enumerate(["", "Corrects", "TR moyen"]):
                tk.Label(tbl, text=hdr,
                         font=("Helvetica", 10, "bold"), fg="#444444", bg="#f0f0f0",
                         padx=6, pady=3, anchor="center",
                         relief="groove").grid(row=0, column=col, sticky="ew", padx=1, pady=1)

            def _pct_str(n, ok):
                if not n:
                    return "—"
                return f"{ok}/{n}  ({round(ok/n*100, 1)}%)"

            def _tr_fmt(tr):
                return f"{tr:.2f} s" if tr is not None else "—"

            for ri, (label, n, ok, tr, color, row_bg) in enumerate([
                ("Pré-stim",  n_pre,  ok_pre,  tr_pre,  "black",   "white"),
                ("Per-stim",  n_per,  ok_per,  tr_per,  "#CC2200", "#fff6f6"),
                ("Post-stim", n_post, ok_post, tr_post, "#0055AA", "#f4f8ff"),
            ], start=1):
                for col, (txt, anc) in enumerate([
                    (label,              "w"),
                    (_pct_str(n, ok),    "center"),
                    (_tr_fmt(tr),        "center"),
                ]):
                    tk.Label(tbl, text=txt,
                             font=("Helvetica", 11), fg=color, bg=row_bg,
                             padx=6, pady=3, anchor=anc,
                             relief="groove").grid(row=ri, column=col, sticky="ew", padx=1, pady=1)

        # ── File line ─────────────────────────────────────────────────────────
        if csv_path:
            stem = Path(csv_path).stem
            file_row = tk.Frame(dlg, bg="white")
            file_row.pack(fill="x", padx=PAD, pady=(0, 8))

            tk.Label(file_row, text=f"Fichier sauvegardé : {stem}",
                     font=("Helvetica", 9), fg="#888888", bg="white",
                     wraplength=340, justify="left").pack(side="left")

            def _open_folder(p=csv_path):
                folder = str(Path(p).parent)
                try:
                    if platform.system() == "Windows":
                        os.startfile(folder)
                    elif platform.system() == "Darwin":
                        subprocess.Popen(["open", folder])
                    else:
                        subprocess.Popen(["xdg-open", folder])
                except Exception:
                    pass

            tk.Button(file_row, text="Ouvrir le dossier", command=_open_folder,
                      bg="#eeeeee", fg="#333333", font=("Helvetica", 9),
                      padx=6, pady=2, relief="groove").pack(side="right")

        # ── Separator + close button ──────────────────────────────────────────
        tk.Frame(dlg, bg="#cccccc", height=1).pack(fill="x", padx=PAD, pady=(4, 8))

        def _close():
            dlg.destroy()
            self._root.destroy()

        def _quit():
            dlg.destroy()
            try:
                self._send({"type": "quit_app"})
            except Exception:
                pass
            self._root.destroy()

        btn_row = tk.Frame(dlg, bg="white")
        btn_row.pack(pady=(0, 16))
        tk.Button(
            btn_row, text="Fermer et revenir à l'accueil",
            command=_close,
            bg="#dddddd", fg="black", font=("Helvetica", 11),
            padx=12, pady=8,
        ).pack(side="left", padx=6)
        tk.Button(
            btn_row, text="Quitter",
            command=_quit,
            bg="#770000", fg="white", font=("Helvetica", 11),
            padx=12, pady=8,
        ).pack(side="left", padx=6)

    # ── Clinician commands ────────────────────────────────────────────────────

    def _send(self, msg: dict) -> None:
        self._to_q.put_nowait(msg)

    def _cmd_skip(self) -> None:
        self._send({"type": "skip"})

    def _cmd_exclude(self) -> None:
        self._send({"type": "exclude"})

    def _cmd_replace(self) -> None:
        """Item 7: Improved replace dialog with scrollable listbox."""
        if not self._remaining_stimuli:
            messagebox.showinfo("Remplacer", "Aucun stimulus disponible pour le remplacement.")
            return

        dlg = tk.Toplevel(self._root)
        dlg.title("Remplacer le stimulus actuel")
        dlg.configure(bg=BG)
        dlg.transient(self._root)
        dlg.grab_set()
        dlg.lift()
        dlg.attributes("-topmost", True)
        dlg.focus_force()
        dlg.update()

        tk.Label(
            dlg, text="Sélectionnez le stimulus de remplacement:",
            fg=FG, bg=BG,
        ).pack(padx=12, pady=(10, 4))

        lb_frame = tk.Frame(dlg, bg=BG)
        lb_frame.pack(padx=12, fill="both", expand=True)

        sb = tk.Scrollbar(lb_frame)
        sb.pack(side="right", fill="y")

        lb = tk.Listbox(
            lb_frame, width=40, height=14,
            bg="#222233", fg=FG,
            selectbackground="#334488",
            yscrollcommand=sb.set,
        )
        lb.pack(side="left", fill="both", expand=True)
        sb.config(command=lb.yview)

        for s in self._remaining_stimuli:
            label = s.get("label", s["planche_id"]) if "label" in s else s["planche_id"]
            lb.insert("end", f"{label}  [{s['planche_id']}]")

        def confirm():
            sel = lb.curselection()
            if not sel:
                return
            pid = self._remaining_stimuli[sel[0]]["planche_id"]
            self._send({"type": "replace", "planche_id": pid})
            dlg.destroy()

        lb.bind("<Double-Button-1>", lambda _: confirm())

        btn_frame = tk.Frame(dlg, bg=BG)
        btn_frame.pack(pady=8)
        ttk.Button(btn_frame, text="Remplacer", command=confirm).pack(side="left", padx=6)
        ttk.Button(btn_frame, text="Annuler", command=dlg.destroy).pack(side="left", padx=6)

    def _send_update_params(self) -> None:
        try:
            self._send({
                "type":         "update_params",
                "electrode":    self._electrode.get().strip(),
                "contact":      self._contact.get().strip(),
                "intensity_ma": float(self._intensity.get()),
                "duration_s":   float(self._duration.get()),
            })
        except ValueError:
            messagebox.showerror("Erreur", "Valeurs de paramètres invalides.")

    def _cmd_next_trial(self) -> None:
        if self._prog_mode == "ClinicianAction":
            self._send({"type": "next_trial"})

    def _disable_all_controls(self) -> None:
        self._session_active = False
        for attr in ("_abort_btn", "_skip_btn", "_excl_btn", "_repl_btn", "_next_btn"):
            btn = getattr(self, attr, None)
            if btn:
                try:
                    btn.config(state="disabled")
                except Exception:
                    pass
        if hasattr(self, "_mock_stim_btn"):
            try:
                self._mock_stim_btn.config(state="disabled")
            except Exception:
                pass

    def _cmd_abort(self) -> None:
        if not self._session_active:
            return
        # If the session already ended (end dialog showing), just close the root.
        if self._session_ended:
            self._root.destroy()
            return

        confirmed = []

        dlg = tk.Toplevel(self._root)
        dlg.title("Arrêter la session")
        dlg.configure(bg=BG)
        dlg.resizable(False, False)
        dlg.transient(self._root)
        dlg.grab_set()
        dlg.lift()
        dlg.attributes("-topmost", True)
        dlg.focus_force()
        dlg.update()

        tk.Label(
            dlg,
            text="Êtes-vous sûr de vouloir arrêter la session ?",
            fg=FG, bg=BG, font=("Helvetica", 13, "bold"),
            wraplength=340,
        ).pack(padx=24, pady=(20, 6))

        tk.Label(
            dlg,
            text="Les données seront sauvegardées.",
            fg=FG_DIM, bg=BG, font=("Helvetica", 11),
        ).pack(padx=24, pady=(0, 16))

        btn_frame = tk.Frame(dlg, bg=BG)
        btn_frame.pack(pady=(0, 16))

        tk.Button(
            btn_frame, text="Oui, arrêter",
            command=lambda: [confirmed.append(True), dlg.destroy()],
            bg="#770000", fg=FG, font=("Helvetica", 11),
            padx=12, pady=6,
        ).pack(side="left", padx=8)

        tk.Button(
            btn_frame, text="Annuler",
            command=dlg.destroy,
            bg="#334455", fg=FG, font=("Helvetica", 11),
            padx=12, pady=6,
        ).pack(side="left", padx=8)

        dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
        dlg.grab_set()
        self._root.wait_window(dlg)   # local event loop — poll continues during wait

        if confirmed:
            print("[ABORT] step 1 — clinician confirmed abort")
            self._disable_all_controls()
            self._send({"type": "abort_session"})
            print("[ABORT] step 2 — abort_session sent, controls disabled")
            try:
                self._abort_btn.config(text="Arrêt en cours…")
            except Exception:
                pass
            print("[ABORT] step 3 — waiting for session_end from patient")

    def _cmd_stim_key(self) -> None:
        self._send({"type": "stim_key"})

    def _cmd_di_correct(self) -> None:
        if self._task_code == "DI_SEEG":
            self._send({"type": "di_correct"})

    def _cmd_di_incorrect(self) -> None:
        if self._task_code == "DI_SEEG":
            self._send({"type": "di_incorrect"})

    def _cmd_annotate(self) -> None:
        """Item 10: Send clinician annotation as NOTE event."""
        text = self._annot_entry.get().strip()
        if not text:
            return
        self._send({"type": "annotate", "text": text})
        self._annot_entry.delete(0, "end")
        # Record locally in Historique
        now_iso = datetime.datetime.now().isoformat(timespec="seconds")
        self._add_history_event("—", now_iso, "NOTE", text)

    # ── Main loop ─────────────────────────────────────────────────────────────

    def run(self) -> None:
        self._root.after(self.POLL_MS, self._poll)
        self._root.mainloop()


# ─── Subprocess entry point ───────────────────────────────────────────────────

def run_clinician_process(
    from_patient_q,
    to_patient_q,
    task_code: str,
    task_display_name: str,
    progression_mode: str,
    stim_key: str,
    electrode: str,
    contact: str,
    intensity_ma: float,
    duration_s: float,
    mock: bool = False,
) -> None:
    """
    Entry point for the clinician window subprocess.
    Instantiates ClinicianApp and runs the tkinter event loop.
    """
    app = ClinicianApp(
        from_patient_q=from_patient_q,
        to_patient_q=to_patient_q,
        task_code=task_code,
        task_display_name=task_display_name,
        progression_mode=progression_mode,
        stim_key=stim_key,
        mock=mock,
    )
    # Pre-populate stim params display
    app._electrode.set(electrode)
    app._contact.set(contact)
    app._intensity.set(str(intensity_ma))
    app._duration.set(str(duration_s))
    # Assert topmost before the patient window opens and can steal focus
    app._root.lift()
    app._root.attributes("-topmost", True)
    app._root.update()
    app.run()

    # Release queue references so the subprocess's resource_tracker does not
    # report the shared semaphores as leaked when this process exits.
    for _q in (from_patient_q, to_patient_q):
        try:
            _q.cancel_join_thread()
            _q.close()
        except Exception:
            pass
