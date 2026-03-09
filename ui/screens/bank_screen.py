"""
BankScreen — Stimulus bank browser.

Shows all JSON stimuli across stimuli/ subdirectories in a scrollable table.
Supports search by ID and category filter.
"""
import glob
import json
import os
from typing import Optional

from kivy.graphics import Color, Rectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.dropdown import DropDown
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput

from ui.screens.widgets import make_card, lbl, btn_primary, btn_ghost, inp, _bg, divider
from ui.theme import (
    BG_COLOR, SURFACE, NAV_BG, BORDER, BTN_GHOST,
    TEXT_DARK, TEXT_MID, TEXT_LIGHT, TEXT_WHITE,
    FONT_XS, FONT_SM, FONT_MD, FONT_LG,
    PAD_SM, PAD_MD, PAD_LG, BTN_H, NAV_H,
)

ROWS_PER_PAGE = 5
STIM_SUBDIRS  = ["semantic_matching", "famous_face", "unknown_face"]
CATEGORIES    = ["Toutes", "semantic_matching", "famous_face", "unknown_face"]


class BankScreen(BoxLayout):
    """Stimulus bank table with search, filter, and pagination."""

    def __init__(self, base_dir: str, **kwargs):
        kwargs.setdefault("orientation", "vertical")
        kwargs.setdefault("spacing", 0)
        super().__init__(**kwargs)

        self._base_dir   = base_dir
        self._all_rows   = []   # list of dicts
        self._filtered   = []   # after search/filter
        self._page       = 0
        self._cat_filter = "Toutes"

        _bg(self, BG_COLOR)

        self._build_header()
        self._build_toolbar()
        self._build_table()
        self._build_pagination()

        self._load_all_stimuli()
        self._refresh()

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
        header.add_widget(lbl("Banque de stimuli", size=FONT_LG, bold=True,
                              color=TEXT_DARK, size_hint_x=0.6))
        header.add_widget(BoxLayout())
        header.add_widget(btn_primary("+ Ajouter un stimulus", size_hint_x=None,
                                      width=dp(200)))
        self.add_widget(header)
        self.add_widget(divider())

    def _build_toolbar(self):
        bar = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(52),
            padding=(dp(PAD_MD), dp(6)),
            spacing=dp(PAD_MD),
        )
        _bg(bar, BG_COLOR)

        self._inp_search = inp("Rechercher...", size_hint_x=0.55)
        self._inp_search.bind(text=lambda *_: self._on_search())
        bar.add_widget(self._inp_search)

        self._cat_btn = Button(
            text="Toutes",
            font_size=dp(FONT_MD),
            size_hint=(None, None),
            size=(dp(200), dp(40)),
            background_normal="",
            background_color=BTN_GHOST,
            color=TEXT_DARK,
        )
        self._cat_btn.bind(on_press=self._open_cat_dropdown)
        bar.add_widget(self._cat_btn)
        bar.add_widget(BoxLayout())
        self.add_widget(bar)

    def _build_table(self):
        # Column headers
        col_header = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(32),
            padding=(dp(PAD_MD), 0),
            spacing=dp(4),
        )
        _bg(col_header, NAV_BG)
        for col, w in COLUMNS:
            col_header.add_widget(
                lbl(col, size=FONT_SM, bold=True, color=TEXT_MID,
                    size_hint_x=w, halign="left", valign="middle",
                    text_size=(None, None))
            )
        self.add_widget(col_header)


        scroll = ScrollView(size_hint=(1, 1))
        self._rows_layout = BoxLayout(orientation="vertical", size_hint_y=None,
                                      spacing=0)
        self._rows_layout.bind(minimum_height=self._rows_layout.setter("height"))
        scroll.add_widget(self._rows_layout)
        self.add_widget(scroll)

    def _build_pagination(self):
        bar = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(48),
            padding=(dp(PAD_MD), dp(6)),
            spacing=dp(PAD_MD),
        )
        _bg(bar, SURFACE)

        self._btn_prev = btn_ghost("← Précédent",
                                    callback=self._prev_page,
                                    size_hint_x=None, width=dp(140))
        self._lbl_page = lbl("Page 1", size=FONT_SM, color=TEXT_MID)
        self._btn_next = btn_ghost("Suivant →",
                                    callback=self._next_page,
                                    size_hint_x=None, width=dp(140))
        bar.add_widget(self._btn_prev)
        bar.add_widget(BoxLayout())
        bar.add_widget(self._lbl_page)
        bar.add_widget(BoxLayout())
        bar.add_widget(self._btn_next)
        self.add_widget(divider())
        self.add_widget(bar)

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _load_all_stimuli(self) -> None:
        self._all_rows = []
        for subdir in STIM_SUBDIRS:
            dirpath = os.path.join(self._base_dir, "stimuli", subdir)
            if not os.path.isdir(dirpath):
                continue
            for filepath in sorted(glob.glob(os.path.join(dirpath, "*.json"))):
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    stim_id   = data.get("stimulus_id", os.path.basename(filepath))
                    filename  = os.path.basename(filepath)
                    mtime     = os.path.getmtime(filepath)
                    from datetime import datetime
                    date_str  = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
                    is_excl   = data.get("is_excluded", False)
                    self._all_rows.append({
                        "stim_id":  stim_id,
                        "filename": filename,
                        "category": subdir,
                        "date":     date_str,
                        "excluded": is_excl,
                        "filepath": filepath,
                    })
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # Filtering & pagination
    # ------------------------------------------------------------------

    def _on_search(self) -> None:
        self._page = 0
        self._refresh()

    def _refresh(self) -> None:
        query = self._inp_search.text.strip().lower()
        self._filtered = [
            r for r in self._all_rows
            if (self._cat_filter in ("Toutes", r["category"]))
            and (query in r["stim_id"].lower() or query in r["filename"].lower())
        ]
        self._render_page()

    def _render_page(self) -> None:
        self._rows_layout.clear_widgets()
        start = self._page * ROWS_PER_PAGE
        page_rows = self._filtered[start: start + ROWS_PER_PAGE]

        for row in page_rows:
            self._rows_layout.add_widget(self._make_row(row))

        total_pages = max(1, -(-len(self._filtered) // ROWS_PER_PAGE))
        self._lbl_page.text = f"Page {self._page + 1} / {total_pages}"
        self._btn_prev.disabled = (self._page == 0)
        self._btn_next.disabled = (self._page >= total_pages - 1)

    def _make_row(self, row: dict):
        container = BoxLayout(orientation="horizontal", size_hint_y=None,
                              height=dp(44), padding=(dp(PAD_MD), 0), spacing=dp(4))
        _bg(container, SURFACE)

        for col, w in COLUMNS[:-1]:
            key = COL_KEY_MAP.get(col, "")
            val = str(row.get(key, ""))
            container.add_widget(
                lbl(val, size=FONT_SM, color=TEXT_DARK, size_hint_x=w,
                    halign="left", valign="middle", text_size=(None, None))
            )

        # État toggle
        is_excl = row["excluded"]
        state_btn = Button(
            text="Exclus" if is_excl else "Actif",
            font_size=dp(FONT_XS),
            size_hint_x=COLUMNS[-1][1],
            background_normal="",
            background_color=BTN_GHOST if is_excl else (0.20, 0.65, 0.35, 1),
            color=TEXT_DARK if is_excl else (1, 1, 1, 1),
        )
        state_btn.bind(on_press=lambda btn, r=row: self._toggle_excluded(r, btn))
        container.add_widget(state_btn)
        container.add_widget(divider())
        return container

    def _toggle_excluded(self, row: dict, btn: Button) -> None:
        row["excluded"] = not row["excluded"]
        # Persist to JSON
        try:
            with open(row["filepath"], "r", encoding="utf-8") as f:
                data = json.load(f)
            data["is_excluded"] = row["excluded"]
            with open(row["filepath"], "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception:
            pass
        self._refresh()

    # ------------------------------------------------------------------
    # Pagination
    # ------------------------------------------------------------------

    def _prev_page(self) -> None:
        if self._page > 0:
            self._page -= 1
            self._render_page()

    def _next_page(self) -> None:
        total_pages = max(1, -(-len(self._filtered) // ROWS_PER_PAGE))
        if self._page < total_pages - 1:
            self._page += 1
            self._render_page()

    # ------------------------------------------------------------------
    # Category dropdown
    # ------------------------------------------------------------------

    def _open_cat_dropdown(self, btn) -> None:
        dd = DropDown()
        for cat in CATEGORIES:
            item = Button(
                text=cat,
                size_hint_y=None,
                height=dp(40),
                background_normal="",
                background_color=SURFACE,
                color=TEXT_DARK,
                font_size=dp(FONT_MD),
            )
            item.bind(on_press=lambda inst, c=cat: (dd.select(c), None))
            dd.add_widget(item)
        dd.bind(on_select=self._on_cat_selected)
        dd.open(btn)

    def _on_cat_selected(self, dd, value: str) -> None:
        self._cat_filter = value
        self._cat_btn.text = value
        self._page = 0
        self._refresh()


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

COLUMNS = [
    ("ID Stimulus",    0.18),
    ("Nom du fichier", 0.25),
    ("Catégorie",      0.18),
    ("Date d'ajout",   0.15),
    ("État",           0.14),
]

COL_KEY_MAP = {
    "ID Stimulus":    "stim_id",
    "Nom du fichier": "filename",
    "Catégorie":      "category",
    "Date d'ajout":   "date",
    "État":           "excluded",
}


