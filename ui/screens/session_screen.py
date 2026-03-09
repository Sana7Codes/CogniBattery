"""
SessionScreen — active session view (replaces the old KivyClinicianScreen).

Layout:
  Top bar: live indicator | Patient ID | Trial type | Terminer button
  Main area (horizontal):
    Left 60%  — patient preview + status chips
    Right 40% — 3 cards: Stimulation | Données de l'essai | Contrôle manuel

Implementation order follows verification priority:
  Steps 5-6 first: manual controls + stim card
  Step 4 after:    patient response in Données de l'essai
"""
from typing import Callable, Optional

from kivy.graphics import Color, Rectangle, RoundedRectangle, Line
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.popup import Popup

from ui.screens.widgets import (
    make_card, lbl, btn_primary, btn_ghost, btn_danger, _bg, _repaint_bg, divider,
)
from ui.theme import (
    BG_COLOR, SURFACE, NAV_BG, BORDER,
    TEXT_DARK, TEXT_MID, TEXT_WHITE, DOT_GREEN, STIM_ON_BG, BTN_GHOST,
    FONT_XS, FONT_SM, FONT_MD, FONT_LG, FONT_XL,
    PAD_SM, PAD_MD, PAD_LG, BTN_H, NAV_H,
)


class SessionScreen(BoxLayout):
    """
    Full-height session screen shown while a session is active.

    Public API:
        update(state: dict)              — refresh all labels / preview
        set_stim_active(active, rem_s)   — update stimulation card colour
        on_stim_ended()                  — convenience: set_stim_active(False)
        on_end_session(cb)               — register Terminer callback
        on_skip(cb)                      — register Passer callback
        on_exclude(cb)                   — register Exclure callback
        show_error(msg)                  — pop an error dialog
    """

    def __init__(self, **kwargs):
        kwargs.setdefault("orientation", "vertical")
        super().__init__(**kwargs)

        _bg(self, BG_COLOR)

        self._on_end_cb:      Optional[Callable] = None
        self._on_skip_cb:     Optional[Callable] = None
        self._on_exclude_cb:  Optional[Callable] = None
        self._on_replace_cb:  Optional[Callable] = None
        self._on_advance_cb:  Optional[Callable] = None

        self._build_top_bar()
        self._build_main_area()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _build_top_bar(self):
        bar = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(NAV_H),
            padding=(dp(PAD_LG), dp(8)),
            spacing=dp(PAD_MD),
        )
        _bg(bar, SURFACE)

        # Green dot + "Séance en cours"
        dot_row = BoxLayout(orientation="horizontal", size_hint_x=None,
                            width=dp(160), spacing=dp(6))
        dot = Label(text="●", font_size=dp(FONT_MD), color=DOT_GREEN,
                    size_hint=(None, None), size=(dp(20), dp(NAV_H)))
        dot_row.add_widget(dot)
        dot_row.add_widget(lbl("Séance en cours", size=FONT_MD, bold=True,
                               color=TEXT_DARK))
        bar.add_widget(dot_row)

        bar.add_widget(divider_v())

        self._lbl_patient_top = lbl("—", size=FONT_MD, color=TEXT_DARK,
                                    size_hint_x=None, width=dp(140))
        bar.add_widget(self._lbl_patient_top)

        bar.add_widget(divider_v())

        self._lbl_test_top = lbl("—", size=FONT_SM, color=TEXT_MID,
                                  size_hint_x=None, width=dp(180))
        bar.add_widget(self._lbl_test_top)

        bar.add_widget(BoxLayout())  # spacer

        self._btn_terminer = btn_danger(
            "Terminer et sauvegarder (CSV)",
            callback=self._confirm_end,
            size_hint_x=None,
            width=dp(260),
        )
        bar.add_widget(self._btn_terminer)

        self.add_widget(bar)
        self.add_widget(divider())

    def _build_main_area(self):
        main = BoxLayout(orientation="horizontal", padding=dp(PAD_MD),
                         spacing=dp(PAD_MD))
        _bg(main, BG_COLOR)

        main.add_widget(self._build_left_panel())
        main.add_widget(self._build_right_panel())
        self.add_widget(main)

    def _build_left_panel(self):
        left = BoxLayout(orientation="vertical", size_hint_x=0.60,
                         spacing=dp(PAD_SM))

        # Label
        left.add_widget(lbl("Écran patient", size=FONT_SM, bold=True,
                            color=TEXT_MID, size_hint_y=None, height=dp(24),
                            halign="left", valign="middle",
                            text_size=(None, None)))

        # Status chips
        chips = BoxLayout(orientation="horizontal", size_hint_y=None,
                          height=dp(28), spacing=dp(8))
        self._chip_state = _chip("État: —")
        self._chip_trial = _chip("Essai: —")
        chips.add_widget(self._chip_state)
        chips.add_widget(self._chip_trial)
        chips.add_widget(BoxLayout())
        left.add_widget(chips)

        # Preview box (gray placeholder)
        preview = BoxLayout(orientation="vertical")
        _bg(preview, NAV_BG)
        self._preview_img = Image(source="", fit_mode="contain")
        preview.add_widget(self._preview_img)
        left.add_widget(preview)

        return left

    def _build_right_panel(self):
        right = BoxLayout(orientation="vertical", size_hint_x=0.40,
                          spacing=dp(PAD_MD))

        # ---- Step 5-6: Stimulation card ----
        self._stim_card = make_card(spacing=dp(PAD_SM), size_hint_y=None,
                                     height=dp(120))
        stim_header = BoxLayout(orientation="horizontal", size_hint_y=None,
                                height=dp(28))
        self._lbl_stim_title = lbl("Stimulation : OFF", size=FONT_MD, bold=True,
                                   color=TEXT_DARK)
        stim_header.add_widget(self._lbl_stim_title)
        self._stim_card.add_widget(stim_header)

        self._lbl_stim_sub = lbl("Électrode — / Contact —", size=FONT_SM,
                                  color=TEXT_MID, size_hint_y=None, height=dp(20))
        self._stim_card.add_widget(self._lbl_stim_sub)

        self._lbl_stim_remaining = lbl("", size=FONT_SM, color=TEXT_MID,
                                        size_hint_y=None, height=dp(20))
        self._stim_card.add_widget(self._lbl_stim_remaining)
        right.add_widget(self._stim_card)

        # ---- Step 4: Données de l'essai card ----
        self._data_card = make_card(spacing=dp(PAD_SM))
        data_header = BoxLayout(orientation="horizontal", size_hint_y=None,
                                height=dp(28))
        data_header.add_widget(lbl("Données de l'essai", size=FONT_MD, bold=True,
                                   color=TEXT_DARK))
        self._lbl_timer = lbl("Timer: —", size=FONT_SM, color=TEXT_MID,
                              halign="right", valign="middle")
        self._lbl_timer.bind(size=self._lbl_timer.setter("text_size"))
        data_header.add_widget(self._lbl_timer)
        self._data_card.add_widget(data_header)

        # 2×2 data grid
        grid = GridLayout(cols=2, rows=2, spacing=dp(PAD_SM), size_hint_y=None,
                          height=dp(120))
        self._data_cells = {}
        for label, key in [
            ("Réponse",          "response"),
            ("Réponse correcte", "correct"),
            ("Correction",       "correction"),
            ("Dernier TR",       "tr_s"),
        ]:
            cell = BoxLayout(orientation="vertical", padding=dp(PAD_SM))
            _bg(cell, BG_COLOR)
            cell.add_widget(lbl(label, size=FONT_XS, color=TEXT_MID,
                                size_hint_y=None, height=dp(16)))
            val_lbl = lbl("—", size=FONT_LG, bold=True, color=TEXT_DARK)
            cell.add_widget(val_lbl)
            self._data_cells[key] = val_lbl
            grid.add_widget(cell)
        self._data_card.add_widget(grid)
        right.add_widget(self._data_card)

        # ---- Step 5: Contrôle manuel card ----
        ctrl_card = make_card(spacing=dp(PAD_SM), size_hint_y=None, height=dp(170))
        ctrl_card.add_widget(lbl("Contrôle manuel", size=FONT_MD, bold=True,
                                  color=TEXT_DARK, size_hint_y=None, height=dp(28)))

        self._btn_advance = btn_primary(
            "Avancer l'essai →",
            callback=lambda: self._on_advance_cb and self._on_advance_cb(),
            size_hint_x=1,
        )
        self._btn_advance.disabled = True
        ctrl_card.add_widget(self._btn_advance)

        self._btn_skip = btn_ghost(
            "Passer l'essai",
            callback=lambda: self._on_skip_cb and self._on_skip_cb(),
            size_hint_x=1,
        )
        ctrl_card.add_widget(self._btn_skip)

        self._btn_exclude = btn_ghost(
            "Exclure ce stimulus",
            callback=self._fire_exclude,
            size_hint_x=1,
        )
        ctrl_card.add_widget(self._btn_exclude)

        self._btn_replace = btn_ghost(
            "Remplacer ce stimulus",
            callback=self._fire_replace,
            size_hint_x=1,
        )
        ctrl_card.add_widget(self._btn_replace)
        right.add_widget(ctrl_card)

        return right

    # ------------------------------------------------------------------
    # Public rendering API
    # ------------------------------------------------------------------

    def update(self, state: dict) -> None:
        """Refresh all labels and preview image from a state dict."""
        self._lbl_patient_top.text = state.get("patient_id", "—")
        self._lbl_test_top.text    = (
            f"{state.get('test_type','—')} — "
            f"Mode: {state.get('progression_mode','—')}"
        )

        trial   = state.get("current_trial", "—")
        total   = state.get("total_trials", "—")
        self._chip_state.text = f"État: {'ACTIF' if state.get('is_stim_active') else 'ATTENTE'}"
        self._chip_trial.text = f"Essai: {trial} / {total}"

        # Stimulus preview
        stimulus = state.get("stimulus")
        if stimulus is not None:
            self._refresh_preview(stimulus, state.get("images_base", ""))
        else:
            self._preview_img.source = ""

        # Stim electrode/contact subtitle from recent session config
        electrode = state.get("electrode", "—")
        contact   = state.get("contact", "—")
        self._lbl_stim_sub.text = f"Électrode {electrode} / Contact {contact}"

        # Trial data (step 4)
        events = state.get("recent_events", [])
        self._refresh_trial_data(events)

        # Timer display
        elapsed = state.get("elapsed_s")
        if elapsed is not None:
            self._lbl_timer.text = f"Timer: {elapsed:.2f}s"

        # Avancer button — enabled only when clinician must manually advance
        awaiting = state.get("awaiting_clinician_advance", False)
        self._btn_advance.disabled = not awaiting

    def update_timer(self, elapsed_s: float) -> None:
        """Live elapsed-time update called from _tick (every 10 ms)."""
        self._lbl_timer.text = f"Timer: {elapsed_s:.2f}s"

    def set_stim_active(self, active: bool, remaining_s: float = 0.0) -> None:
        """Update stimulation card colour and labels (steps 5-6)."""
        if active:
            _repaint_bg(self._stim_card, STIM_ON_BG)
            self._lbl_stim_title.text     = "Stimulation : ON"
            self._lbl_stim_remaining.text = f"{remaining_s:.1f}s restantes"
        else:
            _repaint_bg(self._stim_card, SURFACE)
            self._lbl_stim_title.text     = "Stimulation : OFF"
            self._lbl_stim_remaining.text = ""

    def on_stim_ended(self) -> None:
        self.set_stim_active(False)

    def show_error(self, message: str) -> None:
        from kivy.uix.popup import Popup
        content = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(10))
        content.add_widget(Label(text=message, color=(0.8, 0.2, 0.2, 1)))
        from kivy.uix.button import Button
        btn = Button(text="OK", size_hint_y=None, height=dp(40))
        content.add_widget(btn)
        popup = Popup(title="Erreur", content=content, size_hint=(0.6, 0.4))
        btn.bind(on_press=popup.dismiss)
        popup.open()

    # ------------------------------------------------------------------
    # Callback registration
    # ------------------------------------------------------------------

    def on_end_session(self, cb: Callable) -> None:
        self._on_end_cb = cb

    def on_advance(self, cb: Callable) -> None:
        self._on_advance_cb = cb

    def on_skip(self, cb: Callable) -> None:
        self._on_skip_cb = cb

    def on_exclude(self, cb: Callable) -> None:
        self._on_exclude_cb = cb

    def on_replace(self, cb: Callable) -> None:
        self._on_replace_cb = cb

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _refresh_preview(self, stimulus, images_base: str) -> None:
        from ui.widgets.semantic_matching_widget import _resolve
        task    = stimulus.task_type
        payload = stimulus.payload
        if task == "SemanticMatching":
            self._preview_img.source = _resolve(payload.get("center_image", ""), images_base)
        elif task in ("FamousFace", "UnknownFace"):
            self._preview_img.source = _resolve(payload.get("face_image", ""), images_base)
        else:
            self._preview_img.source = ""

    def _refresh_trial_data(self, recent_events: list) -> None:
        """Step 4 — populate Données de l'essai from the most recent RESPONSE event."""
        from core.event_log import EventType
        resp_events = [
            e for e in recent_events
            if hasattr(e, "event") and e.event == EventType.RESPONSE
        ]
        if not resp_events:
            for key in self._data_cells:
                self._data_cells[key].text = "—"
            return

        e = resp_events[-1]
        self._data_cells["response"].text   = str(e.response or "—")
        self._data_cells["correct"].text    = ("✓" if e.correct else
                                               ("✗" if e.correct is False else "—"))
        self._data_cells["tr_s"].text       = (f"{e.tr_s:.2f}s" if e.tr_s is not None
                                               else "—")
        # "Correction" = correct response of the previous trial
        if len(resp_events) >= 2:
            prev = resp_events[-2]
            self._data_cells["correction"].text = str(prev.response or "—")
        else:
            self._data_cells["correction"].text = "—"

    def _fire_exclude(self) -> None:
        from kivy.uix.textinput import TextInput
        from kivy.uix.button import Button
        from kivy.uix.popup import Popup
        content = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(10))
        reason_inp = TextInput(hint_text="Raison d'exclusion...", multiline=False,
                               size_hint_y=None, height=dp(40))
        content.add_widget(reason_inp)
        row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6))
        btn_ok  = Button(text="Exclure", background_color=(0.78, 0.18, 0.18, 1))
        btn_no  = Button(text="Annuler")
        row.add_widget(btn_ok)
        row.add_widget(btn_no)
        content.add_widget(row)
        popup = Popup(title="Exclure le stimulus", content=content,
                      size_hint=(0.5, 0.35))

        def _do(*_):
            popup.dismiss()
            if self._on_exclude_cb:
                self._on_exclude_cb(reason_inp.text.strip())

        btn_ok.bind(on_press=_do)
        btn_no.bind(on_press=popup.dismiss)
        popup.open()

    def _fire_replace(self) -> None:
        from kivy.uix.textinput import TextInput
        from kivy.uix.button import Button
        from kivy.uix.popup import Popup
        content = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(10))
        reason_inp = TextInput(hint_text="Raison du remplacement...", multiline=False,
                               size_hint_y=None, height=dp(40))
        content.add_widget(reason_inp)
        row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6))
        btn_ok = Button(text="Choisir remplacement",
                        background_color=(0.20, 0.50, 0.80, 1))
        btn_no = Button(text="Annuler")
        row.add_widget(btn_ok)
        row.add_widget(btn_no)
        content.add_widget(row)
        popup = Popup(title="Remplacer le stimulus", content=content,
                      size_hint=(0.5, 0.35))

        def _do(*_):
            popup.dismiss()
            if self._on_replace_cb:
                self._on_replace_cb(reason_inp.text.strip())

        btn_ok.bind(on_press=_do)
        btn_no.bind(on_press=popup.dismiss)
        popup.open()

    def _confirm_end(self) -> None:
        from kivy.uix.button import Button
        from kivy.uix.popup import Popup
        content = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(10))
        content.add_widget(Label(text="Terminer et sauvegarder la séance ?",
                                 color=TEXT_DARK))
        row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6))
        btn_yes = Button(text="Oui, terminer",
                         background_color=(0.78, 0.18, 0.18, 1),
                         background_normal="")
        btn_no  = Button(text="Annuler", background_normal="")
        row.add_widget(btn_yes)
        row.add_widget(btn_no)
        content.add_widget(row)
        popup = Popup(title="Confirmer", content=content, size_hint=(0.45, 0.30))

        def _do(*_):
            popup.dismiss()
            if self._on_end_cb:
                self._on_end_cb()

        btn_yes.bind(on_press=_do)
        btn_no.bind(on_press=popup.dismiss)
        popup.open()


# ---------------------------------------------------------------------------
# Local helpers
# ---------------------------------------------------------------------------

def _chip(text: str) -> Label:
    """Small badge-style label."""
    chip = Label(
        text=text,
        font_size=dp(FONT_XS),
        color=TEXT_MID,
        size_hint=(None, None),
        size=(dp(120), dp(24)),
        halign="center",
        valign="middle",
    )
    chip.bind(size=chip.setter("text_size"))
    with chip.canvas.before:
        Color(*BTN_GHOST)
        rr = RoundedRectangle(pos=chip.pos, size=chip.size, radius=[dp(4)])
    chip.bind(
        pos=lambda i, v: setattr(rr, "pos", v),
        size=lambda i, v: setattr(rr, "size", v),
    )
    return chip


def divider_v(width=1):
    """Thin vertical separator."""
    d = BoxLayout(size_hint_x=None, width=dp(width))
    with d.canvas.before:
        Color(*BORDER)
        rect = Rectangle(pos=d.pos, size=d.size)
    d.bind(
        pos=lambda i, v: setattr(rect, "pos", v),
        size=lambda i, v: setattr(rect, "size", v),
    )
    return d
