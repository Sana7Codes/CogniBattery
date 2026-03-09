"""
ConfigScreen — "Nouvelle Séance" configuration form.

Layout:
  Title row (header)
  3-column card area: session data | params | stimuli
  Bottom validation bar
"""
import os
from datetime import date, datetime
from typing import Callable, List, Optional

from kivy.graphics import Color, Rectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.checkbox import CheckBox
from kivy.uix.dropdown import DropDown
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView

from core.session import ProgressionMode, SessionConfig
from core.stimulus import StimulusLibrary, Stimulus
from ui.screens.widgets import (
    make_card, lbl, btn_primary, btn_ghost, inp, _bg, divider,
)
from ui.theme import (
    BG_COLOR, SURFACE, NAV_BG, BORDER, BTN_PRIMARY, BTN_GHOST,
    TEXT_DARK, TEXT_MID, TEXT_LIGHT, TEXT_WHITE, DOT_GREEN,
    FONT_XS, FONT_SM, FONT_MD, FONT_LG,
    PAD_SM, PAD_MD, PAD_LG, BTN_H, INPUT_H,
)

TEST_TYPES = ["SemanticMatching", "FamousFace", "UnknownFace"]
STIM_DIRS  = {
    "SemanticMatching": "semantic_matching",
    "FamousFace":       "famous_face",
    "UnknownFace":      "unknown_face",
}
SCHEMA_NAMES = {
    "SemanticMatching": "semantic_matching.schema.json",
    "FamousFace":       "famous_face.schema.json",
    "UnknownFace":      "unknown_face.schema.json",
}


