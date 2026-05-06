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


# ─── Design tokens ─────────────────────────────────────────────────────────────

C_BG           = "#ffffff"
C_BG_SECONDARY = "#f7f8fa"
C_BORDER       = "#e2e5ea"
C_TEXT         = "#111318"
C_TEXT_MUTED   = "#6b7280"
C_TEXT_FAINT   = "#9ca3af"
C_BLUE         = "#3b7dd8"
C_NAVY         = "#1a2744"
C_GREEN        = "#16a34a"
C_RED          = "#dc2626"
C_STIM_ON_BG   = "#dc2626"
C_STIM_ON_FG   = "#ffffff"
C_STIM_OFF_BG  = "#f7f8fa"
C_STIM_OFF_FG  = "#6b7280"
C_BG_DARK      = "#0a0a0f"
C_AMBER        = "#d97706"

# Spec-named aliases
C_BG_2    = C_BG_SECONDARY
C_TEXT_2  = C_TEXT_MUTED
C_TEXT_3  = C_TEXT_FAINT
C_STIM_ON = C_STIM_ON_BG
C_STIM_OFF = C_STIM_OFF_BG

# Legacy aliases kept for any remaining references
BG      = C_BG
BG2     = C_BG_SECONDARY
BG3     = C_BG_SECONDARY
FG      = C_TEXT
FG_DIM  = C_TEXT_MUTED
FG_LIGHT = C_STIM_ON_FG
GREEN   = C_GREEN
RED     = C_RED
ORANGE  = C_AMBER
STIM_ON  = C_STIM_ON_BG
STIM_OFF = C_STIM_OFF_BG

# Font constants
F_BODY   = ("Helvetica Neue", 12)
F_SMALL  = ("Helvetica Neue", 10)
F_LABEL  = ("Helvetica Neue", 9)
F_MONO   = ("Menlo", 11)
F_MONO_L = ("Menlo", 15)
F_BOLD   = ("Helvetica Neue", 12, "bold")
F_TITLE  = ("Helvetica Neue", 16, "bold")


# ─── Clinician application ────────────────────────────────────────────────────

