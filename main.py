import os
os.environ['KIVY_NO_ENV_CONFIG'] = '1'
os.environ['KIVY_LOG_LEVEL'] = 'warning'

from ui.kivy_app import KivyApp

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
IMAGES_BASE = os.path.join(BASE_DIR, "stimuli", "images")

if __name__ == "__main__":
    KivyApp(
        base_dir    = BASE_DIR,
        images_base = IMAGES_BASE,
        clinician_w = 1280,
        patient_w   = 1920,
        screen_h    = 1080,
    ).run()
