# Battery — Computerized Cognitive Battery for SEEG Research

A dual-screen clinical application for administering cognitive tasks to patients undergoing
stereo-electroencephalography (SEEG) recordings with intracerebral electrical stimulation (IES).
Developed at the **CRéER / ERCN-IMoPA laboratory, Université de Lorraine, Nancy, France**.

---

## Clinical Context

Drug-resistant epilepsy patients undergoing pre-surgical SEEG evaluation are often stimulated
intracerebrally to map eloquent cortex and characterize seizure networks. This software provides
a standardized cognitive battery that runs concurrently with stimulation so that the neurological
team can probe the functional impact of IES on cognition in real time.

The software is designed for use in a shielded environment (ICU/EEG lab). The patient interacts
with a touch-enabled OLED display; the neurologist monitors the session from a separate clinician
screen and controls trial pacing without interrupting the patient.

---

## What the Software Does

- **Dual-screen delivery**: patient receives a full-screen PsychoPy stimulus window (screen 1,
  1280×800 OLED); the neurologist sees a live tkinter control panel on screen 0
- **8 cognitive tasks** covering face recognition, semantic matching, picture naming, and pointing
- **IES timing**: a TTL pulse is sent to the Micromed SystemPLUS at every IMAGE_ON event so that
  SEEG recordings can be epoch-locked to stimulus onset; stimulation itself is initiated
  **externally** by the medical team via the Micromed hardware button — the software never
  triggers stimulation
- **Epoch classification**: every response is automatically classified relative to stimulation
  windows (`pré-stim`, `per-stim`, `limite-stim`, `post-stim`)
- **Session output**: real-time crash-safe CSV event log, post-session summary CSV, and a
  five-sheet colour-coded Excel report
- **Clinician controls**: skip/exclude/replace stimuli, update stimulation parameters mid-session,
  annotate, abort

---

## Cognitive Tasks

| Code | Display Name | Response Type | Description |
|------|-------------|---------------|-------------|
| `FFP_V1` | Visages célèbres – pointage V1 | 3-choice touch (gauche / centre / droite) | Patient points to the famous face among three faces on a composite image (version 1 stimulus set) |
| `FFP_V2` | Visages célèbres – pointage V2 | 3-choice touch | Same paradigm with version 2 stimulus set; familiar-face pre-check available |
| `MUF_V1` | Appariement visages inconnus V1 | 2-choice touch (gauche / droite) | Patient matches a central face to one of two peripheral faces by identity (unknown faces, V1) |
| `MUF_V2` | Appariement visages inconnus V2 | 2-choice touch | Same paradigm, version 2 stimulus set |
| `ASM_MOTS` | Appariement sémantique – mots | 2-choice touch | Patient matches a central image to one of two peripheral images by semantic category (word-based stimuli) |
| `ASM_SEEG` | Appariement sémantique – SEEG sans déno V2 | 2-choice touch | Semantic matching adapted for SEEG with no verbal naming component, V2 |
| `DI_SEEG` | Dénomination d'images SEEG 2024 | Verbal (clinician scores) | Picture naming — patient names the image aloud; neurologist presses **K** (correct) or **X** (incorrect) |
| `FNP` | Noms célèbres – pointage | 3-choice touch | Patient points to the target position associated with a famous person's name |

### Familiarity Pre-check (FFP_V1 / FFP_V2)
Before the FFP tasks start, the clinician can scroll through each stimulus image and mark it
as *Familier* or *Non familier*. Unfamiliar images are excluded from the trial list so that the
patient is only tested on faces they recognise.

---

## Hardware Integrations

### Patient Display
- Screen index 1 (configurable via `config.PATIENT_SCREEN`)
- Target hardware: MG160-QT01 OLED, 1280×800
- Managed by PsychoPy `visual.Window`

### Clinician Display
- Screen index 0 (`config.CLINICIAN_SCREEN`) — the operator's built-in laptop screen
- Managed by tkinter

### Micromed SystemPLUS (TTL triggers)
Communication over USB-to-serial (`/dev/tty.usbserial-FTXXXXX`, 115200 baud).

