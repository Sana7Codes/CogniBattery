import os
import sys
os.environ['KIVY_NO_ENV_CONFIG'] = '1'
os.environ['KIVY_NO_ARGS']       = '1'   # prevent Kivy from consuming sys.argv
os.environ['KIVY_LOG_LEVEL']     = 'warning'
os.environ['SDL_VIDEO_HIGHDPI_DISABLED'] = '1'  # prevent crash on mixed-DPI spanning (Retina + external)

from ui.kivy_app import KivyApp

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
IMAGES_BASE = os.path.join(BASE_DIR, "stimuli", "images")

if __name__ == "__main__":
    single = "--single-screen" in sys.argv
    KivyApp(
        base_dir    = BASE_DIR,
        images_base = IMAGES_BASE,
        clinician_w = 735  if single else 1470,
        patient_w   = 735  if single else 1920,
        screen_h    = 900  if single else 956,
    ).run()
