"""
HistoryScreen — Session history viewer with event log.

Left panel: searchable session list + dossiers toggle
Right panel: selected session header + event journal
"""
import csv
import glob
import os
import subprocess
from typing import Optional

from kivy.graphics import Color, Rectangle, RoundedRectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.checkbox import CheckBox

from ui.screens.widgets import make_card, lbl, btn_primary, btn_ghost, inp, _bg, divider
from ui.theme import (
    BG_COLOR, SURFACE, NAV_BG, BORDER, BTN_GHOST, BTN_PRIMARY,
    TEXT_DARK, TEXT_MID, TEXT_LIGHT, TEXT_WHITE, DOT_GREEN,
    FONT_XS, FONT_SM, FONT_MD, FONT_LG,
    PAD_SM, PAD_MD, PAD_LG, BTN_H,
)


class HistoryScreen(BoxLayout):
    """Session history browser with event log viewer."""

    def __init__(self, base_dir: str, **kwargs):
        kwargs.setdefault("orientation", "vertical")
        kwargs.setdefault("spacing", 0)
        super().__init__(**kwargs)

        self._base_dir       = base_dir
        self._output_dir     = os.path.join(base_dir, "output")
        self._sessions       = []    # list of dicts
        self._selected       = None  # currently viewed session dict
        self._checked        = set() # checked session filepaths
        self._list_mode      = True  # True=list, False=dossiers

        _bg(self, BG_COLOR)
        self._build_header()
        self._build_body()
        self._load_sessions()
        self._refresh_list()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _build_header(self):
        header = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(56),
            padding=(dp(PAD_LG), dp(8)),
            spacing=dp(PAD_MD),
        )
        _bg(header, SURFACE)
        header.add_widget(lbl("Historique", size=FONT_LG, bold=True,
                               color=TEXT_DARK, size_hint_x=0.3))
        header.add_widget(BoxLayout())

        self._btn_export = btn_ghost("Exporter la sélection (0)",
                                      size_hint_x=None, width=dp(220))
        self._btn_open = btn_ghost("Ouvrir le dossier",
                                    callback=self._open_output_folder,
                                    size_hint_x=None, width=dp(160))
        header.add_widget(self._btn_export)
        header.add_widget(self._btn_open)
        self.add_widget(header)
        self.add_widget(divider())

    def _build_body(self):
        body = BoxLayout(orientation="horizontal", spacing=dp(PAD_MD),
                         padding=dp(PAD_MD))
        _bg(body, BG_COLOR)

        body.add_widget(self._build_left_panel())
        body.add_widget(_vdivider())
        body.add_widget(self._build_right_panel())

        self.add_widget(body)

    def _build_left_panel(self):
        left = BoxLayout(orientation="vertical", size_hint_x=0.48,
                         spacing=dp(PAD_SM))

        # Search + toggle
        toolbar = BoxLayout(orientation="horizontal", size_hint_y=None,
                            height=dp(40), spacing=dp(PAD_SM))
        self._inp_search = inp("Rechercher...", size_hint_x=0.7)
        self._inp_search.bind(text=lambda *_: self._refresh_list())

        self._btn_list = Button(
            text="Liste",
            size_hint_x=0.15,
            size_hint_y=None,
            height=dp(40),
            background_normal="",
            background_color=BTN_PRIMARY,
            color=TEXT_WHITE,
            font_size=dp(FONT_SM),
        )
        self._btn_tree = Button(
            text="Dossiers",
            size_hint_x=0.15,
            size_hint_y=None,
            height=dp(40),
            background_normal="",
            background_color=BTN_GHOST,
            color=TEXT_DARK,
            font_size=dp(FONT_SM),
        )
        self._btn_list.bind(on_press=lambda *_: self._set_mode(True))
        self._btn_tree.bind(on_press=lambda *_: self._set_mode(False))
        toolbar.add_widget(self._inp_search)
        toolbar.add_widget(self._btn_list)
        toolbar.add_widget(self._btn_tree)
        left.add_widget(toolbar)

        scroll = ScrollView()
        self._session_list = BoxLayout(orientation="vertical", size_hint_y=None,
                                       spacing=0)
        self._session_list.bind(minimum_height=self._session_list.setter("height"))
        scroll.add_widget(self._session_list)
        left.add_widget(scroll)

        return left

    def _build_right_panel(self):
        right = BoxLayout(orientation="vertical", size_hint_x=0.52,
                          spacing=dp(PAD_SM))

        self._right_placeholder = lbl("Sélectionnez une séance", size=FONT_MD,
                                      color=TEXT_LIGHT, halign="center",
                                      valign="middle")
        self._right_placeholder.bind(size=self._right_placeholder.setter("text_size"))
        right.add_widget(self._right_placeholder)

        self._right_detail = BoxLayout(orientation="vertical", spacing=dp(PAD_SM))
        self._right_detail.opacity = 0

        # Header
        self._lbl_patient_detail = lbl("—", size=FONT_LG, bold=True, color=TEXT_DARK,
                                       size_hint_y=None, height=dp(30))
        self._lbl_filename_detail = lbl("—", size=FONT_SM, color=TEXT_MID,
                                        size_hint_y=None, height=dp(20))
        self._right_detail.add_widget(self._lbl_patient_detail)
        self._right_detail.add_widget(self._lbl_filename_detail)

        # Tag chips row
        self._tags_row = BoxLayout(orientation="horizontal", size_hint_y=None,
                                   height=dp(28), spacing=dp(8))
        self._right_detail.add_widget(self._tags_row)
        self._right_detail.add_widget(divider())

        # Event journal
        self._right_detail.add_widget(lbl("Journal d'événements", size=FONT_MD,
                                          bold=True, color=TEXT_DARK,
                                          size_hint_y=None, height=dp(28)))
        scroll2 = ScrollView()
        self._event_list = BoxLayout(orientation="vertical", size_hint_y=None,
                                     spacing=dp(2))
        self._event_list.bind(minimum_height=self._event_list.setter("height"))
        scroll2.add_widget(self._event_list)
        self._right_detail.add_widget(scroll2)
        right.add_widget(self._right_detail)

        return right

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------

    def _load_sessions(self) -> None:
        self._sessions = []
        if not os.path.isdir(self._output_dir):
            return
        for filepath in sorted(
            glob.glob(os.path.join(self._output_dir, "**", "*.csv"), recursive=True),
            reverse=True,
        ):
            meta = self._parse_csv_meta(filepath)
            self._sessions.append(meta)

    def _parse_csv_meta(self, filepath: str) -> dict:
        """Read SESSION_START row to extract session metadata."""
        patient_id = os.path.basename(filepath).split("_")[0]
        test_type  = ""
        date_str   = ""
        duration   = ""
        intensity  = ""
        electrode  = ""
        contact    = ""

        try:
            with open(filepath, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get("Event") == "SESSION_START":
                        notes = row.get("Notes", "")
                        for part in notes.split(";"):
                            if "=" in part:
                                k, v = part.split("=", 1)
                                k = k.strip()
                                if k == "PatientID":     patient_id = v
                                elif k == "TestType":    test_type  = v
                                elif k == "Duration_s":  duration   = v + "s"
                                elif k == "Intensity_mA": intensity = v + "mA"
                                elif k == "Electrode":   electrode  = v
                                elif k == "Contact":     contact    = v
                        break
            # Date from file path or mtime
            import datetime
            mtime    = os.path.getmtime(filepath)
            date_str = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
        except Exception:
            pass

        return {
            "filepath":   filepath,
            "filename":   os.path.basename(filepath),
            "patient_id": patient_id,
            "date":       date_str,
            "test_type":  test_type,
            "duration":   duration,
            "intensity":  intensity,
            "electrode":  electrode,
            "contact":    contact,
        }

    # ------------------------------------------------------------------
    # List rendering
    # ------------------------------------------------------------------

    def _refresh_list(self) -> None:
        query = self._inp_search.text.strip().lower() if hasattr(self, "_inp_search") else ""
        filtered = [
            s for s in self._sessions
            if query in s["patient_id"].lower() or query in s["filename"].lower()
        ]
        self._session_list.clear_widgets()
        if self._list_mode:
            for s in filtered:
                self._session_list.add_widget(self._make_list_row(s))
        else:
            self._render_tree(filtered)

    def _make_list_row(self, s: dict) -> BoxLayout:
        row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(44),
                        padding=(dp(PAD_SM), 0), spacing=dp(8))
        _bg(row, SURFACE)

        chk = CheckBox(size_hint=(None, None), size=(dp(24), dp(24)))
        chk.active = s["filepath"] in self._checked
        chk.bind(active=lambda inst, val, fp=s["filepath"]: self._toggle_check(fp, val))
        row.add_widget(chk)

        row.add_widget(lbl(s["patient_id"], size=FONT_SM, color=TEXT_DARK,
                           size_hint_x=0.25, halign="left", valign="middle",
                           text_size=(None, None)))
        row.add_widget(lbl(s["date"], size=FONT_XS, color=TEXT_MID,
                           size_hint_x=0.30, halign="left", valign="middle",
                           text_size=(None, None)))
        row.add_widget(lbl(s["test_type"], size=FONT_XS, color=TEXT_MID,
                           size_hint_x=0.35, halign="left", valign="middle",
                           text_size=(None, None)))

        row.bind(on_touch_down=lambda inst, touch: (
            inst.collide_point(*touch.pos) and self._select_session(s)
        ))
        self._session_list.add_widget(divider())
        return row

    def _render_tree(self, sessions: list) -> None:
        """Simple flat tree grouped by patient_id."""
        by_patient: dict = {}
        for s in sessions:
            by_patient.setdefault(s["patient_id"], []).append(s)

        for pid, group in sorted(by_patient.items()):
            folder_lbl = lbl(f"📁 {pid}", size=FONT_SM, bold=True, color=TEXT_DARK,
                              size_hint_y=None, height=dp(30))
            self._session_list.add_widget(folder_lbl)
            for s in group:
                file_btn = Button(
                    text=f"  📄 {s['filename']}",
                    font_size=dp(FONT_XS),
                    size_hint_y=None,
                    height=dp(26),
                    background_normal="",
                    background_color=SURFACE,
                    color=TEXT_MID,
                    halign="left",
                    valign="middle",
                )
                file_btn.bind(on_press=lambda inst, sess=s: self._select_session(sess))
                self._session_list.add_widget(file_btn)

    def _set_mode(self, list_mode: bool) -> None:
        self._list_mode = list_mode
        self._btn_list.background_color = BTN_PRIMARY if list_mode else BTN_GHOST
        self._btn_tree.background_color = BTN_GHOST if list_mode else BTN_PRIMARY
        self._btn_list.color = TEXT_WHITE if list_mode else TEXT_DARK
        self._btn_tree.color = TEXT_DARK if list_mode else TEXT_WHITE
        self._refresh_list()

    def _toggle_check(self, filepath: str, active: bool) -> None:
        if active:
            self._checked.add(filepath)
        else:
            self._checked.discard(filepath)
        self._btn_export.text = f"Exporter la sélection ({len(self._checked)})"

    # ------------------------------------------------------------------
    # Detail panel
    # ------------------------------------------------------------------

    def _select_session(self, s: dict) -> None:
        self._selected = s
        self._right_placeholder.opacity = 0
        self._right_detail.opacity      = 1

        self._lbl_patient_detail.text  = s["patient_id"]
        self._lbl_filename_detail.text = s["filename"]

        # Tags
        self._tags_row.clear_widgets()
        for tag in [s["test_type"], s["duration"], s["intensity"],
                    f"{s['electrode']} + {s['contact']}"]:
            if tag.strip(" +"):
                self._tags_row.add_widget(_tag(tag))

        # Event journal
        self._event_list.clear_widgets()
        events = self._read_events(s["filepath"])
        for ts, desc in events:
            row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(22),
                            spacing=dp(8))
            row.add_widget(lbl(ts, size=FONT_XS, color=TEXT_MID,
                               size_hint_x=None, width=dp(70)))
            row.add_widget(lbl(desc, size=FONT_SM, color=TEXT_DARK,
                               halign="left", valign="middle", text_size=(None, None)))
            self._event_list.add_widget(row)
            self._event_list.add_widget(divider())

    def _read_events(self, filepath: str) -> list:
        """Parse CSV rows into (timestamp, description) pairs."""
        events = []
        try:
            with open(filepath, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    ts   = row.get("Time_s", "")
                    evt  = row.get("Event", "")
                    stim = row.get("Stimulus", "")
                    resp = row.get("Response", "")
                    note = row.get("Notes", "")

                    if evt == "SESSION_START":
                        desc = "Début de la séance"
                    elif evt == "SESSION_END":
                        desc = "Fin de la séance"
                    elif evt == "TRIAL_START":
                        desc = f"Essai démarré — {stim}"
                    elif evt == "RESPONSE":
                        desc = f"Réponse: {resp}"
                    elif evt == "STIM_START":
                        desc = "Stimulation déclenchée"
                    elif evt == "STIM_END":
                        desc = "Stimulation terminée"
                    elif evt == "NOTE":
                        desc = f"Note: {note}"
                    elif evt == "ERROR":
                        desc = f"Erreur: {note[:60]}"
                    else:
                        desc = f"{evt} {note[:40]}"

                    events.append((f"{ts}s", desc))
        except Exception:
            pass
        return events

    def _open_output_folder(self) -> None:
        try:
            subprocess.Popen(["open", self._output_dir])
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Local helpers
# ---------------------------------------------------------------------------

def _vdivider():
    d = BoxLayout(size_hint_x=None, width=dp(1))
    with d.canvas.before:
        Color(*BORDER)
        rect = Rectangle(pos=d.pos, size=d.size)
    d.bind(
        pos=lambda i, v: setattr(rect, "pos", v),
        size=lambda i, v: setattr(rect, "size", v),
    )
    return d


def _tag(text: str) -> Label:
    chip = Label(
        text=text,
        font_size=dp(FONT_XS),
        color=TEXT_DARK,
        size_hint=(None, None),
        size=(dp(max(60, len(text) * 7)), dp(24)),
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


# Expose NAV_BG at module level for column headers
from ui.theme import NAV_BG
