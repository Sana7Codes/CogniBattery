"""
Visual constants for the clinical cognitive testing platform.
Light, medical-grade palette matching the Figma prototype.
"""

# Backgrounds
BG_COLOR    = (0.976, 0.941, 0.933, 1)  # #F9EFED blush page bg
SURFACE     = (1.0,   1.0,   1.0,   1)  # #FFFFFF white cards
NAV_BG      = (0.906, 0.906, 0.906, 1)  # #E7E7E7 nav bar

# Borders / dividers
BORDER      = (0.878, 0.878, 0.878, 1)  # #E0E0E0

# Buttons
BTN_PRIMARY = (0.255, 0.255, 0.255, 1)  # #414141 charcoal
BTN_GHOST   = (0.820, 0.820, 0.820, 1)  # #D1D1D1 ghost/secondary
BTN_DANGER  = (0.780, 0.180, 0.180, 1)  # #C72E2E red

# Text
TEXT_DARK   = (0.102, 0.102, 0.102, 1)  # #1A1A1A
TEXT_MID    = (0.420, 0.420, 0.420, 1)  # #6B6B6B
TEXT_LIGHT  = (0.650, 0.650, 0.650, 1)  # placeholder / disabled
TEXT_WHITE  = (1.0,   1.0,   1.0,   1)

# Status
DOT_GREEN   = (0.20,  0.70,  0.35,  1)  # session-live dot
STIM_ON_BG  = (0.85,  0.96,  0.88,  1)  # light green tint when stim ON

# Font sizes (dp)
FONT_XS = 11
FONT_SM = 13
FONT_MD = 15
FONT_LG = 18
FONT_XL = 22

# Layout (dp)
RADIUS   = 8
PAD_SM   = 8
PAD_MD   = 16
PAD_LG   = 24
BTN_H    = 44
NAV_H    = 56
INPUT_H  = 40

# Legacy aliases (used by unchanged widgets)
PANEL_COLOR   = NAV_BG
ACCENT_GREEN  = DOT_GREEN
ACCENT_RED    = BTN_DANGER
ACCENT_ORANGE = (0.85, 0.55, 0.10, 1)
TEXT_COLOR    = TEXT_DARK
FONT_SIZE_SM  = FONT_SM
FONT_SIZE_MD  = FONT_MD
FONT_SIZE_LG  = FONT_LG
FONT_SIZE_XL  = FONT_XL
BUTTON_HEIGHT = BTN_H
HEADER_HEIGHT = NAV_H
