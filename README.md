# CogniBattery

### Clinical-grade cognitive testing platform for intraoperative and neuropsychological research


![Python](https://img.shields.io/badge/Python-3.10+-blue)
![Kivy](https://img.shields.io/badge/UI-Kivy-green)
![License](https://img.shields.io/badge/license-MIT-lightgrey)
![Research](https://img.shields.io/badge/use-Research%20%2F%20Clinical-purple)
![Standalone](https://img.shields.io/badge/network-standalone%20%2F%20offline-orange)

---

CogniBattery is a standalone dual-screen cognitive testing platform built for clinical neuroscience research — specifically for use during **stereo-EEG (SEEG) intracranial stimulation** sessions. It presents cognitive tasks on a **patient touchscreen** while the clinician monitors and controls the session from a dedicated **control interface**.


Every stimulus event, patient response, stimulation timestamp, and error is written synchronously to disk to guarantee **crash-safe experimental logging** with no data loss.

> **Safety note:** CogniBattery never triggers electrical stimulation. `STIM_START` is a passive timestamp of an external event — it records *when* the medical team triggered the stimulator, not *whether* to trigger it.

---

## Clinical Context

Patients undergoing invasive EEG monitoring have depth electrodes implanted in the brain. During stimulation of specific electrode contacts, they perform cognitive tasks to assess whether stimulation of a given brain region influences cognitive performance (recognition, association, etc.).

CogniBattery provides the software infrastructure to:

- present tasks on the patient touchscreen
- timestamp every event relative to the stimulation window
- export structured data for clinical and research analysis

The platform runs entirely **offline** — no network connection, no cloud services, no external dependencies at runtime.
=======
Every stimulus event, response, stimulation trigger, and error is written synchronously to disk to ensure **crash-safe experimental logging**.
=======
CogniBattery delivers a dual-screen stimulus presentation suite with crash-safe event logging, hardware trigger support, and a clean clinician interface - purpose-built for demanding clinical and research environments.



---

## Overview

CogniBattery runs a dual-display experiment environment:

- **Patient Screen** — full-screen stimulus presentation, touch response only; no correction, no timer, no stimulation status shown
- **Clinician Screen** — full supervision: current stimulus, correct answer, response accuracy, trial statistics, countdown timer, and STIMULATION ON / OFF status

### Tasks

| Task | ID Prefix | Description |
|---|---|---|
| Semantic Matching | `SM_NNN` | Patient touches the semantically matching image from a planche of three |
| Famous Face Recognition | `FF_NNN` | Patient responds Oui/Non to a famous person's face |
| Unknown Face Recognition | `UF_NNN` | Patient responds Oui/Non to a novel face |

Each task reproduces the structure of existing clinical PowerPoint planches with left/right counterbalancing, image proportion preservation, and automatic screen adaptation.

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
Session  (trial management, progression modes, stim timing)
      │
      ▼
PersistentEventLog  (fsync on every write)
      │
      ▼
CSV  +  metadata.json  +  _hash.txt
```

Core modules (`core/`, `tasks/`, `data/`) are fully independent from the UI layer. All UI callbacks flow upward to `App`.

---

## Features

**Session management**
- **Three progression modes** — `PatientTouch` (patient advances), `ClinicianAction` (clinician advances), `Timer` (auto-advance after a configurable delay)
- **Familiarity pre-validation** — for Famous Face tasks, clinician can mark stimuli as unrecognised and exclude them before the session begins
- **Live stimulus management** — skip, exclude, or replace a stimulus mid-session; all actions are journalled

**Event logging**
- **Crash-safe event log** — every write is flushed and fsynced; no data is lost on power failure
- **STIM_START timestamping** — external USB button or F-key records the stimulation onset without triggering the stimulator
- **STIM_END auto-computation** — `Time(STIM_END) = Time(STIM_START) + StimulationDuration_s`; no second button press required
- **Multiple stimulations per session** — repeated STIM_START/STIM_END pairs are all recorded, each with their full electrode/contact/intensity/duration parameters

**Data integrity**
- **Session metadata sidecar** — `session_metadata.json` captures config, stimulus set, counterbalancing report, and all stimulation parameters
- **SHA-256 integrity hash** — `_hash.txt` sidecar written after every session for data provenance
- **No silent overwrite** — if a session CSV already exists, a new name is generated or the start is blocked with an explicit error

**Reliability**
- **Crash recovery** — detects incomplete sessions on startup and offers resumption
- **Standalone operation** — no internet connection, no network services, no cloud dependencies
- **Hardware trigger outputs** — TTL pulses via serial port and/or LabStreamingLayer (LSL) EEG marker stream

**Stimulus system**
- **JSON stimulus schemas** — stimuli validated against JSON Schema (draft-07) at load time
- **Counterbalancing checks** — machine-readable rules verified before each session

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
│   ├── patient_screen.py           Patient view (touch only, no feedback)
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
    ├── schemas/                    JSON Schema files (draft-07) + counterbalancing rules
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
| `pynput` | External F-key / USB button → passive `STIM_START` timestamp |
| `pyserial` | TTL output pulses via USB-to-serial adapter |
| `pylsl` | LabStreamingLayer EEG marker stream output |
| `jsonschema` | Validate stimulus JSON files against schemas |

The application degrades gracefully if any optional package is absent.

---

## Running

```bash
python main.py
```

The app opens a spanning window: **1280 px clinician panel** on the left, **1920 px patient display** on the right. Adjust dimensions in `main.py` to match your monitors.

### Dual-monitor setup

Position both monitors side-by-side. The window is placed at `(0, 0)` and spans both screens automatically. No separate display configuration is required.

> Before each session, verify that the computer clock and the stimulation equipment clock are synchronised. Neither device is connected to the Internet, so manual verification is required.

---

## Session Workflow

### 1 — Configure

The clinician fills in the session form:

- `PatientID` (required — session cannot start without it)
- Session date and time (system time is shown for reference)
- Test type, electrode, contact, stimulation intensity (mA), duration (s)
- Stimulus selection and ordering (random or fixed)
- Progression mode: `PatientTouch` / `ClinicianAction` / `Timer`
- For Famous Face tasks: familiarity pre-validation — mark unrecognised faces for exclusion before the session begins

### 2 — Run

- Each trial: `TRIAL_START` → `IMAGE_ON` → `RESPONSE` → `TRIAL_END`
- Clinician sees: current stimulus, correct answer, accuracy, trial number, elapsed timer, STIM ON/OFF status
- Patient sees: stimulus and response choices only — no correction, no timer, no stimulation status
- Medical staff presses the external button → `STIM_START` is timestamped; `STIM_END` is computed automatically
- Clinician can skip, exclude, or replace any stimulus at any time; all actions are logged

### 3 — Save

At session end, three files are written to `Data/<PatientID>/<Date>/<TestType>/`:

| File | Contents |
|---|---|
| `<session_id>.csv` | Metadata block + full event log |
| `<session_id>_metadata.json` | Session config, stimulus set, counterbalancing report |
| `<session_id>_hash.txt` | SHA-256 hash of the CSV for integrity verification |

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

Counterbalancing rules live in `stimuli/schemas/counterbalancing_rules.json` and are verified automatically before each session.

---

## Data Output

### File naming

```
Patient_023_2025-03-04_14-32_Association_ContactA1-A2_1.5mA_3s.csv
```

Each filename encodes: PatientID, date, time, test type, electrode contact, intensity, and duration — so context is preserved even if the file is moved.

### Folder structure

```
Data/
└── Patient_023/
    └── 2025-03-04/
        ├── Association/
        │   └── Patient_023_2025-03-04_14-32_Association_ContactA1-A2_1.5mA_3s.csv
        └── Faces/
            └── Patient_023_2025-03-04_15-10_Faces_ContactB1-B2_2.0mA_3s.csv
```

### CSV format

Each file begins with a `#`-prefixed metadata block, followed by the event log table.

```
# SessionID,023_2025-03-04_14-32_Association_A1-A2
# SoftwareVersion,1.0.0
# PatientID,023
# SessionDate,2025-03-04
# SessionStartTime,14:32:10
# TestType,Association
# Electrode,A
# Contact,A1-A2
# StimulationIntensity_mA,1.5
# StimulationDuration_s,3
# ProgressionMode,PatientTouch
# StimSignalKey,F12
# ScreenWidth_px,1920
# ScreenHeight_px,1080
# StimuliIncluded,SM_001;SM_002;SM_003
# StimuliExcluded,

Time_s,Time_iso,Event,Essai,Stimulus,Response,Correct,TR_s,TouchX,TouchY,Notes
0.000,2025-03-04T14:32:10.000,TRIAL_START,1,,,,,,,
0.050,2025-03-04T14:32:10.050,IMAGE_ON,1,SM_001,,,,,,
0.812,2025-03-04T14:32:10.812,RESPONSE,1,SM_001,river,Yes,0.762,812,463,
1.000,2025-03-04T14:32:11.000,TRIAL_END,1,,,,,,,
1.200,2025-03-04T14:32:11.200,TRIAL_START,2,,,,,,,
1.240,2025-03-04T14:32:11.240,IMAGE_ON,2,SM_002,,,,,,
1.950,2025-03-04T14:32:11.950,STIM_START,,,,,,,,,StimID=1;Electrode=A;Contact=A1-A2;Intensity_mA=1.5;Duration_s=3;Signal=F12
2.110,2025-03-04T14:32:12.110,RESPONSE,2,SM_002,house,Yes,0.870,905,510,
4.950,2025-03-04T14:32:14.950,STIM_END,,,,,,,,,StimID=1;AutoComputed=True
5.000,2025-03-04T14:32:15.000,TRIAL_END,2,,,,,,,
```

### CSV columns

| Column | Description |
|---|---|
| `Time_s` | Seconds since session start (`t=0` at session launch) |
| `Time_iso` | Absolute timestamp, ISO 8601 |
| `Event` | Event type (see below) |
| `Essai` | Trial number |
| `Stimulus` | Planche/stimulus identifier |
| `Response` | Patient's selected response |
| `Correct` | `Yes` / `No` |
| `TR_s` | Reaction time in seconds — `Time(RESPONSE) − Time(IMAGE_ON)` — only for `RESPONSE` events |
| `TouchX` / `TouchY` | Touch coordinates in pixels on the patient screen |
| `Notes` | Free-form field (stimulation parameters, clinician comments, exclusion reason) |

### Event types

| Event | Description |
|---|---|
| `TRIAL_START` | Beginning of a trial |
| `IMAGE_ON` | Stimulus displayed on patient screen |
| `RESPONSE` | Touch response recorded |
| `TRIAL_END` | End of trial |
| `STIM_START` | Stimulation onset — timestamped from external button press |
| `STIM_END` | Stimulation offset — auto-computed: `Time(STIM_START) + Duration_s` |
| `STIMULUS_SKIP` | Trial skipped by clinician |
| `STIMULUS_EXCLUDE` | Stimulus excluded from the remainder of the session |
| `STIMULUS_REPLACE` | Stimulus replaced mid-session |

`STIM_START` and `STIM_END` are independent events — they are not bound to any trial and the `Essai` field is left blank. Multiple stimulation pairs may occur within a single session (e.g. repeated stimulation at different intensities or contacts); all are recorded in the same event log with full parameters.

---

## Hardware Triggers

Output triggers fire on every logged event and can be used to synchronise the EEG recording system.

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

Both backends can be combined in a single `CompositeTrigger`.

---

## Architecture Notes

- **Passive UI** — screens hold no domain state; all callbacks flow upward to `App`
- **Thread safety** — `pynput` callbacks are bridged to the Kivy main thread via `Clock.schedule_once(..., 0)`
- **Retina / HiDPI** — window sizing accounts for the `density` factor via `Window.system_size`
- **Clean shutdown** — `App.run()` calls `session.end()` in a `finally` block regardless of how the session exits
- **Extensible** — architecture supports future addition of eye-tracking, voice recording, and dedicated results navigation interfaces

---

## License

For research and clinical use. See `LICENSE` for details.
