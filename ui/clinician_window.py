"""
Clinician window — tkinter, runs in a separate subprocess during the session.

Receives state updates from the patient process via *from_patient_q* and sends
clinician commands back via *to_patient_q*.

Message protocol
────────────────
Patient → Clinician  (from_patient_q):
  {'type': 'session_started', 'task_display_name': str}
  {'type': 'trial_start', 'trial_n': int, 'total': int,
           'stimulus_path': str, 'correct_answer': str,
           'planche_id': str, 'remaining': [{'planche_id', 'path'}]}
  {'type': 'image_on',   'time_s': float}
  {'type': 'response',   'response': str, 'is_correct': bool|None, 'tr_s': float}
  {'type': 'trial_end'}
  {'type': 'stim_event', 'event': 'STIM_START'|'STIM_END', 'duration_s': float}
  {'type': 'stats',      'n_correct': int, 'n_total': int, 'n_skipped': int,
                          'n_excluded': int, 'pct_correct': float}
  {'type': 'timer_tick', 'elapsed_s': float, 'remaining_s': float}
  {'type': 'session_end', 'csv_path': str}
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
"""

from __future__ import annotations

import time
import tkinter as tk
from queue import Empty
from tkinter import ttk, messagebox, simpledialog
from typing import Optional


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
        self._trial_n       = 0
        self._total_trials  = 0
        self._stim_path     = ""
        self._correct_answer = ""
        self._last_response  = ""
        self._last_correct   = None      # bool | None
        self._image_on_ts   = None      # float | None
        self._stim_on       = False
        self._elapsed_s     = 0.0
        self._remaining_s   = None      # float | None (Timer mode)
        self._n_correct     = 0
        self._n_total       = 0
        self._n_skipped     = 0
        self._n_excluded    = 0
        self._remaining_stimuli: list[dict] = []

        # Stim params (editable mid-session)
        self._electrode   = tk.StringVar()
        self._contact     = tk.StringVar()
        self._intensity   = tk.StringVar()
        self._duration    = tk.StringVar()

        self._root = tk.Tk()
        self._build_ui()
        self._bind_keys()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = self._root
        root.title("Battery — Opérateur")
        root.configure(bg="#1a1a2e")
        root.geometry("900x700")

        # ── Top bar: task name + STIM indicator ──────────────────────────────
        top = tk.Frame(root, bg="#16213e", pady=8)
        top.pack(fill="x")

        self._task_lbl = tk.Label(
            top, text=self._task_display,
            font=("Helvetica", 18, "bold"),
            fg="white", bg="#16213e"
        )
        self._task_lbl.pack(side="left", padx=16)

        self._stim_lbl = tk.Label(
            top, text="  STIMULATION OFF  ",
            font=("Helvetica", 14, "bold"),
            fg="white", bg="#555555",
            relief="raised", bd=4
        )
        self._stim_lbl.pack(side="right", padx=16)

        # ── Main area: image + trial info ─────────────────────────────────────
        main = tk.Frame(root, bg="#1a1a2e")
        main.pack(fill="both", expand=True, padx=8, pady=4)

        # Left: image mirror
        img_frame = tk.LabelFrame(main, text="Stimulus actuel", bg="#1a1a2e", fg="white")
        img_frame.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
        self._img_label = tk.Label(img_frame, bg="black", width=40, height=20)
        self._img_label.pack()
        self._tk_img = None  # prevent GC

        # Right: info panels
        info = tk.Frame(main, bg="#1a1a2e")
        info.grid(row=0, column=1, sticky="nsew", padx=4, pady=4)
        main.columnconfigure(0, weight=3)
        main.columnconfigure(1, weight=2)

        # Trial panel
        trial_frame = tk.LabelFrame(info, text="Essai", bg="#1a1a2e", fg="white")
        trial_frame.pack(fill="x", pady=4)

        self._trial_lbl = tk.Label(trial_frame, text="—", fg="white", bg="#1a1a2e",
                                    font=("Helvetica", 12))
        self._trial_lbl.pack(anchor="w", padx=8)

        self._correct_lbl = tk.Label(trial_frame, text="Bonne réponse: —",
                                      fg="#aaaaaa", bg="#1a1a2e")
        self._correct_lbl.pack(anchor="w", padx=8)

        self._resp_lbl = tk.Label(trial_frame, text="Réponse patient: —",
                                   fg="white", bg="#1a1a2e",
                                   font=("Helvetica", 12, "bold"))
        self._resp_lbl.pack(anchor="w", padx=8)

        self._timer_lbl = tk.Label(trial_frame, text="",
                                    fg="#aaaaaa", bg="#1a1a2e")
        self._timer_lbl.pack(anchor="w", padx=8, pady=2)

        # Stats panel
        stats_frame = tk.LabelFrame(info, text="Statistiques", bg="#1a1a2e", fg="white")
        stats_frame.pack(fill="x", pady=4)

        self._stats_lbl = tk.Label(stats_frame, text="—",
                                    fg="white", bg="#1a1a2e")
        self._stats_lbl.pack(anchor="w", padx=8, pady=4)

        # Stim params panel
        params_frame = tk.LabelFrame(info, text="Paramètres stimulation", bg="#1a1a2e", fg="white")
        params_frame.pack(fill="x", pady=4)

        for i, (lbl, var) in enumerate([
            ("Électrode", self._electrode),
            ("Contact",   self._contact),
            ("Intensité (mA)", self._intensity),
            ("Durée (s)",      self._duration),
        ]):
            tk.Label(params_frame, text=lbl, fg="white", bg="#1a1a2e").grid(
                row=i, column=0, sticky="w", padx=8, pady=2
            )
            tk.Entry(params_frame, textvariable=var, width=10).grid(
                row=i, column=1, sticky="w", padx=4
            )

        ttk.Button(
            params_frame, text="Mettre à jour paramètres",
            command=self._send_update_params
        ).grid(row=4, column=0, columnspan=2, pady=4)

        # Controls panel
        ctrl = tk.LabelFrame(main, text="Contrôles", bg="#1a1a2e", fg="white")
        ctrl.grid(row=1, column=0, columnspan=2, sticky="ew", padx=4, pady=4)

        btn_cfg = dict(width=18, pady=6)

        self._skip_btn = tk.Button(ctrl, text="Passer (Skip)",
                                    command=self._cmd_skip,
                                    bg="#444", fg="white", **btn_cfg)
        self._skip_btn.grid(row=0, column=0, padx=6, pady=4)

        self._excl_btn = tk.Button(ctrl, text="Exclure stimulus",
                                    command=self._cmd_exclude,
                                    bg="#884400", fg="white", **btn_cfg)
        self._excl_btn.grid(row=0, column=1, padx=6, pady=4)

        self._repl_btn = tk.Button(ctrl, text="Remplacer stimulus",
                                    command=self._cmd_replace,
                                    bg="#004488", fg="white", **btn_cfg)
        self._repl_btn.grid(row=0, column=2, padx=6, pady=4)

        self._abort_btn = tk.Button(ctrl, text="Arrêter session",
                                     command=self._cmd_abort,
                                     bg="#880000", fg="white", **btn_cfg)
        self._abort_btn.grid(row=0, column=3, padx=6, pady=4)

        # "Essai suivant" button (ClinicianAction mode)
        self._next_btn = tk.Button(ctrl, text="Essai suivant ▶",
                                    command=self._cmd_next_trial,
                                    bg="#006600", fg="white",
                                    width=18, pady=6,
                                    state="disabled")
        self._next_btn.grid(row=0, column=4, padx=6, pady=4)
        if self._prog_mode == "ClinicianAction":
            self._next_btn.config(state="normal")

    def _bind_keys(self) -> None:
        """Keyboard shortcuts for the clinician window."""
        self._root.bind(f"<{self._stim_key.upper()}>", lambda e: self._cmd_stim_key())
        self._root.bind(f"<{self._stim_key}>",          lambda e: self._cmd_stim_key())
        self._root.bind("<k>",  lambda e: self._cmd_di_correct())
        self._root.bind("<K>",  lambda e: self._cmd_di_correct())
        self._root.bind("<x>",  lambda e: self._cmd_di_incorrect())
        self._root.bind("<X>",  lambda e: self._cmd_di_incorrect())
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
            self._root.after(self.POLL_MS, self._poll)

        # Update live elapsed timer
        if self._image_on_ts is not None:
            self._elapsed_s = time.monotonic() - self._image_on_ts
            self._update_timer_display()

    def _handle_message(self, msg: dict) -> None:
        t = msg.get("type", "")

        if t == "session_started":
            self._task_lbl.config(text=msg.get("task_display_name", self._task_display))

        elif t == "trial_start":
            self._trial_n          = msg["trial_n"]
            self._total_trials     = msg["total"]
            self._stim_path        = msg["stimulus_path"]
            self._correct_answer   = msg.get("correct_answer", "")
            self._last_response    = "—"
            self._last_correct     = None
            self._image_on_ts      = None
            self._remaining_stimuli = msg.get("remaining", [])
            self._update_trial_display()
            self._update_image()

        elif t == "image_on":
            self._image_on_ts = time.monotonic()

        elif t == "response":
            self._last_response = msg.get("response", "")
            self._last_correct  = msg.get("is_correct")
            self._update_response_display()

        elif t == "stim_event":
            ev = msg.get("event", "")
            if ev == "STIM_START":
                self._stim_on = True
                self._stim_lbl.config(
                    text="  STIMULATION ON  ", bg="#cc0000", fg="white"
                )
            elif ev == "STIM_END":
                self._stim_on = False
                self._stim_lbl.config(
                    text="  STIMULATION OFF  ", bg="#555555", fg="white"
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
            csv_path = msg.get("csv_path", "")
            messagebox.showinfo(
                "Session terminée",
                f"Session terminée.\nFichier CSV: {csv_path}"
            )
            self._root.after(2000, self._root.destroy)

        elif t == "error":
            messagebox.showerror("Erreur", msg.get("message", "Erreur inconnue"))

        elif t == "stim_params":
            self._electrode.set(msg.get("electrode", ""))
            self._contact.set(msg.get("contact", ""))
            self._intensity.set(str(msg.get("intensity_ma", "")))
            self._duration.set(str(msg.get("duration_s", "")))

    # ── Display updates ───────────────────────────────────────────────────────

    def _update_trial_display(self) -> None:
        self._trial_lbl.config(
            text=f"Essai {self._trial_n} / {self._total_trials}"
        )
        self._correct_lbl.config(
            text=f"Bonne réponse: {self._correct_answer or '—'}"
        )
        self._resp_lbl.config(text="Réponse patient: —", fg="white")

    def _update_response_display(self) -> None:
        cr = self._last_correct
        if cr is True:
            colour = "#00cc44"
            verdict = "✓ Correct"
        elif cr is False:
            colour = "#cc3300"
            verdict = "✗ Incorrect"
        else:
            colour = "#aaaaaa"
            verdict = ""
        self._resp_lbl.config(
            text=f"Réponse patient: {self._last_response}  {verdict}",
            fg=colour,
        )

    def _update_stats_display(self) -> None:
        pct = (
            round(self._n_correct / self._n_total * 100, 1)
            if self._n_total > 0 else 0.0
        )
        self._stats_lbl.config(
            text=(
                f"{self._n_correct}/{self._n_total} corrects  ({pct}%)\n"
                f"Passés: {self._n_skipped}   Exclus: {self._n_excluded}"
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
            pil_img.thumbnail((380, 280))
            tk_img = ImageTk.PhotoImage(pil_img)
            self._img_label.config(image=tk_img, text="")
            self._tk_img = tk_img
        except Exception:
            self._img_label.config(
                image="",
                text=f"[{self._stim_path.split('/')[-1]}]",
                fg="white", bg="black"
            )

    # ── Clinician commands ────────────────────────────────────────────────────

    def _send(self, msg: dict) -> None:
        self._to_q.put_nowait(msg)

    def _cmd_skip(self) -> None:
        self._send({"type": "skip"})

    def _cmd_exclude(self) -> None:
        self._send({"type": "exclude"})

    def _cmd_replace(self) -> None:
        if not self._remaining_stimuli:
            messagebox.showinfo("Remplacer", "Aucun stimulus disponible pour le remplacement.")
            return
        names = [s["planche_id"] for s in self._remaining_stimuli]
        choice = simpledialog.askstring(
            "Remplacer stimulus",
            "Sélectionnez l'ID du stimulus de remplacement:\n\n" + "\n".join(names[:20]),
            parent=self._root,
        )
        if choice and choice in names:
            self._send({"type": "replace", "planche_id": choice})

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
        """F12 pressed by clinician — record STIM_START."""
        self._send({"type": "stim_key"})

    def _cmd_di_correct(self) -> None:
        """K pressed — DI_SEEG correct response."""
        if self._task_code == "DI_SEEG":
            self._send({"type": "di_correct"})

    def _cmd_di_incorrect(self) -> None:
        """X pressed — DI_SEEG incorrect response."""
        if self._task_code == "DI_SEEG":
            self._send({"type": "di_incorrect"})

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
    app.run()
