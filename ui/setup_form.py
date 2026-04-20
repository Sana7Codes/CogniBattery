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
from typing import Optional

from tasks.csv_loader import load_trials, task_folder, TASK_FOLDERS
from core.stimulus import Stimulus

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


# ── Main form ─────────────────────────────────────────────────────────────────

class SetupForm:
    """
    Modal tkinter form for session configuration.
    Call run() to show it; returns config dict when complete or None if cancelled.
    """

    def __init__(self, presets: dict | None = None) -> None:
        self.result: dict | None = None
        self._presets = presets or {}
        self._time_confirmed = False
        self._stim_vars: dict[str, tk.BooleanVar] = {}   # planche_id → BooleanVar
        self._stim_rows: list[dict] = []                  # raw trials.csv rows
        self._root: tk.Tk | None = None

    def run(self) -> dict | None:
        self._root = tk.Tk()
        self._root.title("Battery — Configuration de session")
        self._root.resizable(False, False)
        self._build_ui()
        self._root.mainloop()
        return self.result

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = self._root

        # ── Left column: form fields ──────────────────────────────────────────
        left = ttk.Frame(root, padding=12)
        left.grid(row=0, column=0, sticky="nsew")

        # Patient ID
        ttk.Label(left, text="Patient ID *").grid(row=0, column=0, sticky="w")
        self._patient_id = tk.StringVar(value=self._presets.get("patient_id", ""))
        ttk.Entry(left, textvariable=self._patient_id, width=20).grid(row=0, column=1, sticky="w", pady=2)

        # Date/time
        ttk.Label(left, text="Date/Heure *").grid(row=1, column=0, sticky="w", pady=(8, 0))
        now = datetime.datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
        self._time_label = ttk.Label(left, text=now, foreground="red", font=("Helvetica", 10, "bold"))
        self._time_label.grid(row=1, column=1, sticky="w")
        self._update_clock()

        self._confirm_time_btn = ttk.Button(
            left, text="Heure correcte — continuer", command=self._confirm_time
        )
        self._confirm_time_btn.grid(row=2, column=0, columnspan=2, pady=4)

        # Task type
        ttk.Label(left, text="Tâche *").grid(row=3, column=0, sticky="w", pady=(8, 0))
        self._task_code = tk.StringVar(value=self._presets.get("task_code", list(TASK_FOLDERS.keys())[0]))
        task_cb = ttk.Combobox(
            left, textvariable=self._task_code, width=35,
            values=list(TASK_FOLDERS.keys()), state="readonly"
        )
        task_cb.grid(row=3, column=1, sticky="w")
        task_cb.bind("<<ComboboxSelected>>", self._on_task_changed)

        # Electrode
        ttk.Label(left, text="Électrode *").grid(row=4, column=0, sticky="w", pady=2)
        self._electrode = tk.StringVar(value=self._presets.get("electrode", ""))
        ttk.Entry(left, textvariable=self._electrode, width=10).grid(row=4, column=1, sticky="w")

        # Contact
        ttk.Label(left, text="Contact *").grid(row=5, column=0, sticky="w", pady=2)
        self._contact = tk.StringVar(value=self._presets.get("contact", ""))
        ttk.Entry(left, textvariable=self._contact, width=10).grid(row=5, column=1, sticky="w")

        # Intensity
        ttk.Label(left, text="Intensité (mA) *").grid(row=6, column=0, sticky="w", pady=2)
        self._intensity = tk.StringVar(value=self._presets.get("intensity", "1.0"))
        ttk.Entry(left, textvariable=self._intensity, width=10).grid(row=6, column=1, sticky="w")

        # Duration
        ttk.Label(left, text="Durée stim (s) *").grid(row=7, column=0, sticky="w", pady=2)
        self._duration = tk.StringVar(value=self._presets.get("duration", "3.0"))
        ttk.Entry(left, textvariable=self._duration, width=10).grid(row=7, column=1, sticky="w")

        # Progression mode
        ttk.Label(left, text="Mode progression *").grid(row=8, column=0, sticky="w", pady=(8, 0))
        self._prog_mode = tk.StringVar(value=self._presets.get("progression_mode", "PatientTouch"))
        prog_cb = ttk.Combobox(
            left, textvariable=self._prog_mode, width=20,
            values=["PatientTouch", "ClinicianAction", "Timer"], state="readonly"
        )
        prog_cb.grid(row=8, column=1, sticky="w")
        prog_cb.bind("<<ComboboxSelected>>", self._on_prog_changed)

        ttk.Label(left, text="Délai timer (s)").grid(row=9, column=0, sticky="w", pady=2)
        self._timer_delay = tk.StringVar(value=self._presets.get("timer_delay", "5.0"))
        self._timer_entry = ttk.Entry(left, textvariable=self._timer_delay, width=10)
        self._timer_entry.grid(row=9, column=1, sticky="w")
        self._on_prog_changed()

        # Stim signal key
        ttk.Label(left, text="Touche STIM").grid(row=10, column=0, sticky="w", pady=2)
        self._stim_key = tk.StringVar(value=self._presets.get("stim_key", "f12"))
        ttk.Entry(left, textvariable=self._stim_key, width=10).grid(row=10, column=1, sticky="w")

        # Order
        ttk.Label(left, text="Ordre stimuli").grid(row=11, column=0, sticky="w", pady=(8, 0))
        self._order = tk.StringVar(value=self._presets.get("order", "random"))
        order_frame = ttk.Frame(left)
        order_frame.grid(row=11, column=1, sticky="w")
        ttk.Radiobutton(order_frame, text="Aléatoire", variable=self._order, value="random").pack(side="left")
        ttk.Radiobutton(order_frame, text="Fixe",     variable=self._order, value="fixed").pack(side="left")

        # Start button
        self._start_btn = ttk.Button(
            left, text="Démarrer la session", command=self._on_start,
            state="disabled"
        )
        self._start_btn.grid(row=12, column=0, columnspan=2, pady=(16, 4))

        self._status_label = ttk.Label(left, text="⚠ Confirmez l'heure pour continuer.", foreground="orange")
        self._status_label.grid(row=13, column=0, columnspan=2)

        # ── Right column: stimulus list ───────────────────────────────────────
        right = ttk.LabelFrame(root, text="Stimuli", padding=8)
        right.grid(row=0, column=1, sticky="nsew", padx=(0, 8), pady=8)

        self._cb_label = ttk.Label(right, text="")
        self._cb_label.pack(anchor="w")

        canvas = tk.Canvas(right, width=340, height=480)
        sb = ttk.Scrollbar(right, orient="vertical", command=canvas.yview)
        self._stim_inner = ttk.Frame(canvas)
        self._stim_inner.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.create_window((0, 0), window=self._stim_inner, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        btn_row = ttk.Frame(right)
        btn_row.pack(fill="x", pady=(4, 0))
        ttk.Button(btn_row, text="Tout sélectionner",   command=self._select_all).pack(side="left")
        ttk.Button(btn_row, text="Tout désélectionner", command=self._deselect_all).pack(side="left", padx=4)

        self._load_stimuli()

    # ── Clock ─────────────────────────────────────────────────────────────────

    def _update_clock(self) -> None:
        if self._root and not self._time_confirmed:
            now = datetime.datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
            self._time_label.config(text=now)
            self._root.after(1000, self._update_clock)

    def _confirm_time(self) -> None:
        self._time_confirmed = True
        self._time_label.config(foreground="green")
        self._confirm_time_btn.config(state="disabled", text="✓ Heure confirmée")
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
            ttk.Label(self._stim_inner, text=f"Erreur: {exc}").pack()
            return

        folder = task_folder(task_code)
        stimuli = [Stimulus(task_code, row, folder) for row in rows]
        self._stim_rows = rows

        for stim in stimuli:
            var = tk.BooleanVar(value=True)
            self._stim_vars[stim.planche_id] = var
            cb = ttk.Checkbutton(
                self._stim_inner,
                text=stim.planche_id,
                variable=var,
                command=self._update_cb_label,
            )
            cb.pack(anchor="w")

        self._update_cb_label()

    def _update_cb_label(self) -> None:
        if not self._stim_vars:
            return
        task_code = self._task_code.get()
        folder = task_folder(task_code)
        selected = [
            pid for pid, var in self._stim_vars.items() if var.get()
        ]
        # Count left/right from selected stimuli
        left_n = right_n = 0
        for row in self._stim_rows:
            pid = Path(row["filename"]).stem
            if pid not in selected:
                continue
            stim = Stimulus(task_code, row, folder)
            cr = getattr(stim, "correct_response", None)
            if cr == "left":
                left_n += 1
            elif cr == "right":
                right_n += 1
        total = len(selected)
        if left_n + right_n > 0:
            cb_text = (
                f"{total} stimuli sélectionnés   "
                f"| Gauche: {left_n}  Droite: {right_n}"
            )
        else:
            cb_text = f"{total} stimuli sélectionnés"
        self._cb_label.config(text=cb_text)

    def _select_all(self) -> None:
        for var in self._stim_vars.values():
            var.set(True)
        self._update_cb_label()

    def _deselect_all(self) -> None:
        for var in self._stim_vars.values():
            var.set(False)
        self._update_cb_label()

    # ── Event handlers ────────────────────────────────────────────────────────

    def _on_task_changed(self, _event=None) -> None:
        self._load_stimuli()

    def _on_prog_changed(self, _event=None) -> None:
        if hasattr(self, "_timer_entry"):
            if self._prog_mode.get() == "Timer":
                self._timer_entry.config(state="normal")
            else:
                self._timer_entry.config(state="disabled")

    def _update_start_state(self) -> None:
        ready = (
            self._time_confirmed
            and bool(self._patient_id.get().strip())
            and bool(self._electrode.get().strip())
            and bool(self._contact.get().strip())
        )
        self._start_btn.config(state="normal" if ready else "disabled")
        if ready:
            self._status_label.config(text="Prêt à démarrer.", foreground="green")
        elif not self._time_confirmed:
            self._status_label.config(text="⚠ Confirmez l'heure pour continuer.", foreground="orange")
        else:
            self._status_label.config(text="⚠ Remplissez tous les champs obligatoires.", foreground="orange")

    def _on_start(self) -> None:
        # Validate numeric fields
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
        selected_ids = {pid for pid, var in self._stim_vars.items() if var.get()}
        if not selected_ids:
            messagebox.showerror("Erreur", "Sélectionnez au moins un stimulus.")
            return

        # Build selected stimuli list
        folder = task_folder(task_code)
        all_stimuli = [Stimulus(task_code, row, folder) for row in self._stim_rows]
        selected_stimuli = [s for s in all_stimuli if s.planche_id in selected_ids]

        # Familiarity pre-check for FFP tasks
        excluded_ids: list[str] = []
        if task_code in ("FFP_V1", "FFP_V2"):
            selected_stimuli, excluded_ids = self._run_familiarity_check(selected_stimuli)

        self.result = {
            "patient_id":       self._patient_id.get().strip(),
            "task_code":        task_code,
            "task_display_name": TASK_DISPLAY_NAMES.get(task_code, task_code),
            "electrode":        self._electrode.get().strip(),
            "contact":          self._contact.get().strip(),
            "intensity_ma":     intensity,
            "duration_s":       duration,
            "progression_mode": self._prog_mode.get(),
            "timer_delay_s":    timer_delay,
            "stim_key":         self._stim_key.get().strip().lower(),
            "order":            self._order.get(),
            "selected_stimuli": selected_stimuli,
            "excluded_ids":     excluded_ids,
        }
        self._root.destroy()

    # ── Familiarity pre-check (FFP only) ──────────────────────────────────────

    def _run_familiarity_check(
        self,
        stimuli: list[Stimulus],
    ) -> tuple[list[Stimulus], list[str]]:
        """
        Show each face image; clinician clicks Familier / Non familier.
        Non-familiar faces are excluded.
        Returns (kept_stimuli, excluded_planche_ids).
        """
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
        win.grab_set()

        img_label = tk.Label(win)
        img_label.pack(pady=8)

        name_label = ttk.Label(win, font=("Helvetica", 14, "bold"))
        name_label.pack()

        progress_label = ttk.Label(win)
        progress_label.pack()

        result_var: list[str] = []  # mutable container for button callbacks

        def on_familiar():
            result_var.clear()
            result_var.append("familiar")
            win.quit()

        def on_unfamiliar():
            result_var.clear()
            result_var.append("unfamiliar")
            win.quit()

        btn_frame = ttk.Frame(win)
        btn_frame.pack(pady=8)
        ttk.Button(
            btn_frame, text="Familier", command=on_familiar,
            style="Accent.TButton" if "Accent.TButton" in ttk.Style().theme_names() else "TButton"
        ).pack(side="left", padx=8)
        ttk.Button(btn_frame, text="Non familier", command=on_unfamiliar).pack(side="left", padx=8)

        for i, stim in enumerate(stimuli):
            progress_label.config(text=f"{i + 1} / {len(stimuli)}")
            name_label.config(text=getattr(stim, "target_person", stim.planche_id))

            try:
                pil_img = PILImage.open(stim.image_path)
                pil_img.thumbnail((400, 400))
                tk_img = ImageTk.PhotoImage(pil_img)
                img_label.config(image=tk_img)
                img_label.image = tk_img  # prevent GC
            except Exception:
                img_label.config(image="", text=stim.planche_id)

            result_var.clear()
            win.deiconify()
            win.mainloop()   # blocks until a button is clicked

            if result_var and result_var[0] == "familiar":
                stim.is_familiar = True
                kept.append(stim)
            else:
                stim.is_familiar = False
                excluded.append(stim.planche_id)

        win.destroy()
        return kept, excluded
