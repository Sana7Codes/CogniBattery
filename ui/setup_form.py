"""
Session setup form — clinician screen, pre-session.

Displays a tkinter form that collects all session parameters before the
patient window opens.  Blocks until the clinician clicks "Start Session"
or closes the window.

Returns a dict with all session configuration, or None if cancelled.
"""

from __future__ import annotations

import datetime
import random
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox
from typing import Optional, Any

from tasks.csv_loader import load_trials, task_folder, TASK_FOLDERS
from core.stimulus import Stimulus

# ── Design tokens ─────────────────────────────────────────────────────────────

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

F_BODY   = ("Helvetica Neue", 12)
F_SMALL  = ("Helvetica Neue", 9)
F_BOLD   = ("Helvetica Neue", 12, "bold")
F_MONO   = ("Menlo", 13, "bold")
F_MONO_L = ("Menlo", 15)

# ── Task display names ────────────────────────────────────────────────────────

TASK_DISPLAY_NAMES: dict[str, str] = {
    "FFP_V1":   "Visages célèbres – pointage V1",
    "FFP_V2":   "Visages célèbres – pointage V2",
    "MUF_V1":   "Appariement visages inconnus V1",
    "MUF_V2":   "Appariement visages inconnus V2",
    "ASM_MOTS": "Appariement sémantique – mots",
    "ASM_SEEG": "Appariement sémantique – SEEG sans déno V2",
    "DI_SEEG":  "Dénomination d'images SEEG 2024",
    "FNP":      "Noms célèbres – pointage",
}

_FFP_TASKS = ("FFP_V1", "FFP_V2")


# ── Main form ─────────────────────────────────────────────────────────────────

