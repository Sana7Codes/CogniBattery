"""
Global configuration for the Battery clinical application.
Override at runtime via run.py command-line flags.
"""

MOCK_HARDWARE: bool = True        # True = no real hardware required
PATIENT_SCREEN: int = 1           # PsychoPy screen index for patient OLED
CLINICIAN_SCREEN: int = 0         # Clinician display
DATA_DIR: str = "data/"
STIMULI_DIR: str = "stimuli/"
LOGS_DIR: str = "logs/"
STIM_KEY: str = "f12"             # Key pressed by staff to mark STIM_START
TTL_IMAGE_ON: int = 1             # TTL code sent to Micromed at IMAGE_ON
SOFTWARE_VERSION: str = "1.0.0"
