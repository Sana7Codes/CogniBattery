"""
Shared widget helpers for the clinician UI screens.
All sizing uses dp() for resolution independence.
"""
from kivy.graphics import Color, Rectangle, Line, RoundedRectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput

from ui.theme import (
    SURFACE, BORDER, BTN_PRIMARY, BTN_GHOST, BTN_DANGER,
    TEXT_DARK, TEXT_MID, TEXT_WHITE, TEXT_LIGHT,
    FONT_SM, FONT_MD, FONT_LG, PAD_SM, PAD_MD, BTN_H, INPUT_H, RADIUS,
)


def _bg(widget, color):
    """Attach a filled Rectangle background to any widget."""
    with widget.canvas.before:
        c = Color(*color)
        rect = Rectangle(pos=widget.pos, size=widget.size)
    widget.bind(
        pos=lambda i, v: setattr(rect, "pos", v),
        size=lambda i, v: setattr(rect, "size", v),
    )
    return rect


def _repaint_bg(widget, color):
    """Replace canvas.before with a new solid colour rectangle."""
    widget.canvas.before.clear()
    with widget.canvas.before:
        Color(*color)
        rect = Rectangle(pos=widget.pos, size=widget.size)
    widget.bind(
        pos=lambda i, v: setattr(rect, "pos", v),
        size=lambda i, v: setattr(rect, "size", v),
    )


def make_card(orientation="vertical", padding=PAD_MD, spacing=PAD_SM, **kwargs):
    """White BoxLayout with rounded border — use as a card container."""
    layout = BoxLayout(
        orientation=orientation,
        padding=dp(padding),
        spacing=dp(spacing),
        **kwargs,
    )
    with layout.canvas.before:
        Color(*SURFACE)
        rr = RoundedRectangle(pos=layout.pos, size=layout.size, radius=[dp(RADIUS)])
        Color(*BORDER)
        ln = Line(
            rounded_rectangle=(layout.x, layout.y, layout.width, layout.height, dp(RADIUS)),
            width=1,
        )
    def _upd(inst, val):
        rr.pos  = inst.pos
        rr.size = inst.size
        ln.rounded_rectangle = (inst.x, inst.y, inst.width, inst.height, dp(RADIUS))
    layout.bind(pos=_upd, size=_upd)
    return layout


def lbl(text="", size=FONT_MD, bold=False, color=TEXT_DARK, **kwargs):
    return Label(text=text, font_size=dp(size), bold=bold, color=color, **kwargs)


def btn_primary(text, callback=None, **kwargs):
    kwargs.setdefault("size_hint_y", None)
    kwargs.setdefault("height", dp(BTN_H))
    b = Button(
        text=text,
        font_size=dp(FONT_MD),
        bold=True,
        background_normal="",
        background_color=BTN_PRIMARY,
        color=TEXT_WHITE,
        **kwargs,
    )
    if callback:
        b.bind(on_press=lambda *_: callback())
    return b


def btn_ghost(text, callback=None, **kwargs):
    kwargs.setdefault("size_hint_y", None)
    kwargs.setdefault("height", dp(BTN_H))
    b = Button(
        text=text,
        font_size=dp(FONT_MD),
        background_normal="",
        background_color=BTN_GHOST,
        color=TEXT_DARK,
        **kwargs,
    )
    if callback:
        b.bind(on_press=lambda *_: callback())
    return b


def btn_danger(text, callback=None, **kwargs):
    kwargs.setdefault("size_hint_y", None)
    kwargs.setdefault("height", dp(BTN_H))
    b = Button(
        text=text,
        font_size=dp(FONT_MD),
        bold=True,
        background_normal="",
        background_color=BTN_DANGER,
        color=TEXT_WHITE,
        **kwargs,
    )
    if callback:
        b.bind(on_press=lambda *_: callback())
    return b


def inp(hint="", size_hint_x=1.0, **kwargs):
    return TextInput(
        hint_text=hint,
        multiline=False,
        size_hint=(size_hint_x, None),
        height=dp(INPUT_H),
        font_size=dp(FONT_MD),
        foreground_color=TEXT_DARK,
        hint_text_color=TEXT_LIGHT,
        background_color=SURFACE,
        cursor_color=TEXT_DARK,
        **kwargs,
    )


def divider(height=1):
    """Thin horizontal separator."""
    d = BoxLayout(size_hint_y=None, height=dp(height))
    with d.canvas.before:
        Color(*BORDER)
        rect = Rectangle(pos=d.pos, size=d.size)
    d.bind(
        pos=lambda i, v: setattr(rect, "pos", v),
        size=lambda i, v: setattr(rect, "size", v),
    )
    return d
