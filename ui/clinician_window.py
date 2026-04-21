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
    ) -> None:
        self._from_q = from_patient_q
        self._to_q   = to_patient_q
        self._task_code       = task_code
        self._task_display    = task_display_name
        self._prog_mode       = progression_mode
        self._stim_key        = stim_key.lower()

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

    # ── Session tab ───────────────────────────────────────────────────────────

    def _build_session_tab(self, parent: ttk.Frame) -> None:
        main = tk.Frame(parent, bg=BG)
        main.pack(fill="both", expand=True, padx=6, pady=4)

        # Left: image mirror
        img_frame = tk.LabelFrame(main, text="Stimulus actuel", bg=BG, fg=FG, font=("Helvetica", 10))
        img_frame.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)

        self._img_label = tk.Label(img_frame, bg="black", width=44, height=22)
        self._img_label.pack(padx=4, pady=4)
        self._tk_img = None  # prevent GC

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
        self._root.bind(f"<{self._stim_key.upper()}>", lambda e: self._cmd_stim_key())
        self._root.bind(f"<{self._stim_key}>",          lambda e: self._cmd_stim_key())
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
            self._session_ended = True
            self._show_session_end_dialog(msg)

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
            tk_img = ImageTk.PhotoImage(pil_img)
            self._img_label.config(image=tk_img, text="")
            self._tk_img = tk_img
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

    # Item 16: Session end dialog ─────────────────────────────────────────────

    def _show_session_end_dialog(self, msg: dict) -> None:
        n_total   = msg.get("n_total",   self._n_total)
        n_correct = msg.get("n_correct", self._n_correct)
        n_skipped = msg.get("n_skipped", self._n_skipped)
        n_excl    = msg.get("n_excluded", self._n_excluded)
        mean_tr   = msg.get("mean_tr")
        csv_path  = msg.get("csv_path", "")

        dlg = tk.Toplevel(self._root)
        dlg.title("Session terminée")
        dlg.grab_set()
        dlg.configure(bg=BG)
        dlg.resizable(False, False)

        tk.Label(
            dlg, text="Session terminée",
            font=("Helvetica", 20, "bold"), fg=GREEN, bg=BG,
        ).pack(pady=(16, 8))

        pct = round(n_correct / n_total * 100, 1) if n_total else 0

        info_lines = [
            f"Résultats :  {n_correct} / {n_total}  ({pct} %)",
            f"Passés : {n_skipped}    Exclus : {n_excl}",
        ]
        if mean_tr is not None:
            info_lines.append(f"TR moyen : {mean_tr:.3f} s")

        for line in info_lines:
            tk.Label(dlg, text=line, fg=FG, bg=BG, font=("Helvetica", 12)).pack(pady=2)

        if csv_path:
            tk.Label(
                dlg, text="\nDonnées sauvegardées :",
                fg=FG_DIM, bg=BG, font=("Helvetica", 10),
            ).pack()
            tk.Label(
                dlg, text=csv_path,
                fg="#aaddff", bg=BG, font=("Helvetica", 9),
                wraplength=480, justify="center",
            ).pack(padx=16, pady=(0, 12))

        def _close():
            dlg.destroy()
            self._root.destroy()

        ttk.Button(
            dlg, text="Fermer et revenir à l'accueil",
            command=_close,
        ).pack(pady=(8, 16))

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
        dlg.grab_set()
        dlg.configure(bg=BG)

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

    def _cmd_abort(self) -> None:
        if messagebox.askyesno("Arrêter", "Arrêter la session en cours ?"):
            self._send({"type": "abort"})
            self._root.after(1500, self._root.destroy)

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