| Code | Event | Notes |
|------|-------|-------|
| `1`  | `IMAGE_ON` | Sent immediately after the stimulus image appears on screen |

**Important**: the software sends **only code 1**. Stimulation start and end are controlled
entirely by the medical team via the dedicated button on the Micromed unit. The software detects
`STIM_START` / `STIM_END` events when the clinician presses the configured key (default `f12`).

### EyeLink 1000+
The integration architecture is in place (`hardware/eyelink.py`) with call sites already wired
through the trial loop. `RealEyeLink` raises `NotImplementedError` and the system falls back to
`MockEyeLink` (no-op) in all current sessions.

> **TODO**: Implement `RealEyeLink` using the `pylink` SDK to enable gaze-locked epochs.

### Touchscreen
PsychoPy `Mouse` events are used for touch input. Responses within 150 ms of image onset are
discarded to prevent phantom carry-over clicks from the previous trial.

---

## Project Structure

```
Battery/
├── run.py                    # Entry point — argument parsing, main loop
├── config.py                 # Global constants (screen indices, TTL codes, paths)
│
├── core/
│   ├── event_log.py          # EventLog, EventType enum, compute_stim_epochs()
│   ├── session.py            # Session and StimParams dataclasses
│   ├── stimulus.py           # Stimulus and StimulusSet (trial management)
│   ├── timing.py             # Monotonic session clock
│   └── error_log.py          # File-backed error/info/warning logger
│
├── data/
│   ├── session_writer.py     # CSV/Excel report writers, file naming
│   └── csv_exporter.py       # Standalone CSV rebuild from event list
│
├── hardware/
│   ├── micromed.py           # RealTrigger / MockTrigger (TTL via pyserial)
│   ├── eyelink.py            # RealEyeLink / MockEyeLink stubs
│   └── screens.py            # Screen index helpers
│
├── tasks/
│   ├── base_task.py          # BaseTask ABC — counterbalance check, check_correct()
│   ├── famous_face.py        # FamousFaceTask (FFP_V1, FFP_V2, FNP)
│   ├── semantic_matching.py  # SemanticMatchingTask (MUF, ASM, DI_SEEG)
│   └── csv_loader.py         # TASK_FOLDERS dict, load_trials(), task_folder()
│
├── ui/
│   ├── setup_form.py         # Pre-session clinician form (tkinter)
│   ├── patient_window.py     # Trial loop, PsychoPy stimulus delivery
│   ├── clinician_window.py   # Live control panel (tkinter subprocess)
│   └── widgets/              # Shared widget helpers
│
├── stimuli/                  # Stimulus images and trials.csv files (not in repo)
│   ├── Famous-face-pointing-V1.jpg/
│   ├── Famous-face-pointing-V2/
│   ├── matching-unknown-face-V1/
│   ├── matching-unknown-face-V2/
│   ├── Appariement-seumantique-mots/
│   ├── Appariement-seumantique-SEEG_sansDeunoV2_2/
│   ├── Deunomination-dCOimages-SEEG-2024/
│   └── famous-names-pointing/
│
├── sessions/                 # Output data (created at runtime)
├── logs/                     # Error and info logs (created at runtime)
└── output/                   # Scratch output directory
```

Each task folder under `stimuli/` must contain:
- `trials.csv` — trial list (see column schemas below)
- Image files referenced by `filename` column

---

## Setup and Installation

### Requirements
- **Python 3.11** — PsychoPy is incompatible with Python 3.12+
- macOS (tested) or Linux; Windows untested

### 1. Create the conda environment

```bash
conda create -n py311 python=3.11
conda activate py311
```

### 2. Install dependencies

```bash
pip install psychopy==2026.1.3
pip install openpyxl pillow numpy pyserial
```

For real EyeLink support (not yet implemented):
```bash
pip install pylink-sr-research  # SR Research pylink SDK
```

### 3. Prepare stimuli

Copy the `stimuli/` directory (provided separately) to the project root.
Each task subfolder must contain a `trials.csv` with the appropriate schema:

| Task(s) | Required columns |
|---------|-----------------|
| `MUF_V1`, `MUF_V2` | `filename`, `correct_side` |
| `ASM_MOTS`, `ASM_SEEG` | `filename`, `stimulus`, `correct`, `correct_side` |
| `DI_SEEG` | `filename`, `correct_label`, `item_number` |
| `FFP_V1`, `FFP_V2`, `FNP` | `filename`, `target_person`, `target_position` |

---

## Running a Session

### Development / laptop testing (no hardware)
```bash
conda activate py311
python run.py --mock --single-screen --no-fullscreen
```

### Pre-selecting task and patient
```bash
python run.py --mock --single-screen --no-fullscreen --task MUF_V1 --patient 023
```

### Full hardware deployment (dual screens, Micromed connected)
```bash
python run.py --no-mock --task FFP_V1 --patient 042
```

### CLI flags

| Flag | Default | Description |
|------|---------|-------------|
| `--mock` / `--no-mock` | `--mock` | Use mock hardware (no TTL, no EyeLink) |
| `--single-screen` | off | Both windows on screen 0 (laptop testing) |
| `--no-fullscreen` | off | Windowed patient display (fullscreen by default) |
| `--task CODE` | None | Pre-fill task code in the setup form |
| `--patient ID` | `TEST` | Pre-fill patient ID |

---

## Session Flow

```
run.py
  └─ SetupForm (clinician screen)
       Clinician fills in: patient ID, task, electrode, contact, mA, duration,
       progression mode, STIM key, stimulus order.
       FFP tasks: optional familiarity pre-check.
       ↓
  └─ _run_one_session()
       ├─ Launches ClinicianWindow in a separate subprocess (tkinter)
       ├─ Runs run_session() in the main process (PsychoPy)
       │    Trial loop:
       │      IMAGE_ON → TTL code 1 → start response timer
       │      Await response (touch / keyboard / clinician action / timer)
       │      Log RESPONSE event
       │      Clinician presses f12 → log STIM_START / STIM_END
       ├─ Natural end: files written → PsychoPy closed → clinician finalize dialog
       │    Clinician adds notes → "Sauvegarder et fermer" or "Abandonner"
       └─ Returns session summary → back to SetupForm for next session
```

### Progression Modes

| Mode | Advance trigger |
|------|----------------|
| `PatientTouch` | First valid touch/keyboard response |
| `ClinicianAction` | Clinician clicks "Essai suivant" |
| `Timer` | Configurable delay (default 5 s) or first response, whichever comes first |

---

## Data Output

All output files are written to:
```
sessions/Patient_{patient_id}/{YYYY-MM-DD}/{task_code}/
```

### 1. Event log CSV (crash-safe, written incrementally)
**Filename**: `Patient_{id}_{date}_{HH-MM}_{task}_Contact{elec}-{cont}_{mA}mA_{dur}s.csv`

Header block (lines prefixed `#`) contains session metadata:
`SessionID`, `PatientID`, `SessionDate`, `SessionStartTime`, `TestType`,
`Electrode`, `Contact`, `StimulationIntensity_mA`, `StimulationDuration_s`,
`ProgressionMode`, `StimSignalKey`, `StimuliOrder`, `ScreenWidth_px`,
`ScreenHeight_px`, `StimuliIncluded`, `StimuliExcluded`, `CounterBalance`

Data columns:

| Column | Type | Description |
|--------|------|-------------|
| `Time_s` | float | Seconds since session start (monotonic clock) |
| `Time_iso` | str | ISO 8601 wall-clock timestamp |
| `Event` | str | EventType value (see below) |
| `Essai` | int | Trial number |
| `Stimulus` | str | Stimulus `planche_id` |
| `Response` | str | Patient response zone or verbal answer |
| `Correct` | str | `Yes` / `No` / blank |
| `TR_s` | float | Response time in seconds from IMAGE_ON |
| `stim_epoch` | str | `pré-stim` / `per-stim` / `limite-stim` / `post-stim` |
| `TouchX` | float | Normalised X coordinate of touch |
| `TouchY` | float | Normalised Y coordinate of touch |
| `Notes` | str | Epoch boundary annotation or clinician notes |