class SetupForm:
    """
    Modal tkinter form for session configuration.
    Call run() to show it; returns config dict when complete or None if cancelled.
    """

    def __init__(
        self,
        presets: dict | None = None,
        prev_session_info: dict | None = None,
    ) -> None:
        self.result: dict | None = None
        self._presets = presets or {}
        self._prev_session_info = prev_session_info
        self._time_confirmed = False
        self._stim_vars: dict[str, tk.BooleanVar] = {}
        self._stim_rows: list[dict] = []

        self._familiarity_done: bool = False
        self._familiarity_kept: list[Stimulus] = []
        self._familiarity_excluded_ids: list[str] = []

        self._root: tk.Tk | None = None
        self._banner_frame: tk.Frame | None = None
        self._banner_prev_patient: str | None = None

    def run(self) -> dict | None:
        self._root = tk.Tk()
        self._root.title("Battery — Configuration de session")
        self._root.resizable(False, False)
        self._root.configure(bg=C_BG)
        self._root.minsize(960, 680)
        self._build_ui()
        self._root.mainloop()
        return self.result

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = self._root

        # ── Previous-session banner ───────────────────────────────────────────
        psi = self._prev_session_info
        if psi is not None:
            self._banner_prev_patient = psi.get("patient_id", "")
            stem  = psi.get("filename_stem") or Path(psi.get("csv_path", "")).stem or "—"
            n     = psi.get("n_trials", psi.get("n_total", 0))
            ok    = psi.get("n_correct", 0)
            task  = psi.get("task_display_name", psi.get("task", "—"))

            _BG_BAN = "#e8f0fc"
            _FG_BAN = "#1a4a9e"
            self._banner_frame = tk.Frame(root, bg="#c5d7f7", padx=1, pady=1)
            self._banner_frame.grid(row=0, column=0, columnspan=2,
                                    sticky="ew", padx=12, pady=(10, 0))
            _inner = tk.Frame(self._banner_frame, bg=_BG_BAN, pady=10, padx=16)
            _inner.pack(fill="x")
            tk.Label(
                _inner,
                text=f"Session précédente : {task} — {n} essais, {ok} corrects",
                font=F_BOLD, fg=_FG_BAN, bg=_BG_BAN, anchor="w",
            ).pack(fill="x")
            tk.Label(
                _inner, text=f"Fichier : {stem}",
                font=F_SMALL, fg=_FG_BAN, bg=_BG_BAN, anchor="w",
            ).pack(fill="x")

        _content_row = 1 if self._banner_frame else 0

        # ── Widget helpers ────────────────────────────────────────────────────
        def _lbl(parent, text, row):
            tk.Label(
                parent, text=text,
                bg=C_BG, fg=C_TEXT_MUTED, font=F_SMALL, anchor="w",
            ).grid(row=row, column=0, sticky="w", pady=(8, 0), padx=(0, 8))

        def _entry(parent, var, row, width=18):
            e = tk.Entry(
                parent, textvariable=var, width=width,
                bg=C_BG_SECONDARY, fg=C_TEXT, font=F_BODY,
                insertbackground=C_TEXT, relief="flat",
                highlightbackground=C_BORDER, highlightthickness=1,
            )
            e.grid(row=row, column=1, sticky="w", pady=(8, 0), padx=(8, 0))
            return e

        # ── Left column ───────────────────────────────────────────────────────
        left = tk.Frame(root, bg=C_BG, padx=16, pady=12)
        left.grid(row=_content_row, column=0, sticky="nsew")

        # Patient ID
        _lbl(left, "Patient ID *", 0)
        self._patient_id = tk.StringVar(value=self._presets.get("patient_id", ""))
        self._patient_id.trace_add("write", self._on_patient_id_changed)
        _entry(left, self._patient_id, 0)

        # Date/time
        _lbl(left, "Date / Heure *", 1)
        now = datetime.datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
        self._time_label = tk.Label(
            left, text=now,
            bg=C_BG, fg=C_BLUE, font=F_MONO_L, anchor="w",
        )
        self._time_label.grid(row=1, column=1, sticky="w", pady=(8, 0), padx=(8, 0))
        self._update_clock()

        self._confirm_time_btn = tk.Button(
            left, text="Heure correcte — continuer",
            command=self._confirm_time,
            bg=C_BG_SECONDARY, fg=C_TEXT, font=F_BODY,
            relief="flat",
            highlightbackground=C_BORDER, highlightthickness=1,
            padx=12, pady=4, cursor="hand2",
        )
        self._confirm_time_btn.grid(row=2, column=0, columnspan=2, pady=(6, 0), sticky="w")

        # Task
        _lbl(left, "Tâche *", 3)
        self._task_code = tk.StringVar(value=self._presets.get("task_code", list(TASK_FOLDERS.keys())[0]))
        task_cb = ttk.Combobox(
            left, textvariable=self._task_code, width=35,
            values=list(TASK_FOLDERS.keys()), state="readonly",
        )
        task_cb.grid(row=3, column=1, sticky="w", pady=(8, 0), padx=(8, 0))
        task_cb.bind("<<ComboboxSelected>>", self._on_task_changed)

        # Electrode
        _lbl(left, "Électrode *", 4)
        self._electrode = tk.StringVar(value=self._presets.get("electrode", ""))
        self._electrode.trace_add("write", lambda *_: self._update_start_state())
        _entry(left, self._electrode, 4, width=10)

        # Contact
        _lbl(left, "Contact *", 5)
        self._contact = tk.StringVar(value=self._presets.get("contact", ""))
        self._contact.trace_add("write", lambda *_: self._update_start_state())
        _entry(left, self._contact, 5, width=10)

        # Intensity
        _lbl(left, "Intensité (mA) *", 6)
        self._intensity = tk.StringVar(value=self._presets.get("intensity", "1.0"))
        _entry(left, self._intensity, 6, width=10)

        # Duration
        _lbl(left, "Durée stim (s) *", 7)
        self._duration = tk.StringVar(value=self._presets.get("duration", "3.0"))
        _entry(left, self._duration, 7, width=10)

        # Progression mode
        _lbl(left, "Mode progression *", 8)
        self._prog_mode = tk.StringVar(value=self._presets.get("progression_mode", "PatientTouch"))
        prog_cb = ttk.Combobox(
            left, textvariable=self._prog_mode, width=20,
            values=["PatientTouch", "ClinicianAction", "Timer"], state="readonly",
        )
        prog_cb.grid(row=8, column=1, sticky="w", pady=(8, 0), padx=(8, 0))
        prog_cb.bind("<<ComboboxSelected>>", self._on_prog_changed)

        # Timer delay
        _lbl(left, "Délai timer (s)", 9)
        self._timer_delay = tk.StringVar(value=self._presets.get("timer_delay", "5.0"))
        self._timer_entry = _entry(left, self._timer_delay, 9, width=10)
        self._on_prog_changed()

        # Stim key
        _lbl(left, "Touche STIM", 10)
        self._stim_key = tk.StringVar(value=self._presets.get("stim_key", "f12"))
        _entry(left, self._stim_key, 10, width=10)

        self._stim_reminder = tk.Label(
            left,
            text="⌨  Cette touche déclenche la stimulation en session.",
            bg=C_BG, fg=C_TEXT_FAINT, font=F_SMALL, anchor="w",
        )
        self._stim_reminder.grid(row=11, column=0, columnspan=2, sticky="w", pady=(2, 0))

        # Familiarity precheck (FFP only)
        self._precheck_btn = tk.Button(
            left, text="Vérification de familiarité…",
            command=self._do_precheck,
            bg=C_BG_SECONDARY, fg=C_TEXT, font=F_BODY,
            relief="flat", highlightbackground=C_BORDER, highlightthickness=1,
            padx=12, pady=4, cursor="hand2",
        )
        self._precheck_btn.grid(row=12, column=0, columnspan=2, pady=(8, 2), sticky="w")

        self._precheck_status = tk.Label(
            left, text="",
            bg=C_BG, fg=C_TEXT_MUTED, font=F_SMALL,
        )
        self._precheck_status.grid(row=13, column=0, columnspan=2, sticky="w")

        if self._task_code.get() not in _FFP_TASKS:
            self._precheck_btn.grid_remove()
            self._precheck_status.grid_remove()

        # Order
        _lbl(left, "Ordre stimuli", 14)
        self._order = tk.StringVar(value=self._presets.get("order", "random"))
        order_frame = tk.Frame(left, bg=C_BG)
        order_frame.grid(row=14, column=1, sticky="w", pady=(8, 0), padx=(8, 0))
        for text, val in [("Aléatoire", "random"), ("Fixe", "fixed")]:
            tk.Radiobutton(
                order_frame, text=text,
                variable=self._order, value=val,
                bg=C_BG, fg=C_TEXT, font=F_BODY,
                activebackground=C_BG_SECONDARY, selectcolor=C_BG,
                relief="flat",
            ).pack(side="left", padx=(0, 12))

        # Start + Quit
        btn_bar = tk.Frame(left, bg=C_BG)
        btn_bar.grid(row=15, column=0, columnspan=2, pady=(20, 0), sticky="w")

        self._start_btn = tk.Button(
            btn_bar, text="Démarrer la session ▶",
            command=self._on_start,
            bg=C_NAVY, fg="white", font=F_BOLD,
            relief="flat", activebackground="#2a3d6e", activeforeground="white",
            padx=24, pady=10, cursor="hand2",
            state="disabled",
        )
        self._start_btn.pack(side="left")

        self._status_label = tk.Label(
            left, text="⚠  Confirmez l'heure pour continuer.",
            bg=C_BG, fg=C_RED, font=F_SMALL,
        )
        self._status_label.grid(row=16, column=0, columnspan=2, sticky="w", pady=(6, 0))

        tk.Button(
            left, text="Quitter",
            command=self._on_quit,
            bg=C_BG, fg=C_TEXT_MUTED, font=F_BODY,
            relief="flat",
            highlightbackground=C_BORDER, highlightthickness=1,
            padx=16, pady=8, cursor="hand2",
        ).grid(row=17, column=0, columnspan=2, pady=(10, 4), sticky="w")

        # ── Right column: stimulus list ───────────────────────────────────────
        right = tk.Frame(
            root, bg=C_BG, padx=8, pady=12,
            highlightbackground=C_BORDER, highlightthickness=1,
        )
        right.grid(row=_content_row, column=1, sticky="nsew", padx=(0, 12), pady=12)

        self._cb_label = tk.Label(
            right, text="",
            bg=C_BG, fg=C_TEXT_MUTED, font=F_MONO, anchor="w",
        )
        self._cb_label.pack(anchor="w", pady=(0, 6))

        canvas = tk.Canvas(
            right, width=360, height=480,
            bg=C_BG, highlightthickness=0,
        )
        sb = ttk.Scrollbar(right, orient="vertical", command=canvas.yview)
        self._stim_inner = tk.Frame(canvas, bg=C_BG)
        self._stim_inner.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=self._stim_inner, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        btn_row = tk.Frame(right, bg=C_BG)
        btn_row.pack(fill="x", pady=(6, 0))
        for text, cmd in [
            ("Tout sélectionner",   self._select_all),
            ("Tout désélectionner", self._deselect_all),
        ]:
            tk.Button(
                btn_row, text=text, command=cmd,
                bg=C_BG_SECONDARY, fg=C_TEXT, font=F_SMALL,
                relief="flat", highlightbackground=C_BORDER, highlightthickness=1,
                padx=8, pady=3, cursor="hand2",
            ).pack(side="left", padx=(0, 4))

        self._load_stimuli()

    # ── Clock ─────────────────────────────────────────────────────────────────

    def _update_clock(self) -> None:
        if self._root and not self._time_confirmed:
            now = datetime.datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
            self._time_label.config(text=now)
            self._root.after(1000, self._update_clock)

    def _confirm_time(self) -> None:
        self._time_confirmed = True
        self._confirm_time_btn.config(
            state="disabled", text="✓ Heure confirmée",
            bg="#e0f4e8", fg="#1a6b3a",
            relief="flat", padx=8, pady=3,
            highlightthickness=0,
        )
        self._update_start_state()

    # ── Stimulus list ─────────────────────────────────────────────────────────

    def _load_stimuli(self) -> None:
        for w in self._stim_inner.winfo_children():
            w.destroy()
        self._stim_vars.clear()
        self._stim_rows.clear()

        task_code = self._task_code.get()
        try:
            rows = load_trials(task_code)
        except Exception as exc:
            tk.Label(
                self._stim_inner, text=f"Erreur: {exc}",
                bg=C_BG, fg=C_RED, font=F_BODY,
            ).pack()
            return

        folder = task_folder(task_code)
        stimuli = [Stimulus(task_code, row, folder) for row in rows]
        self._stim_rows = rows

        for stim in stimuli:
            var = tk.BooleanVar(value=True)
            self._stim_vars[stim.planche_id] = var

            label = getattr(stim, "stimulus_label", None) or stim.planche_id
            if label and label != stim.planche_id:
                display_text = f"{label}  [{stim.planche_id}]"
            else:
                display_text = stim.planche_id

            tk.Checkbutton(
                self._stim_inner,
                text=display_text,
                variable=var,
                command=self._on_stim_selection_changed,
                bg=C_BG, fg=C_TEXT, font=F_BODY,
                selectcolor=C_BG, activebackground=C_BG_SECONDARY,
                relief="flat", anchor="w",
            ).pack(anchor="w")

        self._update_cb_label()

    def _update_cb_label(self) -> None:
        if not self._stim_vars:
            return
        task_code = self._task_code.get()
        folder = task_folder(task_code)
        selected = [pid for pid, var in self._stim_vars.items() if var.get()]

        left_n = center_n = right_n = 0
        for row in self._stim_rows:
            pid = Path(row["filename"]).stem
            if pid not in selected:
                continue
            stim = Stimulus(task_code, row, folder)
            cr = getattr(stim, "correct_response", None)
            if cr == "left":
                left_n += 1
            elif cr == "center":
                center_n += 1
            elif cr == "right":
                right_n += 1

        total = len(selected)
        if left_n + center_n + right_n > 0:
            parts = [f"{total} stimuli sélectionnés"]
            if left_n > 0:
                parts.append(f"Gauche: {left_n}")
            if center_n > 0:
                parts.append(f"Centre: {center_n}")
            if right_n > 0:
                parts.append(f"Droite: {right_n}")
            cb_text = "   |   ".join(parts)
        else:
            cb_text = f"{total} stimuli sélectionnés"
        self._cb_label.config(text=cb_text)

    def _on_stim_selection_changed(self) -> None:
        self._update_cb_label()
        if self._familiarity_done:
            self._familiarity_done = False
            self._familiarity_kept = []
            self._familiarity_excluded_ids = []
            self._precheck_btn.config(text="Vérification de familiarité…")
            self._precheck_status.config(
                text="Sélection modifiée — relancez la vérification.",
                fg=C_RED,
            )
            self._update_start_state()

    def _select_all(self) -> None:
        for var in self._stim_vars.values():
            var.set(True)
        self._on_stim_selection_changed()

    def _deselect_all(self) -> None:
        for var in self._stim_vars.values():
            var.set(False)
        self._on_stim_selection_changed()

    # ── Familiarity pre-check (item 1) ────────────────────────────────────────

    def _do_precheck(self) -> None:
        task_code = self._task_code.get()
        folder = task_folder(task_code)
        selected_ids = {pid for pid, var in self._stim_vars.items() if var.get()}
        all_stimuli = [Stimulus(task_code, row, folder) for row in self._stim_rows]
        selected = [s for s in all_stimuli if s.planche_id in selected_ids]

        if not selected:
            messagebox.showwarning("Pré-vérification", "Aucun stimulus sélectionné.")
            return

        kept, excluded = self._run_familiarity_check(selected)
        self._familiarity_kept = kept
        self._familiarity_excluded_ids = excluded
        self._familiarity_done = True

        n_kept = len(kept)
        n_excl = len(excluded)
        self._precheck_btn.config(text="✓ Vérification faite — relancer")
        self._precheck_status.config(
            text=f"{n_kept} familiers retenus, {n_excl} exclus.",
            fg=C_GREEN,
        )
        self._update_start_state()

    # ── Event handlers ────────────────────────────────────────────────────────

    def _on_task_changed(self, _event=None) -> None:
        task_code = self._task_code.get()

        self._familiarity_done = False
        self._familiarity_kept = []
        self._familiarity_excluded_ids = []

        if task_code in _FFP_TASKS:
            self._precheck_btn.config(text="Vérification de familiarité…")
            self._precheck_status.config(text="")
            self._precheck_btn.grid()
            self._precheck_status.grid()
        else:
            self._precheck_btn.grid_remove()
            self._precheck_status.grid_remove()

        self._load_stimuli()
        self._update_start_state()

    def _on_prog_changed(self, _event=None) -> None:
        if hasattr(self, "_timer_entry"):
            if self._prog_mode.get() == "Timer":
                self._timer_entry.config(state="normal")
            else:
                self._timer_entry.config(state="disabled")

    def _on_patient_id_changed(self, *_) -> None:
        self._update_start_state()
        if (self._banner_frame is not None
                and self._banner_prev_patient is not None
                and self._patient_id.get() != self._banner_prev_patient):
            self._banner_frame.grid_remove()

    def _on_quit(self) -> None:
        """Quitter button — return None to run.py, which exits the app."""
        self._root.destroy()

    def _update_start_state(self) -> None:
        task_code = self._task_code.get()
        needs_precheck = task_code in _FFP_TASKS

        ready = (
            self._time_confirmed
            and bool(self._patient_id.get().strip())
            and bool(self._electrode.get().strip())
            and bool(self._contact.get().strip())
            and (not needs_precheck or self._familiarity_done)
        )
        if ready:
            self._start_btn.config(state="normal", bg=C_NAVY, fg="white")
        else:
            self._start_btn.config(state="disabled", bg=C_BORDER, fg=C_TEXT_FAINT)
        if ready:
            self._status_label.config(text="Prêt à démarrer.", fg=C_GREEN)
        elif not self._time_confirmed:
            self._status_label.config(text="⚠  Confirmez l'heure pour continuer.", fg=C_RED)
        elif needs_precheck and not self._familiarity_done:
            self._status_label.config(text="⚠  Lancez la vérification de familiarité.", fg=C_RED)
        else:
            self._status_label.config(text="⚠  Remplissez tous les champs obligatoires.", fg=C_RED)

    def _on_start(self) -> None:
        try:
            intensity = float(self._intensity.get())
            duration  = float(self._duration.get())
        except ValueError:
            messagebox.showerror("Erreur", "Intensité et durée doivent être des nombres.")
            return

        timer_delay = 0.0
        if self._prog_mode.get() == "Timer":
            try:
                timer_delay = float(self._timer_delay.get())
            except ValueError:
                messagebox.showerror("Erreur", "Délai timer invalide.")
                return

        task_code = self._task_code.get()

        if task_code in _FFP_TASKS:
            selected_stimuli = self._familiarity_kept
            excluded_ids = self._familiarity_excluded_ids
            if not selected_stimuli:
                messagebox.showerror("Erreur", "Aucun stimulus retenu après la vérification de familiarité.")
                return
        else:
            selected_ids = {pid for pid, var in self._stim_vars.items() if var.get()}
            if not selected_ids:
                messagebox.showerror("Erreur", "Sélectionnez au moins un stimulus.")
                return
            folder = task_folder(task_code)
            all_stimuli = [Stimulus(task_code, row, folder) for row in self._stim_rows]
            selected_stimuli = [s for s in all_stimuli if s.planche_id in selected_ids]
            excluded_ids = []

        self.result = {
            "patient_id":        self._patient_id.get().strip(),
            "task_code":         task_code,
            "task_display_name": TASK_DISPLAY_NAMES.get(task_code, task_code),
            "electrode":         self._electrode.get().strip(),
            "contact":           self._contact.get().strip(),
            "intensity_ma":      intensity,
            "duration_s":        duration,
            "progression_mode":  self._prog_mode.get(),
            "timer_delay_s":     timer_delay,
            "stim_key":          self._stim_key.get().strip().lower(),
            "order":             self._order.get(),
            "selected_stimuli":  selected_stimuli,
            "excluded_ids":      excluded_ids,
        }
        self._root.destroy()

    # ── Familiarity pre-check modal ───────────────────────────────────────────

    def _run_familiarity_check(
        self,
        stimuli: list[Stimulus],
    ) -> tuple[list[Stimulus], list[str]]:
        try:
            from PIL import Image as PILImage, ImageTk
        except ImportError:
            messagebox.showwarning(
                "Pré-vérification",
                "Pillow non installé — pré-vérification ignorée.\n"
                "Installez: pip install Pillow"
            )
            return stimuli, []

        kept: list[Stimulus] = []
        excluded: list[str] = []

        win = tk.Toplevel(self._root)
        win.title("Pré-vérification de familiarité")
        win.configure(bg=C_BG)
        win.grab_set()

        img_label = tk.Label(win, bg=C_BG)
        img_label.pack(pady=8)

        name_label = tk.Label(win, bg=C_BG, fg=C_TEXT, font=F_BOLD)
        name_label.pack()

        progress_label = tk.Label(win, bg=C_BG, fg=C_TEXT_MUTED, font=F_SMALL)
        progress_label.pack()

        result_var: list[str] = []

        def on_familiar():
            result_var.clear()
            result_var.append("familiar")
            win.quit()

        def on_unfamiliar():
            result_var.clear()
            result_var.append("unfamiliar")
            win.quit()

        btn_frame = tk.Frame(win, bg=C_BG)
        btn_frame.pack(pady=8)
        for text, cmd, bg, fg in [
            ("Familier",     on_familiar,   C_NAVY,         "white"),
            ("Non familier", on_unfamiliar, C_BG_SECONDARY, C_TEXT),
        ]:
            tk.Button(
                btn_frame, text=text, command=cmd,
                bg=bg, fg=fg, font=F_BODY,
                relief="flat", padx=16, pady=6, cursor="hand2",
                highlightbackground=C_BORDER, highlightthickness=1,
            ).pack(side="left", padx=8)

        for i, stim in enumerate(stimuli):
            progress_label.config(text=f"{i + 1} / {len(stimuli)}")
            name_label.config(text=getattr(stim, "target_person", stim.planche_id))

            try:
                pil_img = PILImage.open(stim.image_path)
                pil_img.thumbnail((400, 400))
                tk_img = ImageTk.PhotoImage(pil_img)
                img_label.config(image=tk_img)
                img_label.image = tk_img
            except Exception:
                img_label.config(image="", text=stim.planche_id, fg=C_TEXT)

            result_var.clear()
            win.deiconify()
            win.mainloop()

            if result_var and result_var[0] == "familiar":
                stim.is_familiar = True
                kept.append(stim)
            else:
                stim.is_familiar = False
                excluded.append(stim.planche_id)

        win.destroy()
        return kept, excluded