class ClinicianApp:
    POLL_MS = 50

    def __init__(
        self,
        from_patient_q,
        to_patient_q,
        task_code: str,
        task_display_name: str,
        progression_mode: str,
        stim_key: str = "f12",
        mock: bool = False,
        patient_id: str = "",
    ) -> None:
        self._from_q = from_patient_q
        self._to_q   = to_patient_q
        self._task_code       = task_code
        self._task_display    = task_display_name
        self._prog_mode       = progression_mode
        self._stim_key        = stim_key.lower()
        self._mock            = mock
        self._patient_id      = patient_id

        self._trial_n          = 0
        self._total_trials     = 0
        self._stim_path        = ""
        self._current_pid      = ""
        self._correct_answer   = ""
        self._last_response    = ""
        self._last_correct     = None
        self._image_on_ts      = None
        self._stim_on          = False
        self._stim_start_ts    = None
        self._stim_duration    = 0.0
        self._elapsed_s        = 0.0
        self._remaining_s      = None
        self._n_correct        = 0
        self._n_total          = 0
        self._n_skipped        = 0
        self._n_excluded       = 0
        self._tr_values: list[float] = []
        self._remaining_stimuli: list[dict] = []
        self._session_ended: bool = False
        self._session_active: bool = True

        self._all_stimuli: list[dict] = []
        self._presented_pids: set[str] = set()
        self._history_events: list[dict] = []

        self._root = tk.Tk()

        self._electrode   = tk.StringVar()
        self._contact     = tk.StringVar()
        self._intensity   = tk.StringVar()
        self._duration    = tk.StringVar()

        self._params_collapsed = False
        self._build_ui()
        self._bind_keys()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = self._root
        root.title("Battery — Opérateur")
        root.configure(bg=C_BG)
        root.geometry("1100x760")

        # ── Header bar ────────────────────────────────────────────────────────
        header = tk.Frame(
            root, bg=C_BG, height=48,
            highlightbackground=C_BORDER, highlightthickness=1,
        )
        header.pack(fill="x")
        header.pack_propagate(False)

        left_hdr = tk.Frame(header, bg=C_BG)
        left_hdr.pack(side="left", padx=(12, 0), fill="y")

        dot_cv = tk.Canvas(left_hdr, width=10, height=10, bg=C_BG, highlightthickness=0)
        dot_cv.pack(side="left", anchor="center", pady=14, padx=(0, 8))
        dot_cv.create_oval(1, 1, 9, 9, fill="#22c55e", outline="")

        lbl_col = tk.Frame(left_hdr, bg=C_BG)
        lbl_col.pack(side="left", anchor="center")

        self._task_lbl = tk.Label(
            lbl_col, text=self._task_display,
            font=F_BOLD, fg=C_TEXT, bg=C_BG, anchor="w",
        )
        self._task_lbl.pack(anchor="w")

        self._patient_meta_lbl = tk.Label(
            lbl_col, text=self._patient_id,
            font=F_SMALL, fg=C_TEXT_2, bg=C_BG, anchor="w",
        )
        self._patient_meta_lbl.pack(anchor="w")

        if self._mock:
            tk.Label(
                left_hdr, text="MODE TEST",
                font=("Helvetica Neue", 9, "bold"),
                fg="#b45309", bg="#fffbeb",
                padx=6, pady=2,
            ).pack(side="left", padx=(12, 0), anchor="center")

        right_hdr = tk.Frame(header, bg=C_BG)
        right_hdr.pack(side="right", padx=12, fill="y")

        _pill_kw = dict(
            font=F_MONO, fg=C_TEXT_2, bg=C_BG_2,
            highlightbackground=C_BORDER, highlightthickness=1,
            padx=8, pady=3, relief="flat",
        )
        self._timer_pill = tk.Label(right_hdr, text="0.0s", **_pill_kw)
        self._timer_pill.pack(side="right", anchor="center", pady=13)

        self._trial_pill = tk.Label(right_hdr, text="— / —", **_pill_kw)
        self._trial_pill.pack(side="right", anchor="center", pady=13, padx=(0, 6))

        # ── STIM banner ───────────────────────────────────────────────────────
        self._stim_banner = tk.Label(
            root,
            text="  STIMULATION OFF  ",
            font=("Helvetica Neue", 11, "bold"),
            fg=C_STIM_OFF_FG, bg=C_STIM_OFF_BG,
            anchor="center", height=2,
        )
        self._stim_banner.pack(fill="x")

        # ── Notebook ──────────────────────────────────────────────────────────
        nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=True, padx=8, pady=(6, 0))

        tab_session = ttk.Frame(nb)
        tab_banque  = ttk.Frame(nb)
        tab_hist    = ttk.Frame(nb)
        nb.add(tab_session, text="Session en cours")
        nb.add(tab_banque,  text="Banque de stimuli")
        nb.add(tab_hist,    text="Historique")

        self._build_session_tab(tab_session)
        self._build_banque_tab(tab_banque)
        self._build_historique_tab(tab_hist)

    # ── Session tab ───────────────────────────────────────────────────────────

    def _build_session_tab(self, parent: ttk.Frame) -> None:
        main = tk.Frame(parent, bg=C_BG)
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=3)
        main.columnconfigure(1, weight=0, minsize=340)

        # ── Left: dark patient mirror ─────────────────────────────────────────
        img_card = tk.Frame(main, bg=C_BG_DARK)
        img_card.grid(row=0, column=0, sticky="nsew", padx=(8, 4), pady=8)

        tk.Label(
            img_card, text="ÉCRAN PATIENT",
            font=F_LABEL, fg="#333344", bg=C_BG_DARK,
            anchor="w", padx=12, pady=6,
        ).pack(fill="x")

        self._img_label = tk.Label(img_card, bg=C_BG_DARK)
        self._img_label.pack(padx=8, pady=(0, 12), expand=True)
        self._mirror_img = None

        # ── Right: info panel ─────────────────────────────────────────────────
        right_panel = tk.Frame(
            main, bg=C_BG,
            highlightbackground=C_BORDER, highlightthickness=1,
        )
        right_panel.grid(row=0, column=1, sticky="nsew", padx=(4, 8), pady=8)

        inner = tk.Frame(right_panel, bg=C_BG)
        inner.pack(fill="both", expand=True)

        def _sec_lbl(title: str) -> None:
            tk.Label(
                inner, text=title,
                font=F_LABEL, fg=C_TEXT_FAINT, bg=C_BG,
                anchor="w", padx=12,
            ).pack(fill="x", pady=(6, 2))

        def _divider() -> None:
            tk.Frame(inner, bg=C_BORDER, height=1).pack(fill="x", padx=8, pady=2)

        def _tile(parent_w, title: str):
            f = tk.Frame(
                parent_w, bg=C_BG_2,
                highlightbackground=C_BORDER, highlightthickness=1,
            )
            tk.Label(f, text=title, font=F_LABEL, fg=C_TEXT_3, bg=C_BG_2,
                     anchor="w", padx=6).pack(fill="x", pady=(4, 0))
            val = tk.Label(f, text="—", font=F_BOLD, fg=C_TEXT, bg=C_BG_2,
                           anchor="w", padx=6)
            val.pack(fill="x", pady=(0, 4))
            return f, val

        # ── ESSAI EN COURS ────────────────────────────────────────────────────
        _sec_lbl("ESSAI EN COURS")

        grid2 = tk.Frame(inner, bg=C_BG)
        grid2.pack(fill="x", padx=8, pady=(0, 2))
        grid2.columnconfigure(0, weight=1, uniform="t2")
        grid2.columnconfigure(1, weight=1, uniform="t2")

        f_ess, self._tile_essai_val    = _tile(grid2, "Essai")
        f_tmp, self._tile_temps_val    = _tile(grid2, "Temps écoulé")
        f_att, self._tile_attendue_val = _tile(grid2, "Réponse attendue")
        f_rsp, self._tile_resp_val     = _tile(grid2, "Réponse patient")

        f_ess.grid(row=0, column=0, sticky="nsew", padx=(0, 2), pady=(0, 2))
        f_tmp.grid(row=0, column=1, sticky="nsew", padx=(2, 0), pady=(0, 2))
        f_att.grid(row=1, column=0, sticky="nsew", padx=(0, 2), pady=(2, 0))
        f_rsp.grid(row=1, column=1, sticky="nsew", padx=(2, 0), pady=(2, 0))

        f_stm, self._tile_stim_val = _tile(inner, "Stimulus")
        f_stm.pack(fill="x", padx=8, pady=(4, 2))

        self._timer_canvas = tk.Canvas(
            inner, height=3, bg=C_BORDER, highlightthickness=0,
        )
        self._timer_canvas.pack(fill="x", padx=8, pady=(2, 1))

        self._timer_lbl = tk.Label(
            inner, text="", font=F_MONO, fg=C_TEXT_MUTED, bg=C_BG,
            anchor="w", padx=8,
        )
        self._timer_lbl.pack(fill="x", pady=(0, 2))

        _divider()

        # ── STATISTIQUES ──────────────────────────────────────────────────────
        _sec_lbl("STATISTIQUES")

        chips_row = tk.Frame(inner, bg=C_BG)
        chips_row.pack(fill="x", padx=8, pady=(0, 4))
        for _c in range(4):
            chips_row.columnconfigure(_c, weight=1, uniform="ch")

        def _chip(parent_w, title: str):
            f = tk.Frame(
                parent_w, bg=C_BG_2,
                highlightbackground=C_BORDER, highlightthickness=1,
            )
            tk.Label(f, text=title, font=F_LABEL, fg=C_TEXT_3, bg=C_BG_2,
                     anchor="center").pack(fill="x", pady=(4, 0))
            val = tk.Label(f, text="—", font=("Menlo", 18, "bold"), fg=C_TEXT, bg=C_BG_2,
                           anchor="center")
            val.pack(fill="x", pady=(0, 4))
            return f, val

        fc_tot, self._chip_total_val   = _chip(chips_row, "Essais")
        fc_cor, self._chip_correct_val = _chip(chips_row, "Corrects")
        fc_skp, self._chip_skipped_val = _chip(chips_row, "Passés")
        fc_pct, self._chip_pct_val     = _chip(chips_row, "% Correct")

        fc_tot.grid(row=0, column=0, sticky="nsew", padx=(0, 1))
        fc_cor.grid(row=0, column=1, sticky="nsew", padx=1)
        fc_skp.grid(row=0, column=2, sticky="nsew", padx=1)
        fc_pct.grid(row=0, column=3, sticky="nsew", padx=(1, 0))

        _divider()

        # ── CONTRÔLE ─────────────────────────────────────────────────────────
        _sec_lbl("CONTRÔLE")

        ctrl = tk.Frame(inner, bg=C_BG)
        ctrl.pack(fill="x", padx=8, pady=(0, 4))

        _btn_kw = dict(
            bg=C_BG, fg=C_TEXT, relief="flat",
            font=F_BODY, cursor="hand2", width=30, anchor="w",
            highlightbackground=C_BORDER, highlightthickness=1,
            padx=8, pady=4,
        )

        self._skip_btn = tk.Button(ctrl, text="Passer", command=self._cmd_skip, **_btn_kw)
        self._skip_btn.pack(fill="x", pady=1)

        self._excl_btn = tk.Button(ctrl, text="Exclure", command=self._cmd_exclude, **_btn_kw)
        self._excl_btn.pack(fill="x", pady=1)

        self._repl_btn = tk.Button(ctrl, text="Remplacer…", command=self._cmd_replace, **_btn_kw)
        self._repl_btn.pack(fill="x", pady=1)

        self._next_btn = tk.Button(
            ctrl, text="Essai suivant ▶", command=self._cmd_next_trial,
            state="disabled", **_btn_kw,
        )
        self._next_btn.pack(fill="x", pady=1)
        if self._prog_mode == "ClinicianAction":
            self._next_btn.config(state="normal")

        self._abort_btn = tk.Button(
            ctrl, text="Arrêter la séance", command=self._cmd_abort,
            bg=C_BG, fg=C_RED, relief="flat", width=30, anchor="w",
            font=F_BODY, cursor="hand2",
            highlightbackground="#fca5a5", highlightthickness=1,
            padx=8, pady=4,
        )
        self._abort_btn.pack(fill="x", pady=1)

        if self._mock:
            self._mock_stim_btn = tk.Button(
                ctrl, text="Test STIM (F12)", command=self._cmd_stim_key,
                fg="#b45309", bg="#fffbeb",
                relief="flat", width=30, anchor="w",
                font=F_BODY, cursor="hand2",
                highlightbackground="#fbbf24", highlightthickness=1,
                padx=8, pady=4,
            )
            self._mock_stim_btn.pack(fill="x", pady=1)

        _divider()

        # ── ANNOTATION ────────────────────────────────────────────────────────
        _sec_lbl("ANNOTATION")

        annot_row = tk.Frame(inner, bg=C_BG)
        annot_row.pack(fill="x", padx=8, pady=(2, 8))

        self._annot_entry = tk.Entry(
            annot_row, width=22,
            font=F_SMALL,
            bg=C_BG_SECONDARY, fg=C_TEXT, insertbackground=C_TEXT,
            relief="flat",
            highlightbackground=C_BORDER, highlightthickness=1,
        )
        self._annot_entry.pack(side="left", padx=(0, 6))
        self._annot_entry.bind("<Return>", lambda _: self._cmd_annotate())

        tk.Button(
            annot_row, text="Ajouter",
            command=self._cmd_annotate,
            bg=C_BG, fg=C_TEXT, font=F_SMALL,
            relief="flat", highlightbackground=C_BORDER, highlightthickness=1,
            padx=10, pady=3, cursor="hand2",
        ).pack(side="left")

        _divider()

        # ── PARAMÈTRES DE STIMULATION (collapsible) ───────────────────────────
        self._params_toggle_btn = tk.Button(
            inner,
            text="▼  PARAMÈTRES DE STIMULATION",
            command=self._toggle_params,
            bg=C_BG, fg=C_TEXT_MUTED,
            relief="flat", anchor="w",
            font=F_LABEL,
            padx=12, pady=6, cursor="hand2",
        )
        self._params_toggle_btn.pack(fill="x")

        self._params_frame = tk.Frame(
            inner, bg=C_BG_SECONDARY,
            highlightbackground=C_BORDER, highlightthickness=1,
        )
        self._params_frame.pack(fill="x", padx=8, pady=(0, 8))

        for i, (lbl, var) in enumerate([
            ("Électrode",      self._electrode),
            ("Contact",        self._contact),
            ("Intensité (mA)", self._intensity),
            ("Durée (s)",      self._duration),
        ]):
            tk.Label(
                self._params_frame, text=lbl,
                font=F_SMALL, fg=C_TEXT, bg=C_BG_SECONDARY,
                anchor="w",
            ).grid(row=i, column=0, sticky="w", padx=10, pady=2)
            tk.Entry(
                self._params_frame, textvariable=var, width=10,
                font=F_SMALL,
                bg=C_BG, fg=C_TEXT, insertbackground=C_TEXT,
                relief="flat",
                highlightbackground=C_BORDER, highlightthickness=1,
            ).grid(row=i, column=1, sticky="w", padx=(6, 10))

        tk.Button(
            self._params_frame, text="Mettre à jour",
            command=self._send_update_params,
            bg=C_BLUE, fg="white",
            relief="flat", font=F_SMALL,
            padx=10, pady=5, cursor="hand2",
        ).grid(row=4, column=0, columnspan=2, pady=(6, 8), sticky="w", padx=10)

    # ── Banque de stimuli tab ─────────────────────────────────────────────────

    def _build_banque_tab(self, parent: ttk.Frame) -> None:
        filter_bar = tk.Frame(
            parent, bg=C_BG, padx=10, pady=8,
            highlightbackground=C_BORDER, highlightthickness=1,
        )
        filter_bar.pack(fill="x")

        tk.Label(filter_bar, text="Afficher :",
                 font=("Helvetica Neue", 11), fg=C_TEXT, bg=C_BG).pack(side="left")
        self._banque_filter = tk.StringVar(value="Tous")
        filter_cb = ttk.Combobox(
            filter_bar, textvariable=self._banque_filter,
            values=["Tous", "Restants", "Présentés"],
            width=12, state="readonly",
        )
        filter_cb.pack(side="left", padx=8)
        filter_cb.bind("<<ComboboxSelected>>", lambda _: self._refresh_banque())

        main = tk.Frame(parent, bg=C_BG)
        main.pack(fill="both", expand=True, padx=8, pady=8)

        lb_panel = tk.Frame(main, bg=C_BG)
        lb_panel.pack(side="left", fill="y")

        tk.Label(lb_panel, text="Stimuli",
                 font=("Helvetica Neue", 9), fg=C_TEXT_FAINT, bg=C_BG,
                 anchor="w").pack(anchor="w", pady=(0, 4))

        lb_border = tk.Frame(lb_panel, bg=C_BORDER, padx=1, pady=1)
        lb_border.pack(fill="y", expand=True)

        sb = tk.Scrollbar(lb_border)
        sb.pack(side="right", fill="y")

        self._banque_lb = tk.Listbox(
            lb_border, width=32, height=22,
            bg=C_BG_SECONDARY, fg=C_TEXT,
            selectbackground="#dbeafe",
            selectforeground="#1e3a5f",
            font=("Helvetica Neue", 10),
            relief="flat",
            yscrollcommand=sb.set,
        )
        self._banque_lb.pack(side="left", fill="y")
        sb.config(command=self._banque_lb.yview)
        self._banque_lb.bind("<<ListboxSelect>>", self._on_banque_select)

        preview = tk.Frame(main, bg=C_BG)
        preview.pack(side="left", fill="both", expand=True, padx=(12, 0))

        img_wrapper = tk.Frame(preview, bg=C_BG_DARK, padx=4, pady=4)
        img_wrapper.pack()

        self._banque_img_label = tk.Label(img_wrapper, bg=C_BG_DARK, width=36, height=20)
        self._banque_img_label.pack()
        self._banque_img_tk = None

        self._banque_name_lbl = tk.Label(
            preview, text="",
            font=("Helvetica Neue", 11, "bold"), fg=C_TEXT, bg=C_BG, wraplength=280,
        )
        self._banque_name_lbl.pack(pady=(8, 2))

        self._banque_status_lbl = tk.Label(
            preview, text="",
            font=("Helvetica Neue", 9), fg=C_TEXT_MUTED, bg=C_BG,
        )
        self._banque_status_lbl.pack()

    # ── Historique tab ────────────────────────────────────────────────────────

    def _build_historique_tab(self, parent: ttk.Frame) -> None:
        tree_frame = tk.Frame(parent, bg=C_BG)
        tree_frame.pack(fill="both", expand=True, padx=8, pady=(8, 2))

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

        self._hist_summary_lbl = tk.Label(
            parent, text="",
            font=("Helvetica Neue", 10), fg=C_TEXT, bg=C_BG_SECONDARY,
            justify="left", anchor="w", padx=8, pady=4,
        )
        self._hist_summary_lbl.pack(fill="x", padx=8, pady=(4, 0))

        tk.Frame(parent, bg=C_BORDER, height=1).pack(fill="x", padx=8, pady=(4, 0))

        ttk.Button(
            parent, text="Exporter CSV",
            command=self._export_historique,
        ).pack(pady=8)

    # ── Key bindings ──────────────────────────────────────────────────────────

    def _bind_keys(self) -> None:
        upper_seq = f"<{self._stim_key.upper()}>"
        try:
            self._root.bind(upper_seq, lambda e: self._cmd_stim_key())
        except tk.TclError:
            pass
        if len(self._stim_key) == 1:
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
        except Exception as exc:
            print(f"[WARN] _poll handle error: {exc}", flush=True)
        finally:
            if not self._session_ended:
                self._root.after(self.POLL_MS, self._poll)

        try:
            if self._image_on_ts is not None and not self._session_ended:
                self._elapsed_s = time.monotonic() - self._image_on_ts
                self._update_timer_display()
            self._update_stim_banner()
        except Exception:
            pass

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
            self._update_stats_display()
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
            print("[END] clinician received session_end (abort/emergency)")
            self._session_ended = True
            self._show_session_end_dialog(msg)

        elif t == "session_end_pending":
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
        pill_text = f"{self._trial_n} / {self._total_trials}"
        self._trial_pill.config(text=pill_text)
        self._tile_essai_val.config(text=pill_text)
        self._tile_attendue_val.config(text=self._correct_answer or "—")
        self._tile_resp_val.config(text="—", fg=C_TEXT)
        self._tile_stim_val.config(text=self._current_pid or "—")

    def _update_response_display(self) -> None:
        cr = self._last_correct
        if cr is True:
            colour = C_GREEN
            text   = f"{self._last_response}  ✓"
        elif cr is False:
            colour = C_RED
            text   = f"{self._last_response}  ✗"
        else:
            colour = C_TEXT_MUTED
            text   = self._last_response or "—"
        self._tile_resp_val.config(text=text, fg=colour)

    def _update_stats_display(self) -> None:
        pct = (
            round(self._n_correct / self._n_total * 100, 1)
            if self._n_total > 0 else 0.0
        )
        pct_color = C_GREEN if pct >= 70 else (C_AMBER if pct >= 40 else C_RED)
        self._chip_total_val.config(text=str(self._n_total), fg=C_TEXT)
        self._chip_correct_val.config(
            text=str(self._n_correct),
            fg=C_GREEN if self._n_total else C_TEXT,
        )
        self._chip_skipped_val.config(text=str(self._n_skipped), fg=C_TEXT)
        self._chip_pct_val.config(text=f"{pct}%", fg=pct_color)

    def _update_timer_display(self) -> None:
        if self._image_on_ts is None:
            self._timer_lbl.config(text="")
            self._timer_pill.config(text="0.0s")
            return
        t_str = f"{self._elapsed_s:.1f}s"
        if self._remaining_s is not None:
            full_str = f"{t_str}  ▸  {self._remaining_s:.1f}s restant"
        else:
            full_str = t_str
        self._timer_lbl.config(text=full_str)
        self._timer_pill.config(text=t_str)
        self._tile_temps_val.config(text=t_str)
        try:
            w = self._timer_canvas.winfo_width()
            if w > 1 and self._remaining_s is not None:
                total = self._elapsed_s + self._remaining_s
                if total > 0:
                    frac = min(1.0, self._elapsed_s / total)
                    self._timer_canvas.delete("all")
                    self._timer_canvas.create_rectangle(
                        0, 0, int(w * frac), 3, fill=C_BLUE, outline="",
                    )
        except Exception:
            pass

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
            self._img_label.config(image="", text=f"[{name}]", fg=FG_LIGHT, bg=C_BG_DARK)

    def _update_stim_banner(self) -> None:
        try:
            if self._stim_on:
                elapsed   = time.monotonic() - self._stim_start_ts if self._stim_start_ts else 0
                remaining = max(0.0, self._stim_duration - elapsed)
                elec = self._electrode.get() or "?"
                cont = self._contact.get()   or "?"
                mA   = self._intensity.get() or "?"
                dur  = self._duration.get()  or "?"
                text = (
                    f"  ■  STIMULATION EN COURS  —  {elec}-{cont} | {mA}mA | {dur}s"
                    f"  |  ▼ {remaining:.1f}s"
                )
                self._stim_banner.config(text=text, bg=C_STIM_ON_BG, fg=C_STIM_ON_FG)
            else:
                self._stim_banner.config(
                    text="  STIMULATION OFF", bg=C_STIM_OFF_BG, fg=C_STIM_OFF_FG,
                )
        except Exception as exc:
            print(f"[WARN] _update_stim_banner: {exc}", flush=True)

    def _toggle_params(self) -> None:
        if self._params_collapsed:
            self._params_frame.pack(fill="x", padx=8, pady=(0, 8))
            self._params_toggle_btn.config(text="▼  PARAMÈTRES DE STIMULATION")
        else:
            self._params_frame.pack_forget()
            self._params_toggle_btn.config(text="▶  PARAMÈTRES DE STIMULATION")
        self._params_collapsed = not self._params_collapsed

    # ── Banque helpers ────────────────────────────────────────────────────────

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

        self._banque_lb_stimuli = stimuli

    def _on_banque_select(self, _event=None) -> None:
        sel = self._banque_lb.curselection()
        if not sel or not hasattr(self, "_banque_lb_stimuli"):
            return
        idx = sel[0]
        if idx >= len(self._banque_lb_stimuli):
            return
        s = self._banque_lb_stimuli[idx]

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
                self._banque_img_label.config(image="", text=f"[{pid}]", fg=FG_LIGHT, bg=C_BG_DARK)

    # ── Historique helpers ────────────────────────────────────────────────────

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

    # ── Finaliser dialog (natural session end) ────────────────────────────────

    def _show_finalise_dialog(self, msg: dict) -> None:
        n_total    = msg.get("n_total",    self._n_total)
        n_correct  = msg.get("n_correct",  self._n_correct)
        patient_id = msg.get("patient_id", "—")
        task_name  = msg.get("task_display_name", self._task_display)

        dlg = tk.Toplevel(self._root)
        dlg.title("Finaliser la session")
        dlg.configure(bg=C_BG)
        dlg.resizable(False, False)
        dlg.minsize(480, 1)
        self._finalise_dlg = dlg
        dlg.transient(self._root)
        # No grab_set() — causes Text widget focus loss / dialog destruction on macOS.
        # Controls in the root window are already disabled; lift() keeps dialog on top.
        dlg.lift()
        dlg.attributes("-topmost", True)
        dlg.focus_force()
        dlg.update()

        PAD = 24

        # Data-safe banner — files written before this dialog was shown
        tk.Label(
            dlg, text="✓  Données sauvegardées",
            font=F_BOLD, fg=C_GREEN, bg=C_BG,
        ).pack(pady=(16, 2))

        tk.Label(dlg, text="Finaliser la session",
                 font=F_TITLE, fg=C_TEXT, bg=C_BG).pack(pady=(0, 4))

        subtitle = (
            f"Patient : {patient_id}  —  {task_name}  "
            f"—  {n_total} essais  —  {n_correct} corrects"
        )
        tk.Label(dlg, text=subtitle,
                 font=("Helvetica Neue", 10), fg=C_TEXT_MUTED, bg=C_BG,
                 wraplength=440).pack(fill="x", padx=PAD)

        tk.Frame(dlg, bg=C_BORDER, height=1).pack(fill="x", padx=PAD, pady=12)

        tk.Label(dlg, text="Notes clinicien (optionnel)",
                 font=("Helvetica Neue", 11, "bold"), fg=C_TEXT, bg=C_BG,
                 anchor="w").pack(fill="x", padx=PAD)

        notes_box = tk.Text(dlg, width=52, height=3, wrap="word",
                            font=F_BODY,
                            bg=C_BG_SECONDARY, fg=C_TEXT, relief="flat",
                            highlightbackground=C_BORDER, highlightthickness=1,
                            padx=4, pady=4)
        notes_box.pack(fill="x", padx=PAD, pady=(4, 2))

        tk.Label(
            dlg,
            text='Ex : "Patient fatigué", "Stimulation non tolérée", "Essai 12 interrompu"',
            font=("Helvetica Neue", 9), fg=C_TEXT_FAINT, bg=C_BG,
            anchor="w", justify="left",
        ).pack(fill="x", padx=PAD, pady=(0, 12))

        tk.Frame(dlg, bg=C_BORDER, height=1).pack(fill="x", padx=PAD, pady=(0, 10))

        status_lbl = tk.Label(dlg, text="", font=("Helvetica Neue", 10),
                               fg=C_TEXT_MUTED, bg=C_BG)
        status_lbl.pack()

        btn_frame = tk.Frame(dlg, bg=C_BG)
        btn_frame.pack(pady=(8, 20))

        save_btn = tk.Button(
            btn_frame, text="Sauvegarder et fermer",
            bg=C_NAVY, fg="white", font=F_BOLD,
            relief="flat", padx=20, pady=10, cursor="hand2",
        )
        abandon_btn = tk.Button(
            btn_frame, text="Abandonner la session",
            bg=C_BG, fg=C_RED,
            font=("Helvetica Neue", 11),
            relief="flat", highlightbackground="#fca5a5", highlightthickness=1,
            padx=12, pady=8, cursor="hand2",
        )
        save_btn.pack(side="left", padx=8)
        abandon_btn.pack(side="left", padx=8)

        def _do_save():
            notes = notes_box.get("1.0", "end-1c").strip()
            save_btn.config(state="disabled")
            abandon_btn.config(state="disabled")
            status_lbl.config(text="Enregistrement des notes…")
            dlg.update_idletasks()
            self._send({"type": "finalize_save", "notes": notes})

        def _do_abandon():
            conf_dlg = tk.Toplevel(dlg)
            conf_dlg.title("Confirmer abandon")
            conf_dlg.configure(bg=C_BG)
            conf_dlg.resizable(False, False)
            conf_dlg.transient(dlg)
            conf_dlg.grab_set()
            conf_dlg.lift()
            conf_dlg.attributes("-topmost", True)
            conf_dlg.focus_force()
            conf_dlg.update()

            tk.Label(conf_dlg,
                     text="Les données ne seront PAS sauvegardées.",
                     fg=C_TEXT, bg=C_BG, font=("Helvetica Neue", 12, "bold")).pack(padx=20, pady=(16, 6))
            tk.Label(conf_dlg, text="Confirmer l'abandon ?",
                     fg=C_TEXT_MUTED, bg=C_BG, font=("Helvetica Neue", 11)).pack(padx=20, pady=(0, 12))

            confirmed = []
            b = tk.Frame(conf_dlg, bg=C_BG)
            b.pack(pady=(0, 16))
            tk.Button(b, text="Oui, abandonner",
                      command=lambda: [confirmed.append(True), conf_dlg.destroy()],
                      bg=C_BG, fg=C_RED, font=("Helvetica Neue", 11),
                      relief="flat", highlightbackground="#fca5a5", highlightthickness=1,
                      padx=10, pady=5, cursor="hand2").pack(side="left", padx=8)
            tk.Button(b, text="Annuler", command=conf_dlg.destroy,
                      bg=C_BG_SECONDARY, fg=C_TEXT, font=("Helvetica Neue", 11),
                      relief="flat", highlightbackground=C_BORDER, highlightthickness=1,
                      padx=10, pady=5, cursor="hand2").pack(side="left", padx=8)

            conf_dlg.grab_set()
            dlg.wait_window(conf_dlg)

            if confirmed:
                save_btn.config(state="disabled")
                abandon_btn.config(state="disabled")
                status_lbl.config(text="Session abandonnée…")
                dlg.update_idletasks()
                self._send({"type": "finalize_abandon"})

        save_btn.config(command=_do_save)
        abandon_btn.config(command=_do_abandon)
        # Closing via the window X button is equivalent to "Sauvegarder et fermer"
        # (data already safe; this just appends any typed notes).
        dlg.protocol("WM_DELETE_WINDOW", _do_save)

    # ── Session end dialog ────────────────────────────────────────────────────

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

        n_pre  = msg.get("n_trials_pre",    0)
        ok_pre = msg.get("n_correct_pre",   0)
        tr_pre = msg.get("mean_TR_pre")
        n_per  = msg.get("n_trials_per",    0)
        ok_per = msg.get("n_correct_per",   0)
        tr_per = msg.get("mean_TR_per")
        n_lim  = msg.get("n_trials_limite", 0)
        ok_lim = msg.get("n_correct_limite",0)
        tr_lim = msg.get("mean_TR_limite")
        n_post = msg.get("n_trials_post",   0)
        ok_post= msg.get("n_correct_post",  0)
        tr_post= msg.get("mean_TR_post")

        now      = datetime.datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M")

        dlg = tk.Toplevel(self._root)
        dlg.title("Session terminée")
        dlg.configure(bg=C_BG)
        dlg.resizable(False, False)
        dlg.minsize(520, 1)
        dlg.transient(self._root)
        dlg.grab_set()
        dlg.lift()
        dlg.attributes("-topmost", True)
        dlg.focus_force()
        dlg.update()

        PAD = 24

        tk.Label(
            dlg, text="Session terminée",
            font=F_TITLE, fg=C_TEXT, bg=C_BG,
        ).pack(fill="x", pady=(20, 4))

        subtitle = f"Patient : {patient_id}  |  Tâche : {task_name}  |  {date_str}  {time_str}"
        tk.Label(
            dlg, text=subtitle,
            font=F_SMALL, fg=C_TEXT_2, bg=C_BG,
            wraplength=460,
        ).pack(fill="x", padx=PAD)

        tk.Frame(dlg, bg=C_BORDER, height=1).pack(fill="x", padx=PAD, pady=12)

        # ── Stats block ───────────────────────────────────────────────────────
        pct = round(n_correct / n_total * 100, 1) if n_total else 0.0
        if pct >= 70:
            pct_color = C_GREEN
        elif pct >= 40:
            pct_color = ORANGE
        else:
            pct_color = C_RED

        res_frame = tk.Frame(dlg, bg=C_BG)
        res_frame.pack(fill="x", padx=PAD, pady=(0, 8))
        for col in range(3):
            res_frame.columnconfigure(col, weight=1, uniform="res")

        for col, hdr in enumerate(["Essais", "Corrects", "TR moyen"]):
            tk.Label(res_frame, text=hdr,
                     font=("Helvetica Neue", 10), fg=C_TEXT_FAINT, bg=C_BG,
                     anchor="center").grid(row=0, column=col, sticky="ew")

        tr_str = f"{mean_tr:.2f} s" if mean_tr is not None else "—"
        tk.Label(res_frame, text=str(n_total),
                 font=("Menlo", 22, "bold"), fg=C_TEXT, bg=C_BG,
                 anchor="center").grid(row=1, column=0, sticky="ew")

        correct_inner = tk.Frame(res_frame, bg=C_BG)
        correct_inner.grid(row=1, column=1, sticky="ew")
        tk.Label(correct_inner, text=f"{n_correct} ",
                 font=("Menlo", 22, "bold"), fg=C_TEXT, bg=C_BG).pack(side="left", expand=True, anchor="e")
        tk.Label(correct_inner, text=f"({pct}%)",
                 font=("Helvetica Neue", 13), fg=pct_color, bg=C_BG).pack(side="left", anchor="s", pady=5)

        tk.Label(res_frame, text=tr_str,
                 font=("Menlo", 22, "bold"), fg=C_TEXT, bg=C_BG,
                 anchor="center").grid(row=1, column=2, sticky="ew")

        tk.Frame(dlg, bg=C_BORDER, height=1).pack(fill="x", padx=PAD, pady=(4, 10))

        # ── Stimulation epoch table ───────────────────────────────────────────
        if n_stim_events > 0:
            s_label = "s" if n_stim_events != 1 else ""
            tk.Label(
                dlg, text=f"Stimulations : {n_stim_events} événement{s_label}",
                font=("Helvetica Neue", 11, "bold"), fg=C_TEXT, bg=C_BG, anchor="w",
            ).pack(fill="x", padx=PAD, pady=(0, 6))

            tbl = tk.Frame(dlg, bg=C_BG)
            tbl.pack(fill="x", padx=PAD, pady=(0, 10))
            for col in range(3):
                tbl.columnconfigure(col, weight=1, uniform="tbl")

            for col, hdr in enumerate(["", "Corrects", "TR moyen"]):
                tk.Label(tbl, text=hdr,
                         font=("Helvetica Neue", 10, "bold"), fg=C_TEXT_MUTED, bg=C_BG_SECONDARY,
                         padx=6, pady=3, anchor="center",
                         relief="groove").grid(row=0, column=col, sticky="ew", padx=1, pady=1)

            def _pct_str(n, ok):
                if not n:
                    return "—"
                return f"{ok}/{n}  ({round(ok/n*100, 1)}%)"

            def _tr_fmt(tr):
                return f"{tr:.2f} s" if tr is not None else "—"

            for ri, (label, n, ok, tr, color, row_bg) in enumerate([
                ("Pré-stim",    n_pre,  ok_pre,  tr_pre,  C_TEXT,   C_BG),
                ("Per-stim",    n_per,  ok_per,  tr_per,  C_RED,    "#fff5f5"),
                ("Limite stim", n_lim,  ok_lim,  tr_lim,  C_AMBER,  "#fffbf0"),
                ("Post-stim",   n_post, ok_post, tr_post, C_BLUE,   "#f0f7ff"),
            ], start=1):
                for col, (txt, anc) in enumerate([
                    (label,              "w"),
                    (_pct_str(n, ok),    "center"),
                    (_tr_fmt(tr),        "center"),
                ]):
                    tk.Label(tbl, text=txt,
                             font=("Helvetica Neue", 11), fg=color, bg=row_bg,
                             padx=6, pady=3, anchor=anc,
                             relief="groove").grid(row=ri, column=col, sticky="ew", padx=1, pady=1)

        # ── File line ─────────────────────────────────────────────────────────
        if csv_path:
            stem = Path(csv_path).stem
            file_row = tk.Frame(dlg, bg=C_BG)
            file_row.pack(fill="x", padx=PAD, pady=(0, 8))

            tk.Label(file_row, text=f"Fichier sauvegardé : {stem}",
                     font=("Menlo", 9), fg=C_TEXT_FAINT, bg=C_BG,
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
                      bg=C_BG_SECONDARY, fg=C_BLUE, font=("Helvetica Neue", 9),
                      relief="flat", highlightbackground=C_BORDER, highlightthickness=1,
                      padx=6, pady=2, cursor="hand2").pack(side="right")

        # ── Close buttons ─────────────────────────────────────────────────────
        tk.Frame(dlg, bg=C_BORDER, height=1).pack(fill="x", padx=PAD, pady=(4, 8))

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

        btn_row = tk.Frame(dlg, bg=C_BG)
        btn_row.pack(pady=(0, 16))
        tk.Button(
            btn_row, text="Fermer et revenir à l'accueil",
            command=_close,
            bg=C_BG_SECONDARY, fg=C_TEXT, font=("Helvetica Neue", 11),
            relief="flat", highlightbackground=C_BORDER, highlightthickness=1,
            padx=12, pady=8, cursor="hand2",
        ).pack(side="left", padx=6)
        tk.Button(
            btn_row, text="Quitter",
            command=_quit,
            bg=C_BG, fg=C_RED, font=("Helvetica Neue", 11),
            relief="flat", highlightbackground="#fca5a5", highlightthickness=1,
            padx=12, pady=8, cursor="hand2",
        ).pack(side="left", padx=6)

    # ── Clinician commands ────────────────────────────────────────────────────

    def _send(self, msg: dict) -> None:
        try:
            self._to_q.put_nowait(msg)
        except Exception as exc:
            print(f"[WARN] clinician send failed: {exc}", flush=True)

    def _cmd_skip(self) -> None:
        self._send({"type": "skip"})

    def _cmd_exclude(self) -> None:
        self._send({"type": "exclude"})

    def _cmd_replace(self) -> None:
        if not self._remaining_stimuli:
            messagebox.showinfo("Remplacer", "Aucun stimulus disponible pour le remplacement.")
            return

        dlg = tk.Toplevel(self._root)
        dlg.title("Remplacer le stimulus actuel")
        dlg.configure(bg=C_BG)
        dlg.transient(self._root)
        dlg.grab_set()
        dlg.lift()
        dlg.attributes("-topmost", True)
        dlg.focus_force()
        dlg.update()

        tk.Label(
            dlg, text="Sélectionnez le stimulus de remplacement:",
            fg=C_TEXT, bg=C_BG, font=("Helvetica Neue", 11),
        ).pack(padx=12, pady=(10, 4))

        lb_frame = tk.Frame(dlg, bg=C_BG)
        lb_frame.pack(padx=12, fill="both", expand=True)

        sb = tk.Scrollbar(lb_frame)
        sb.pack(side="right", fill="y")

        lb = tk.Listbox(
            lb_frame, width=40, height=14,
            bg=C_BG_SECONDARY, fg=C_TEXT,
            selectbackground="#dbeafe",
            selectforeground="#1e3a5f",
            font=("Helvetica Neue", 10),
            relief="flat",
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

        btn_frame = tk.Frame(dlg, bg=C_BG)
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
        if self._session_ended:
            self._root.destroy()
            return

        confirmed = []

        dlg = tk.Toplevel(self._root)
        dlg.title("Arrêter la session")
        dlg.configure(bg=C_BG)
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
            fg=C_TEXT, bg=C_BG, font=("Helvetica Neue", 13, "bold"),
            wraplength=340,
        ).pack(padx=24, pady=(20, 6))

        tk.Label(
            dlg,
            text="Les données seront sauvegardées.",
            fg=C_TEXT_MUTED, bg=C_BG, font=("Helvetica Neue", 11),
        ).pack(padx=24, pady=(0, 16))

        btn_frame = tk.Frame(dlg, bg=C_BG)
        btn_frame.pack(pady=(0, 16))

        tk.Button(
            btn_frame, text="Oui, arrêter",
            command=lambda: [confirmed.append(True), dlg.destroy()],
            bg=C_BG, fg=C_RED, font=("Helvetica Neue", 11),
            relief="flat", highlightbackground="#fca5a5", highlightthickness=1,
            padx=12, pady=6, cursor="hand2",
        ).pack(side="left", padx=8)

        tk.Button(
            btn_frame, text="Annuler",
            command=dlg.destroy,
            bg=C_BG_SECONDARY, fg=C_TEXT, font=("Helvetica Neue", 11),
            relief="flat", highlightbackground=C_BORDER, highlightthickness=1,
            padx=12, pady=6, cursor="hand2",
        ).pack(side="left", padx=8)

        dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
        dlg.grab_set()
        self._root.wait_window(dlg)

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
        if not self._session_active:
            return
        try:
            self._send({"type": "stim_key"})
        except Exception as exc:
            print(f"[WARN] _cmd_stim_key: {exc}", flush=True)

    def _cmd_di_correct(self) -> None:
        if self._task_code == "DI_SEEG":
            self._send({"type": "di_correct"})

    def _cmd_di_incorrect(self) -> None:
        if self._task_code == "DI_SEEG":
            self._send({"type": "di_incorrect"})

    def _cmd_annotate(self) -> None:
        text = self._annot_entry.get().strip()
        if not text:
            return
        self._send({"type": "annotate", "text": text})
        self._annot_entry.delete(0, "end")
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
    patient_id: str = "",
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
        patient_id=patient_id,
    )
    app._electrode.set(electrode)
    app._contact.set(contact)
    app._intensity.set(str(intensity_ma))
    app._duration.set(str(duration_s))
    app._root.lift()
    app._root.attributes("-topmost", True)
    app._root.update()
    app.run()

    for _q in (from_patient_q, to_patient_q):
        try:
            _q.cancel_join_thread()
            _q.close()
        except Exception:
            pass