class ConfigScreen(BoxLayout):
    """
    Full-height configuration form for creating a new session.

    Callbacks:
        on_start_session(config: SessionConfig, stim_set) — fires when the
        user clicks Démarrer and validation passes.
    """

    def __init__(self, base_dir: str, images_base: str, **kwargs):
        kwargs.setdefault("orientation", "vertical")
        kwargs.setdefault("spacing", 0)
        super().__init__(**kwargs)

        self._base_dir    = base_dir
        self._images_base = images_base
        self._on_start_cb: Optional[Callable] = None

        # State
        self._selected_test_type: str          = TEST_TYPES[0]
        self._progression_mode: ProgressionMode = ProgressionMode.CLINICIAN_ACTION
        self._stim_checkboxes: dict            = {}   # stim_id → CheckBox (include)
        self._familiarity_checkboxes: dict     = {}   # stim_id → CheckBox (familiar)
        self._stim_ids: list                   = []   # ordered list
        self._randomize: bool                  = False

        _bg(self, BG_COLOR)

        self._build_header()
        self._build_cards()
        self._build_bottom_bar()

        self._load_stimuli(TEST_TYPES[0])
        self._validate()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _build_header(self):
        header = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(56),
            padding=(dp(PAD_LG), 0),
            spacing=dp(PAD_MD),
        )
        _bg(header, SURFACE)

        title = lbl("Configuration de la Nouvelle Séance",
                    size=FONT_LG, bold=True, color=TEXT_DARK,
                    size_hint_x=0.55, halign="left", valign="middle")
        title.bind(size=title.setter("text_size"))
        header.add_widget(title)

        # Device status badges
        badges = BoxLayout(orientation="horizontal", size_hint_x=0.45,
                           spacing=dp(PAD_SM))
        for badge_text in ("PC Clinicien ✓", "Écran patient ✓", "Bouton externe ✓"):
            b = lbl(badge_text, size=FONT_XS, color=DOT_GREEN,
                    size_hint_x=None, width=dp(110))
            badges.add_widget(b)
        header.add_widget(badges)

        self.add_widget(header)
        self.add_widget(divider())

    def _build_cards(self):
        cards_row = BoxLayout(
            orientation="horizontal",
            spacing=dp(PAD_MD),
            padding=dp(PAD_MD),
        )
        _bg(cards_row, BG_COLOR)

        cards_row.add_widget(self._card_session_data())
        cards_row.add_widget(self._card_params())
        cards_row.add_widget(self._card_stimuli())

        self.add_widget(cards_row)

    def _card_session_data(self):
        card = make_card(spacing=dp(PAD_SM))
        card.add_widget(lbl("Données de la séance", size=FONT_MD, bold=True,
                            size_hint_y=None, height=dp(28),
                            color=TEXT_DARK, halign="left", valign="bottom",
                            text_size=(None, None)))

        card.add_widget(lbl("ID Patient", size=FONT_SM, color=TEXT_MID,
                            size_hint_y=None, height=dp(20)))
        self._inp_patient = inp("Ex: P001")
        self._inp_patient.bind(text=lambda *_: self._validate())
        card.add_widget(self._inp_patient)

        card.add_widget(lbl("Date", size=FONT_SM, color=TEXT_MID,
                            size_hint_y=None, height=dp(20)))
        self._inp_date = inp(str(date.today()))
        self._inp_date.text = str(date.today())
        card.add_widget(self._inp_date)

        card.add_widget(lbl("Heure", size=FONT_SM, color=TEXT_MID,
                            size_hint_y=None, height=dp(20)))
        self._inp_time = inp(datetime.now().strftime("%H:%M:%S"))
        self._inp_time.text = datetime.now().strftime("%H:%M:%S")
        card.add_widget(self._inp_time)

        # Clock confirmation
        confirm_row = BoxLayout(orientation="horizontal", size_hint_y=None,
                                height=dp(32), spacing=dp(8))
        self._chk_clock = CheckBox(size_hint=(None, None), size=(dp(24), dp(24)))
        self._chk_clock.bind(active=lambda *_: self._validate())
        confirm_lbl = lbl("Je confirme que l'heure est exacte",
                          size=FONT_SM, color=TEXT_MID)
        confirm_row.add_widget(self._chk_clock)
        confirm_row.add_widget(confirm_lbl)
        card.add_widget(confirm_row)

        return card

    def _card_params(self):
        card = make_card(spacing=dp(PAD_SM))
        card.add_widget(lbl("Paramètres et progression", size=FONT_MD, bold=True,
                            size_hint_y=None, height=dp(28), color=TEXT_DARK))

        # Electrode + Contact
        row1 = BoxLayout(orientation="horizontal", size_hint_y=None,
                         height=dp(INPUT_H), spacing=dp(PAD_SM))
        self._inp_electrode = inp("Électrode", size_hint_x=0.5)
        self._inp_electrode.bind(text=lambda *_: self._validate())
        self._inp_contact = inp("Contact", size_hint_x=0.5)
        self._inp_contact.bind(text=lambda *_: self._validate())
        row1.add_widget(self._inp_electrode)
        row1.add_widget(self._inp_contact)
        card.add_widget(lbl("Électrode / Contact", size=FONT_SM, color=TEXT_MID,
                            size_hint_y=None, height=dp(20)))
        card.add_widget(row1)

        # Intensité + Durée
        row2 = BoxLayout(orientation="horizontal", size_hint_y=None,
                         height=dp(INPUT_H), spacing=dp(PAD_SM))
        self._inp_intensity = inp("mA", size_hint_x=0.5)
        self._inp_intensity.bind(text=lambda *_: self._validate())
        self._inp_duration = inp("s", size_hint_x=0.5)
        self._inp_duration.bind(text=lambda *_: self._validate())
        row2.add_widget(self._inp_intensity)
        row2.add_widget(self._inp_duration)
        card.add_widget(lbl("Intensité (mA) / Durée (s)", size=FONT_SM, color=TEXT_MID,
                            size_hint_y=None, height=dp(20)))
        card.add_widget(row2)

        # Timer duration (shown only in Timer mode)
        self._timer_row = BoxLayout(orientation="vertical", size_hint_y=None,
                                    height=dp(INPUT_H + 20))
        self._timer_row.add_widget(lbl("Durée minuteur (s)", size=FONT_SM,
                                       color=TEXT_MID, size_hint_y=None, height=dp(20)))
        self._inp_timer = inp("Ex: 5.0")
        self._timer_row.add_widget(self._inp_timer)
        self._timer_row.opacity = 0
        card.add_widget(self._timer_row)

        # Randomize order
        rand_row = BoxLayout(orientation="horizontal", size_hint_y=None,
                             height=dp(30), spacing=dp(8))
        self._chk_randomize = CheckBox(size_hint=(None, None), size=(dp(24), dp(24)))
        self._chk_randomize.bind(active=lambda inst, val: setattr(self, "_randomize", val))
        rand_row.add_widget(self._chk_randomize)
        rand_row.add_widget(lbl("Ordre aléatoire", size=FONT_SM, color=TEXT_DARK))
        card.add_widget(rand_row)

        # Progression mode radios
        card.add_widget(lbl("Mode de progression", size=FONT_SM, color=TEXT_MID,
                            size_hint_y=None, height=dp(24)))

        self._radio_buttons = {}
        radio_options = [
            (ProgressionMode.PATIENT_TOUCH,    "Tactile"),
            (ProgressionMode.CLINICIAN_ACTION, "Action du clinicien"),
            (ProgressionMode.TIMER,            "Minuteur automatique"),
        ]
        for mode, label in radio_options:
            row = BoxLayout(orientation="horizontal", size_hint_y=None,
                            height=dp(30), spacing=dp(8))
            chk = CheckBox(group="progression", allow_no_selection=False,
                           size_hint=(None, None), size=(dp(24), dp(24)))
            chk.active = (mode == ProgressionMode.CLINICIAN_ACTION)
            chk.bind(active=lambda inst, val, m=mode: self._on_progression_change(m, val))
            self._radio_buttons[mode] = chk
            row.add_widget(chk)
            row.add_widget(lbl(label, size=FONT_SM, color=TEXT_DARK))
            card.add_widget(row)

        return card

    def _card_stimuli(self):
        card = make_card(spacing=dp(PAD_SM))
        card.add_widget(lbl("Stimuli", size=FONT_MD, bold=True,
                            size_hint_y=None, height=dp(28), color=TEXT_DARK))

        # Test type dropdown
        card.add_widget(lbl("Type de test", size=FONT_SM, color=TEXT_MID,
                            size_hint_y=None, height=dp(20)))
        self._test_type_btn = Button(
            text=TEST_TYPES[0],
            font_size=dp(FONT_MD),
            size_hint_y=None,
            height=dp(INPUT_H),
            background_normal="",
            background_color=BTN_GHOST,
            color=TEXT_DARK,
        )
        self._test_type_btn.bind(on_press=self._open_test_type_dropdown)
        card.add_widget(self._test_type_btn)

        # Active count label
        self._lbl_stim_count = lbl("0/0 actifs", size=FONT_SM, color=TEXT_MID,
                                    size_hint_y=None, height=dp(20))
        card.add_widget(self._lbl_stim_count)

        # Stim list with checkboxes (scrollable)
        scroll = ScrollView(size_hint=(1, 1))
        self._stim_list = BoxLayout(orientation="vertical", size_hint_y=None,
                                    spacing=dp(4))
        self._stim_list.bind(minimum_height=self._stim_list.setter("height"))
        scroll.add_widget(self._stim_list)
        card.add_widget(scroll)

        return card

    def _build_bottom_bar(self):
        bar = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(64),
            padding=(dp(PAD_LG), dp(PAD_SM)),
            spacing=dp(PAD_MD),
        )
        _bg(bar, SURFACE)

        self._lbl_validation = lbl("", size=FONT_SM, color=(0.8, 0.2, 0.2, 1),
                                   size_hint_x=0.5, halign="left", valign="middle")
        self._lbl_validation.bind(size=self._lbl_validation.setter("text_size"))
        bar.add_widget(self._lbl_validation)

        bar.add_widget(BoxLayout())  # spacer

        self._btn_start = btn_primary("Démarrer la séance",
                                      callback=self._on_start_pressed,
                                      size_hint_x=None, width=dp(220))
        self._btn_start.disabled = True
        bar.add_widget(self._btn_start)

        self.add_widget(divider())
        self.add_widget(bar)

    # ------------------------------------------------------------------
    # Stimuli loading
    # ------------------------------------------------------------------

    def _load_stimuli(self, test_type: str) -> None:
        self._stim_list.clear_widgets()
        self._stim_checkboxes.clear()
        self._stim_ids.clear()

        stim_subdir = STIM_DIRS.get(test_type, "")
        stim_dir    = os.path.join(self._base_dir, "stimuli", stim_subdir)
        schema_name = SCHEMA_NAMES.get(test_type, "")
        schema_path = os.path.join(self._base_dir, "stimuli", "schemas", schema_name)

        lib = StimulusLibrary()
        if os.path.isdir(stim_dir):
            lib.load_from_directory(
                stim_dir,
                test_type,
                schema_path=schema_path if os.path.exists(schema_path) else None,
            )

        stimuli = list(lib._stimuli.values()) if lib._stimuli else []
        self._stim_ids = [s.stimulus_id for s in stimuli]
        self._familiarity_checkboxes.clear()
        is_famous_face = (test_type == "FamousFace")

        for stim in stimuli:
            row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(30),
                            spacing=dp(8))

            chk = CheckBox(size_hint=(None, None), size=(dp(24), dp(24)))
            chk.active = True
            chk.bind(active=lambda *_: self._update_stim_count())
            self._stim_checkboxes[stim.stimulus_id] = chk
            row.add_widget(chk)

            row.add_widget(lbl(stim.stimulus_id, size=FONT_SM, color=TEXT_DARK,
                               halign="left", valign="middle",
                               text_size=(None, None)))

            if is_famous_face:
                fam_chk = CheckBox(size_hint=(None, None), size=(dp(24), dp(24)))
                fam_chk.active = stim.is_familiar is not False  # default familiar
                fam_chk.bind(active=lambda *_: self._update_stim_count())
                self._familiarity_checkboxes[stim.stimulus_id] = fam_chk
                row.add_widget(lbl("Familier", size=FONT_XS, color=TEXT_MID,
                                   size_hint_x=None, width=dp(50)))
                row.add_widget(fam_chk)

            self._stim_list.add_widget(row)

        if not stimuli:
            self._stim_list.add_widget(
                lbl("Aucun stimuli trouvé dans stimuli/" + stim_subdir,
                    size=FONT_SM, color=TEXT_LIGHT,
                    size_hint_y=None, height=dp(30))
            )

        self._update_stim_count()
        self._validate()

    def _update_stim_count(self) -> None:
        active = sum(1 for chk in self._stim_checkboxes.values() if chk.active)
        total  = len(self._stim_checkboxes)
        self._lbl_stim_count.text = f"{active}/{total} actifs"

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validate(self) -> None:
        errors = []

        if not self._inp_patient.text.strip():
            errors.append("ID Patient manquant")
        if not self._inp_electrode.text.strip():
            errors.append("Électrode manquante")
        if not self._inp_contact.text.strip():
            errors.append("Contact manquant")

        try:
            float(self._inp_intensity.text)
            assert float(self._inp_intensity.text) > 0
        except Exception:
            errors.append("Intensité invalide (mA > 0)")

        try:
            float(self._inp_duration.text)
            assert float(self._inp_duration.text) > 0
        except Exception:
            errors.append("Durée invalide (s > 0)")

        if self._progression_mode == ProgressionMode.TIMER:
            try:
                float(self._inp_timer.text)
                assert float(self._inp_timer.text) > 0
            except Exception:
                errors.append("Durée minuteur invalide")

        if not self._chk_clock.active:
            errors.append("Confirmez l'heure")

        active_stims = [sid for sid, chk in self._stim_checkboxes.items() if chk.active]
        if not active_stims:
            errors.append("Aucun stimulus sélectionné")

        if errors:
            self._lbl_validation.text = " · ".join(errors[:2])
            self._btn_start.disabled = True
        else:
            self._lbl_validation.text = ""
            self._btn_start.disabled = False

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_progression_change(self, mode: ProgressionMode, active: bool) -> None:
        if active:
            self._progression_mode = mode
            self._timer_row.opacity = 1 if mode == ProgressionMode.TIMER else 0
            self._validate()

    def _open_test_type_dropdown(self, btn) -> None:
        dd = DropDown()
        for tt in TEST_TYPES:
            item = Button(
                text=tt,
                size_hint_y=None,
                height=dp(40),
                background_normal="",
                background_color=SURFACE,
                color=TEXT_DARK,
                font_size=dp(FONT_MD),
            )
            item.bind(on_press=lambda inst, t=tt: (dd.select(t), None))
            dd.add_widget(item)
        dd.bind(on_select=self._on_test_type_selected)
        dd.open(btn)

    def _on_test_type_selected(self, dd, value: str) -> None:
        self._selected_test_type = value
        self._test_type_btn.text = value
        self._load_stimuli(value)

    def _on_start_pressed(self) -> None:
        if not self._on_start_cb:
            return
        try:
            self._do_start()
        except Exception as exc:
            self._show_start_error(str(exc))

    def _show_start_error(self, message: str) -> None:
        from kivy.uix.popup import Popup
        from kivy.uix.button import Button
        content = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(10))
        content.add_widget(Label(text=f"Erreur au démarrage :\n{message}",
                                 color=(0.8, 0.2, 0.2, 1), halign="center"))
        btn = Button(text="OK", size_hint_y=None, height=dp(40))
        popup = Popup(title="Erreur", content=content, size_hint=(0.6, 0.4))
        btn.bind(on_press=popup.dismiss)
        content.add_widget(btn)
        popup.open()

    def _do_start(self) -> None:
        # Exclude unchecked stimuli AND (for FamousFace) non-familiar ones
        non_familiar = {
            sid for sid, chk in self._familiarity_checkboxes.items() if not chk.active
        }
        included = [
            sid for sid, chk in self._stim_checkboxes.items()
            if chk.active and sid not in non_familiar
        ]
        excluded = [
            sid for sid, chk in self._stim_checkboxes.items()
            if not chk.active or sid in non_familiar
        ]

        timer_s: Optional[float] = None
        if self._progression_mode == ProgressionMode.TIMER:
            try:
                timer_s = float(self._inp_timer.text)
            except ValueError:
                pass

        try:
            session_date = date.fromisoformat(self._inp_date.text.strip())
        except ValueError:
            session_date = date.today()

        try:
            from datetime import time as dtime
            parts = self._inp_time.text.strip().split(":")
            session_time = dtime(int(parts[0]), int(parts[1]),
                                 int(parts[2]) if len(parts) > 2 else 0)
        except Exception:
            session_time = datetime.now().time()

        config = SessionConfig(
            patient_id         = self._inp_patient.text.strip(),
            session_date       = session_date,
            session_start_time = session_time,
            test_type          = self._selected_test_type,
            electrode          = self._inp_electrode.text.strip(),
            contact            = self._inp_contact.text.strip(),
            stim_intensity_mA  = float(self._inp_intensity.text),
            stim_duration_s    = float(self._inp_duration.text),
            progression_mode   = self._progression_mode,
            timer_duration_s   = timer_s,
            stim_signal_key    = "f12",
            screen_width_px    = 1920,
            screen_height_px   = 1080,
            software_version   = "1.0.0",
            stimuli_included   = included,
            stimuli_excluded   = excluded,
            randomize_order    = self._randomize,
        )

        # Build StimulusSet from selected IDs
        stim_subdir = STIM_DIRS.get(self._selected_test_type, "")
        stim_dir    = os.path.join(self._base_dir, "stimuli", stim_subdir)
        schema_name = SCHEMA_NAMES.get(self._selected_test_type, "")
        schema_path = os.path.join(self._base_dir, "stimuli", "schemas", schema_name)

        lib = StimulusLibrary()
        if os.path.isdir(stim_dir):
            lib.load_from_directory(
                stim_dir,
                self._selected_test_type,
                schema_path=schema_path if os.path.exists(schema_path) else None,
            )
        else:
            # Placeholder so UI launches with empty dir
            lib.add(Stimulus(
                stimulus_id      = "SM_001",
                task_type        = self._selected_test_type,
                payload          = {
                    "center_image": "", "left_image": "", "right_image": "",
                    "center_label": "—", "left_label": "Option A",
                    "right_label": "Option B", "semantic_category": "placeholder",
                },
                correct_response = "left",
                left_right_balance = "left",
            ))

        stim_set = lib.build_set(
            randomize=self._randomize,
            included=included if included else None,
        )

        self._on_start_cb(config, stim_set)

    # ------------------------------------------------------------------
    # Callback registration
    # ------------------------------------------------------------------

    def on_start_session(self, callback: Callable) -> None:
        self._on_start_cb = callback