**EventType values**: `SESSION_START`, `TRIAL_START`, `IMAGE_ON`, `RESPONSE`,
`STIM_START`, `STIM_END`, `TRIAL_END`, `STIMULUS_SKIP`, `STIMULUS_EXCLUDE`,
`STIMULUS_REPLACE`, `SESSION_END`, `NOTE`, `SESSION_NOTES`

**Stim epoch classification** (computed after session end):

| Epoch | Condition |
|-------|-----------|
| `pré-stim` | No stim window overlaps IMAGE_ON or RESPONSE |
| `per-stim` | IMAGE_ON **and** RESPONSE both inside a stim window |
| `limite-stim` | IMAGE_ON before window start, RESPONSE inside — leading boundary; `Notes` = `IMAGE_ON avant STIM_START (+Xs)` |
| `per-stim` *(annotated)* | IMAGE_ON inside window, RESPONSE after window end — trailing boundary; `Notes` = `RESPONSE après STIM_END (+Xs)` |
| `post-stim` | IMAGE_ON after the most recent stim window |

### 2. Summary CSV
**Filename**: `*_summary.csv`

Columns: `task`, `n_trials`, `n_correct`, `mean_TR_s`, `sd_TR_s`, `n_timeout`,
`n_skipped`, `n_stim_events`, then per-epoch breakdowns:
`n_trials_{pre|per|limite|post}`, `n_correct_{pre|per|limite|post}`,
`mean_TR_{pre|per|limite|post}`

### 3. Excel report (`.xlsx`)
Five sheets:

| Sheet | Content |
|-------|---------|
| **Résumé** | Clinical summary: session info, global accuracy, TR stats, stimulation detail blocks, clinician notes |
| **Journal des essais** | One row per trial: stimulus, image time, response, expected, correct, TR, epoch, stim-active flag, boundary notes |
| **Analyse par stimulation** | (if stimulation occurred) Trials grouped by stim window, classified in four colour-coded columns: PRÉ-STIM / PER-STIM / LIMITE / POST-STIM |
| **Métadonnées** | Full session metadata key-value table |
| **Événements bruts** | Complete event log in French, colour-coded by epoch |

---

## EyeLink Integration

The call sites are wired throughout the trial loop (connect on startup, `start_recording` /
`stop_recording` per trial, `send_message` at IMAGE_ON and RESPONSE). All calls currently route
to `MockEyeLink` (no-ops) regardless of the `--mock` flag. Replace the factory return value in
`hardware/eyelink.py → make_eyelink()` with `RealEyeLink()` once the `pylink` SDK is integrated.

---

## IPC Architecture

The clinician window runs in a **separate subprocess** to avoid tkinter / PsychoPy event-loop
conflicts. Communication is via two `multiprocessing.Queue` objects:

- `to_clin_q` — patient process → clinician window (trial updates, stats, session end)
- `from_clin_q` — clinician window → patient process / run.py (skip, abort, finalize, quit)

---

## Configuration

Edit `config.py` to change defaults without touching CLI flags:

```python
MOCK_HARDWARE  = True        # True = no real hardware
PATIENT_SCREEN = 1           # PsychoPy screen index
CLINICIAN_SCREEN = 0         # tkinter screen index
DATA_DIR       = "data/"
STIMULI_DIR    = "stimuli/"
LOGS_DIR       = "logs/"
STIM_KEY       = "f12"       # Key the operator presses to log STIM_START/STIM_END
TTL_IMAGE_ON   = 1           # Byte value sent to Micromed serial port at IMAGE_ON
SOFTWARE_VERSION = "1.0.0"
```

---

## Authors

- **Sana Haidar** — software development
- **Dr. Jonas** — neurologist, CHU Nancy — clinical design and validation

CRéER / ERCN-IMoPA laboratory — Université de Lorraine, Nancy, France
