"""
Screen configuration helpers.

The standard dual-screen setup:
  Screen 0 — clinician MacBook display (tkinter)
  Screen 1 — patient OLED touchscreen (PsychoPy)

In --single-screen mode both windows go to screen 0 for laptop testing.
"""

import config


def patient_screen_index(single_screen: bool = False) -> int:
    """Return the PsychoPy screen index for the patient window."""
    if single_screen:
        return 0
    return config.PATIENT_SCREEN


def clinician_screen_index(single_screen: bool = False) -> int:
    """Return the screen index for the clinician tkinter window."""
    if single_screen:
        return 0
    return config.CLINICIAN_SCREEN


def screen_description() -> str:
    return (
        f"Patient screen: {config.PATIENT_SCREEN} | "
        f"Clinician screen: {config.CLINICIAN_SCREEN}"
    )
