# CogniBattery

### Clinical-grade cognitive testing platform for intraoperative and neuropsychological research


![Python](https://img.shields.io/badge/Python-3.10+-blue)
![Kivy](https://img.shields.io/badge/UI-Kivy-green)
![License](https://img.shields.io/badge/license-MIT-lightgrey)
![Research](https://img.shields.io/badge/use-Research%20%2F%20Clinical-purple)

---

CogniBattery is a dual-screen cognitive testing platform designed for clinical and neuroscience research environments. It presents cognitive tasks on a **patient display** while clinicians monitor and control the session from a dedicated **control interface**.

Every stimulus event, response, stimulation trigger, and error is written synchronously to disk to ensure **crash-safe experimental logging**.
=======
CogniBattery delivers a dual-screen stimulus presentation suite with crash-safe event logging, hardware trigger support, and a clean clinician interface - purpose-built for demanding clinical and research environments.


---

## Overview

CogniBattery runs a dual-display experiment environment:

- **Patient Screen** — full-screen stimulus presentation
- **Clinician Screen** — monitoring, control, and logging interface

All experimental events are recorded with precise timestamps and written to disk immediately, ensuring robust data capture even under unexpected interruptions.

### Tasks

| Task | ID Prefix | Description |
|---|---|---|
| Semantic Matching | `SM_NNN` | Patient selects the semantically matching image from a set of three |
| Famous Face Recognition | `FF_NNN` | Patient responds Oui/Non to a famous person's face |
| Unknown Face Recognition | `UF_NNN` | Patient responds Oui/Non to a novel face |

---

## System Architecture

```
Clinician Screen
      │
      ▼
KivyApp  (UI layer — passive views, no domain state)
      │
      ▼
App  (domain controller — session lifecycle, event loop)
      │
      ▼
Session  (trial management, progression, stim timing)
      │
      ▼
PersistentEventLog  (fsync on every write)
      │
      ▼
CSV + metadata.json + _hash.txt
```

Core modules (`core/`, `tasks/`, `data/`) are fully independent from the UI layer. All UI callbacks flow upward to `App`.

---

## Features

- **Dual-screen Kivy UI** — clinician control panel + full-screen patient display span a single window across two monitors
- **Crash-safe event log** — every write is flushed and fsynced; no data is lost on power failure or crash
- **Hardware triggers** — TTL pulses via serial port, LabStreamingLayer (LSL) markers, or composite (both simultaneously)
- **Stimulation signal listener** — F-key or external USB button fires `STIM_START` events via `pynput`
- **JSON stimulus schemas** — stimuli are validated against JSON Schema (draft-07) at load time
- **Session metadata sidecar** — `session_metadata.json` captures config, stimulus set, and counterbalancing info
- **SHA-256 integrity hash** — `_hash.txt` sidecar written after every session for data provenance
- **Crash recovery** — detects incomplete sessions on startup and offers resumption
- **Counterbalancing checks** — machine-readable rules validate stimulus set balance before the session starts

---

## Project Structure

```
CogniBattery/
├── main.py                         Entry point
├── app.py                          App orchestrator (session lifecycle)
│
├── core/
│   ├── timing.py                   Clock (perf_counter + ISO timestamps)
│   ├── event_log.py                PersistentEventLog — fsync on every write
│   ├── session.py                  SessionConfig, ProgressionMode, Session
│   ├── stimulus.py                 Stimulus, StimulusLibrary, StimulusSet
│   ├── stim_signal.py              StimSignalListener (pynput, F-key trigger)
│   ├── trigger.py                  TTLTrigger / LSLTrigger / CompositeTrigger
│   └── recovery.py                 Crash recovery helpers
│
├── tasks/
│   ├── base_task.py                BaseTask (abstract)
│   ├── semantic_matching.py        SemanticMatchingTask
│   ├── famous_face.py              FamousFaceTask
│   └── unknown_face.py             UnknownFaceTask
│
├── ui/
│   ├── kivy_app.py                 KivyApp — Kivy application shell
│   ├── clinician_screen.py         Clinician view (nav + session mode)
│   ├── patient_screen.py           Patient view
│   ├── theme.py                    Color and font constants
│   ├── widgets/
│   │   ├── fixation_widget.py      Black screen + fixation cross
│   │   ├── semantic_matching_widget.py  3-image touch layout
│   │   ├── face_widget.py          Face + Oui/Non buttons
│   │   └── timer_bar_widget.py     Draining progress bar
│   └── screens/
│       ├── config_screen.py        Session configuration form
│       ├── session_screen.py       Active session view
│       ├── bank_screen.py          Stimulus bank (search / filter / paginate)
│       └── history_screen.py       CSV history + event journal
│
├── data/
│   ├── file_manager.py             No-overwrite CSV path management
│   ├── csv_exporter.py             Post-hoc CSV rebuilder
│   ├── session_metadata.py         JSON sidecar writer/reader
│   └── integrity.py                SHA-256 hash sidecar writer/verifier
│
└── stimuli/
    ├── schemas/                    JSON Schema files (draft-07)
    ├── semantic_matching/          SM_NNN.json planches
    ├── famous_face/                FF_NNN.json planches
    ├── unknown_face/               UF_NNN.json planches
    └── images/                     Stimulus images (referenced by relative path)
```

---

## Installation

**Requirements:** Python 3.10+

```bash
# 1. Clone the repository
git clone https://github.com/Sana7Codes/CogniBattery.git
cd CogniBattery

# 2. Create and activate a virtual environment
python -m venv batteryenv
source batteryenv/bin/activate   # Windows: batteryenv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt
```

### Optional dependencies

| Package | Purpose |
|---|---|
| `pynput` | External F-key / USB button → `STIM_START` signal |
| `pyserial` | TTL pulses via USB-to-serial adapter |
| `pylsl` | LabStreamingLayer EEG marker stream |
| `jsonschema` | Validate stimulus JSON files against schemas |

All optional packages are listed in `requirements.txt`. The application degrades gracefully if any are absent.

---

## Running

```bash
python main.py
```

The app opens a spanning window: **1280 px clinician panel** on the left, **1920 px patient display** on the right. Adjust dimensions in `main.py` if your monitors differ.

### Dual-monitor setup

Position both monitors side-by-side. The window is placed at `(0, 0)` and spans both screens automatically. No separate display configuration is required.

---

## Stimulus Files

Each stimulus is a JSON file validated against its task schema at load time.

**Semantic Matching example** — `stimuli/semantic_matching/SM_001.json`:

```json
{
  "stimulus_id": "SM_001",
  "category": "animals",
  "target_image": "images/SM/cat.png",
  "foil_images": ["images/SM/car.png", "images/SM/house.png"],
  "correct_index": 0
}
```

Image paths are relative to `stimuli/images/`. Load a directory with:

```python
from core.stimulus import StimulusLibrary

lib = StimulusLibrary.load_from_directory(
    "stimuli/semantic_matching",
    task_type="semantic_matching"
)
```

Counterbalancing rules live in `stimuli/schemas/counterbalancing_rules.json` and are checked automatically before each session.

---

## Data Output

Each session produces three files under `output/<patient_id>/<date>/`:

| File | Contents |
|---|---|
| `<session_id>.csv` | Full event log |
| `<session_id>_metadata.json` | Session config, stimulus set, counterbalancing report |
| `<session_id>_hash.txt` | SHA-256 hash of the CSV for integrity verification |

### CSV columns

```
Time_s | Time_iso | Event | Essai | Stimulus | Response | Correct | TR_s | TouchX | TouchY | Notes
```

`STIM_START` notes format:

```
StimID=N;Electrode=X;Contact=Y;Intensity_mA=Z;Duration_s=W;Signal=K
```

---

## Hardware Triggers

### TTL (serial port)

```python
from core.trigger import TTLTrigger, CompositeTrigger

trigger = CompositeTrigger()
trigger.add(TTLTrigger(port="/dev/ttyUSB0", baudrate=115200))
kivy_app.trigger = trigger
```

### LabStreamingLayer

```python
from core.trigger import LSLTrigger, CompositeTrigger

trigger = CompositeTrigger()
trigger.add(LSLTrigger(stream_name="CogniBattery"))
kivy_app.trigger = trigger
```

Both backends can be combined in a single `CompositeTrigger`. Triggers fire on every logged event type.

---

## Architecture Notes

- **Passive UI** — screens hold no domain state; all callbacks flow upward to `App`
- **Thread safety** — `pynput` callbacks are bridged to the Kivy main thread via `Clock.schedule_once(..., 0)`
- **Retina / HiDPI** — window sizing accounts for the `density` factor via `Window.system_size`
- **Clean shutdown** — `App.run()` calls `session.end()` in a `finally` block regardless of how the session exits

---

## License

For research and clinical use. See `LICENSE` for details.
