```.gitignore
# Python
__pycache__/
*.py[cod]
.venv/
.ruff_cache/

# PyInstaller output / intermediates
build/
dist/
```

```README.md
# skm — SKM-2PO communication/measurement mechanism (standalone app)

A standalone application that replicates the communication and measurement
mechanism of SKM devices, extracted by reverse engineering the CKM2PO.exe
binary. Python core package + PySide6 GUI; works without real hardware via
a byte-level SKM-23 simulator built from the RE'd protocol.

Package layout (uv, `src/`):

- `src/skm/constants.py` — protocol constants (commands, sentinel, retry
  counts) with the Ghidra evidence references,
- `src/skm/transport.py` — byte transport ABC + FTDI D2XX transport (ctypes,
  for the Win10 VM / real hardware) + loopback transport for tests,
- `src/skm/simulator.py` — byte-level fake SKM device (CKM-23 behaviour RE'd
  from CKM2PO.exe; faithful reply shapes + measurement stream),
- `src/skm/protocol.py` — low-level exchange helpers mirroring the app's
  drain/send/sleep/accumulate-receive pattern (TX buffer DAT_0059e764,
  RX DAT_00596764, error sentinel 0x499602D2),
- `src/skm/device.py` — high-level operations: discovery, speakers 'U'/'V',
  selects 'I','M','B','C','D','E', range 'R', channels 'X'/'Y', queries
  'F'/'Q'/'J', generator 'H', measurement 'N'/'S' capture,
- `src/skm/measurement.py` — stream capture → 65536-point spectrum (numpy
  FFT) mirroring FUN_00589aec post-processing,
- `src/main.py` / `src/gui.py` — app shell with three top-level modes
  (Russian UI, English comments): «СКМ» measurement screen (INFO column,
  green ФОН / red СИГНАЛ+ФОН colour layers, navy spectrum canvas with
  the yellow cursor, TXT export, TONE playback toggle), the tone
  generator page, the analyzer stub; all device I/O in a QThread,
- `src/cli.py` — probe/speaker/sample/gen/measure CLI commands,
- `src/gui_smoke.py` — headless smoke test (modes → measure → export →
  TONE → PNG grabs),
- `SKM.spec` — PyInstaller build (Qt module/plugin pruning, numpy kept).

Evidence: the reverse-engineering base lives in the sibling `CKM2PO` project
repo — `analysis/meas/defns/FUN_*.c` (5858 decompiled bodies) and the "SKM
protocol total layer — extracted" section in `analysis/notes.md`.

## Simulated data stream (no hardware needed)

The byte stream behind the `'N'` measurement is generated synthetically by
`src/skm/simulator.py` so the whole pipeline — transport, capture, FFT,
GUI plots — runs against a known scene:

- scene = sine test tone (`tone_freq`, `tone_amp`) on a Gaussian noise floor
  (`noise_sigma`); the AWG'ish "world" lives entirely in the simulator;
- the `'H'` generator command retunes the scene (demo interpretation of the
  unresolved RE fields: `p2==0` = STOP silences the tone, otherwise the first
  divider word sets the tone as `stream_fs / div`, mirroring the guard
  encoding of `device.set_generator`). So in the GUI: ON (H) 5120 -> next
  capture peaks at 5120 Hz; STOP -> the tone disappears, noise floor remains;
- direct scene control for tests: `Simulator.set_scene(freq=…, amp=…, noise=…)`;
- `uv run python src/cli.py sweep` walks the scene 200…8000 Hz through the
  full protocol (`'H'` → `'N'`/`'S'` → FFT) and prints captured peaks;
- in the SKM mode the measurement loop streams continuously (0.5 s
  interval, module constant `STREAM_INTERVAL_S`), refreshing the column
  of the selected colour — the other colour's layer stays frozen for
  comparison, exactly like the original background→signal workflow.

## Modes shell

The window top is a flat mode bar; nothing sits above it:

- «СКМ» — original-like measurement screen (screenshot: `analysis`
  workflow — fill the green background layer, switch the colour, fill
  the red signal layer, then export both into a `*.txt` file via the
  original-style dialog `Текстовый файл|*.txt`). Sources: simulator
  (no hardware), test-data files (both spectra at once: noise → ФОН,
  signal_noise → СИГНАЛ+ФОН), or SKM-23 hardware over D2XX.
  TONE toggles the acoustic playback (in-process tone engine; the same
  button state is polled from the generator's player 3×/s).
- «ГЕНЕРАТОР ЧАСТОТ» — the full tone playback UI (below).
- «АНАЛИЗАТОР ЧАСТОТ» — stub for a future mode.

## Tone generator mode (integrated engine, full UI)

The tone mode hosts a faithful PySide6 rebuild of the
TonePlayer screen driven by the same in-process engine
(`audio_engine.TonePlayer` imported verbatim from ../tone-player/src —
no TonePlayer instance is started and commands act instantly):

- transport: First/Prev/Play/Pause/Stop/Next/Last and the autoplay toggle
  (autoplay advances bands every `seconds_per_tone`);
- big frequency readout, tone counter, remaining time and a tone progress
  bar, refreshed at 50 ms like the original;
- band strip like the original: a horizontal strip of narrow vertical
  band columns (each 66 px: dB value, vertical level slider, frequency,
  per-band Play button) beside a shared level ruler, inside a
  horizontally scrolled area with a wheel-driven scroll; master gain
  column outside the scroll on the left;
- band highlights and keyboard like the original: accent frame and
  light fill on the sounding band, focus ring on the focused slider,
  Left/Right move the slider focus (Right from master goes to the
  bands), Up/Down nudge the focused band by one step, Space
  play/pause, Enter activates the focused band; double click or the
  context menu resets a slider to 0 dB;
- band levels are runtime-only (exactly like TonePlayer — not
  persisted) edited with the slider or Up/Down;
- master gain slider (±10 dB from the −12 dB base), output-device selector
  (PortAudio list) and the preset selector — device/preset/autoplay/
  master choices persist into the same `settings.json` (shared with the
  TonePlayer app) via settings_store.save_settings (debounced 600 ms,
  flushed at app exit).

Engine sources location: `../tone-player/src` in dev (skipped for the
frozen bundle, where PyInstaller collects `audio_engine`, `models`,
`error`, `settings_store` and the bundled PortAudio library per
SKM.spec). Settings file: dev — `../tone-player/dist/settings.json`,
frozen SKM — next to the SKM executable ("same folder" deployment).
Overrides: `SKM_TONE_PLAYER_SRC` (engine sources), `SKM_TONE_SETTINGS`
(settings.json path).

## Precomputed-spectrum file input

A third connection kind, "Files (test data)", duplicates the input of the
signal-processor project: it loads its two ready-made spectra
(`noise.txt` = pure noise U_n, `signal_noise.txt` = signal + noise U_sn;
1 Hz grid, voltage level) and renders them through the same visualization
path as a device capture.

- Directory resolution: `SKM_TEST_DATA_DIR` env override, then the sibling
  repo layout (`../signal-processor/test_data`).
- Two display modes via the "File input mode" radio group: Noise (U_n) /
  Signal + noise (U_sn); switching re-renders instantly.
- Levels are shown as 20*log10(V) (dB re 1 V); the frequency axis widens to
  the full file span (32000 Hz); the oscillogram view is disabled since the
  files contain no time-domain data.

Quantization note: the divider is an integer, so e.g. "4000 Hz" produces
`51200/13 ≈ 3938 Hz` — a physically faithful artifact of the RE'd divider
scheme, not a bug.

## Build / run

```sh
uv sync && uv sync --group build   # runtime + build toolchain
uv run python src/cli.py probe     # CLI against the simulator
uv run python src/main.py          # GUI (needs display)
QT_QPA_PLATFORM=offscreen uv run python src/gui_smoke.py out.png   # headless test
uv run --group build pyinstaller SKM.spec   # single-file dist/SKM
SKM_ONEDIR=1 uv run --group build pyinstaller SKM.spec --noconfirm  # dist/SKM/ dir
```

Real SKM hardware: Windows + `ftd2xx.dll` in PATH, connect via "FTDI: CKM 23v1"
in the GUI (D2XX discovery by description, as FUN_00570b84 does).
```

```SKM.spec
# -*- mode: python ; coding: utf-8 -*-
"""Build script for SKM.

The app only needs Qt Widgets, so unused Qt modules and plugins are stripped
from the bundled distribution: Qt6Pdf, Qt6OpenGL, Qt6Multimedia, Qt6Qml and
the rest; platform plugins plus styles and input methods are kept. This is
the main source of size reduction.

Platform plugins are OS-dependent: on Windows they are windows, windowsv3,
minimal and offscreen; on Linux — xcb, wayland, minimal and offscreen.
Wayland is kept because in a Wayland session Qt selects it by default (often
via QT_QPA_PLATFORM), and without the plugin the app would not start.
The wayland plugin ships with shell integration (xdg-shell) and window
decorations: without them Qt cannot create an actual window.

numpy is NOT excluded (unlike the tone-player reference): the measurement
engine needs it at runtime for the 65536-point FFT.

For build debugging it is handy to temporarily switch EXE(...) to
exclude_binaries=True and add a COLLECT: that produces a _internal directory
where one can see what got bundled.
"""

import os
import sys
from pathlib import Path

from PyInstaller.building.datastruct import TOC

# SPECPATH — directory of the spec file, set by PyInstaller itself; the build
# does not depend on the launch working directory.
ROOT_DIR = Path(SPECPATH).resolve()
SRC_DIR = ROOT_DIR / "src"

IS_WINDOWS = sys.platform == "win32"
ONEDIR = os.environ.get("SKM_ONEDIR") == "1"

# Qt and Python modules the app does not need.
EXCLUDED_MODULES = [
    "tkinter",
    "unittest",
    # NOTE: pydoc is NOT excluded: pyqtgraph/parametertree/interactive.py
    # imports it, and pyqtgraph is eagerly imported at startup.
    "PIL",
    # NOTE: PySide6.QtOpenGL is NOT excluded: pyqtgraph imports it eagerly
    # (pyqtgraph/Qt/OpenGLHelpers.py via PlotCurveItem), so removing it
    # breaks startup of the bundled app.
    "PySide6.QtPrintSupport",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQuickWidgets",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtSql",
    "PySide6.QtTest",
    "PySide6.QtXml",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtDesigner",
    "PySide6.QtHelp",
    "PySide6.QtUiTools",
    "PySide6.QtWebChannel",
    "PySide6.QtWebSockets",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtBluetooth",
    "PySide6.QtPositioning",
    "PySide6.QtSensors",
    "PySide6.QtSerialPort",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
]

# Qt libraries required by the app.
# Qt6XcbQpa and Qt6WaylandClient are not separate modules but parts of the
# platform plugins: without the former libqxcb.so cannot load (it pulls in the
# system Qt of a different version), without the latter libqwayland.so cannot.
QT_LIB_PREFIXES = (
    "Qt6Core",
    "Qt6Gui",
    "Qt6Widgets",
    "Qt6DBus",
    "Qt6Network",
    "Qt6XcbQpa",
    "Qt6WaylandClient",
)

# Qt6Core is linked against ICU, which sits next to the Qt libraries.
QT_LIB_SUBSTRINGS = ("icu",)

# Platform plugins kept in the build (without lib/q prefixes).
PLATFORM_PLUGINS = {
    "windows": ("windows", "windowsv3", "minimal", "offscreen"),
    "linux": ("xcb", "wayland", "minimal", "offscreen"),
}

# Qt plugin directories kept entirely.
KEPT_PLUGIN_DIRS = ("styles", "platforminputcontexts", "imageformats")

# Wayland plugins: needed only on Linux and not wholesale.
# xdg-shell is the shell integration for regular desktops; bradient and
# adwaita are window titlebar renderers (in niri and other compositors
# without server-side decorations a window would otherwise have no frame),
# qt-plugin-wayland-egl is EGL rendering.
WAYLAND_PLUGIN_FILES = {
    "wayland-shell-integration": ("xdg-shell",),
    "wayland-decoration-client": ("bradient", "adwaita"),
}

# External libraries pulled in only by the removed Qt plugins.
# X11 libraries are needed by the xcb plugin, libwayland-* by the wayland
# plugin, so they are not touched.
EXCLUDED_LIB_SUBSTRINGS = (
    "libglycin",
    "libgtk-3",
    "libgdk-3",
)


def stem_of(filename: str) -> str:
    """File name without lib/q prefixes and without the extension."""
    stem = filename
    for prefix in ("lib", "q"):
        if stem.startswith(prefix):
            stem = stem[len(prefix):]
    return stem.split(".", 1)[0]


def wanted_plugin(path: str) -> bool:
    """Keep only required plugins: platform, wayland, styles and input."""
    normalized = path.replace("\\", "/")
    if "/plugins/" not in normalized:
        return True
    directory, _, filename = normalized.split("/plugins/", 1)[1].partition("/")
    if not filename:
        return True
    if directory == "platforms":
        allowed = PLATFORM_PLUGINS["windows" if IS_WINDOWS else "linux"]
        return stem_of(filename) in allowed
    if directory in KEPT_PLUGIN_DIRS:
        return True
    if IS_WINDOWS:
        return False
    return any(item in filename for item in WAYLAND_PLUGIN_FILES.get(directory, ()))


def wanted_binary(path: str) -> bool:
    """Drop extra Qt libraries and dependencies of unneeded plugins."""
    normalized = path.replace("\\", "/")
    if not wanted_plugin(normalized):
        return False

    filename = normalized.rsplit("/", 1)[-1]
    if "Qt6/lib/" in normalized:
        stem = stem_of(filename)
        return stem.startswith(QT_LIB_PREFIXES) or any(
            item in stem for item in QT_LIB_SUBSTRINGS
        )
    return not any(item in filename for item in EXCLUDED_LIB_SUBSTRINGS)


a = Analysis(
    [str(SRC_DIR / "main.py")],
    # tone-player/src holds the integrated TonePlayer audio engine
    # (top-level modules audio_engine, models, error, settings_store).
    pathex=[str(SRC_DIR), str(ROOT_DIR.parent / "tone-player" / "src")],
    binaries=[],
    datas=[],
    hiddenimports=[
        "skm",
        "skm.constants",
        "skm.transport",
        "skm.simulator",
        "skm.protocol",
        "skm.device",
        "skm.measurement",
        "gui",
        "cli",
        "numpy",
        # TonePlayer engine, imported in-process by skm.toneplayer.
        "audio_engine",
        "models",
        "error",
        "settings_store",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDED_MODULES,
    noarchive=False,
)

# The in-process TonePlayer engine uses sounddevice/PortAudio: pull in the
# bundled portaudio library (sounddevice ships it in _sounddevice_data).
from PyInstaller.utils.hooks import collect_dynamic_libs  # noqa: E402

_portaudio = collect_dynamic_libs("sounddevice")

dropped = len(a.binaries)
a.binaries = TOC(
    [entry for entry in a.binaries + _portaudio if wanted_binary(str(entry[0]))]
)
print(f"Dropped files: {dropped - len(a.binaries)} of {dropped}")

pyz = PYZ(a.pure)

EXE_OPTIONS = {
    "name": "SKM",
    "debug": False,
    "bootloader_ignore_signals": False,
    "strip": not IS_WINDOWS,
    # UPX disabled: compressing Qt DLLs breaks their loading and increases
    # false-positive antivirus detections; besides, windows-latest runners
    # have no UPX installed.
    "upx": False,
    "upx_exclude": [],
    "runtime_tmpdir": None,
    "console": False,
    "disable_windowed_traceback": False,
    "argv_emulation": False,
    "target_arch": None,
    "codesign_identity": None,
    "entitlements_file": None,
}

if ONEDIR:
    exe = EXE(pyz, a.scripts, exclude_binaries=True, **EXE_OPTIONS)
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=not IS_WINDOWS,
        upx=False,
        upx_exclude=[],
        name="SKM",
    )
else:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], **EXE_OPTIONS)
```

```pyproject.toml
[project]
name = "skm"
version = "0.1.0"
description = "SKM-2PO measurement/communication mechanism: protocol core + measurement GUI (standalone)"
requires-python = "==3.14.9"
dependencies = [
    "numpy==2.5.4",
    "pyqtgraph==0.14.0",
    "pyside6==6.12.0",
    "sounddevice==0.5.6",  # TonePlayer engine (in-process), same pin as tone-player
]

[dependency-groups]
dev = ["ruff==0.17.1"]
build = ["pyinstaller==6.22.3"]

[tool.uv]
package = false

[tool.ruff]
line-length = 100
target-version = "py314"

[tool.ruff.lint]
select = ["E", "W", "F", "I", "UP", "S", "B", "N"]

[tool.ruff.lint.per-file-ignores]
"src/**" = ["N802"]

[tool.ruff.lint.pep8-naming]
# CamelCase override names, required by Qt (Qt event overrides).
ignore-names = [
    "paintEvent",
    "mouseReleaseEvent",
    "mousePressEvent",
    "mouseDoubleClickEvent",
    "contextMenuEvent",
    "enterEvent",
    "leaveEvent",
    "wheelEvent",
    "keyPressEvent",
    "closeEvent",
    "setUp",
    "setUpClass",
    "focusInEvent",
    "focusOutEvent",
]
```

```src/cli.py
"""CLI for the skm link core.

  python3 -m skmapp.cli probe        # discovery + handshake + status
  python3 -m skmapp.cli speaker on|off
  python3 -m skmapp.cli sample       # 'J' 12-bit probe reads
  python3 -m skmapp.cli gen 1000     # 'H' generator demo (retunes the scene)
  python3 -m skmapp.cli measure      # capture + spectrum, print bands
  python3 -m skmapp.cli sweep        # retune generator + capture across a
                                     # frequency ladder, then STOP -> noise
"""
from __future__ import annotations

import sys

import numpy as np

from skm import PairTransport, Simulator, SkmDevice


def open_sim() -> SkmDevice:
    sim = Simulator()
    dev = SkmDevice(PairTransport(sim))
    dev.open()
    return dev


def cmd_probe(dev: SkmDevice) -> int:
    ok = dev.handshake()
    print(f"handshake 'A': {'OK' if ok else 'NO REPLY'}")
    print(f"status 'Q': {dev.query_status()}")
    print(f"freq 'F': {dev.read_freq()}")
    print(f"sample 'J': {dev.read_sample()}")
    print(f"speaker 'V/U' toggle: on={dev.set_speaker(True)} "
          f"q={dev.query_status()} off={dev.set_speaker(False)} "
          f"q={dev.query_status()}")
    return 0


def cmd_speaker(dev: SkmDevice, on: bool) -> int:
    print("OK" if dev.set_speaker(on) else "NO REPLY")
    return 0


def cmd_sample(dev: SkmDevice) -> int:
    for _ in range(5):
        print("J =", dev.read_sample())
    return 0


def cmd_gen(dev: SkmDevice, freq: int) -> int:
    # div approximation: stream_fs/frequency guard-wrapped (RE: FUN_0058aadc)
    div = max(1, round(Simulator.stream_fs / freq))
    ok = dev.set_generator(p2=1, p1=2, div=div, p7=3, p6=4, p5=5, div2=div)
    actual = Simulator.stream_fs / div
    print(f"H frame sent ({'ok' if ok else 'no reply'}), div={div}, "
          f"scene tone now {actual:.1f} Hz")
    return 0


def cmd_measure(dev: SkmDevice, fs: float) -> int:
    sp = dev.meas.spectrum(fs=fs)
    print(f"captured 65536 samples, bin={sp.freqs[1]:.2f} Hz")
    print(f"peak: {sp.freqs[int(np.argmax(sp.lin))]:.1f} Hz "
          f"@ {sp.db.max():.1f} dB")
    for f in (100, 500, 1000, 2000, 5000, 10000):
        print(f"  band {f:6d} Hz: {sp.band_db(f):7.1f} dB")
    return 0


def cmd_sweep(dev: SkmDevice, fs: float) -> int:
    """Demo the full pipeline: retune the generator, capture, report peak."""
    dev.handshake()
    for freq in (200, 500, 1000, 2000, 4000, 8000):
        div = max(1, round(fs / freq))
        dev.set_generator(p2=1, p1=2, div=div, p7=3, p6=4, p5=5, div2=div)
        sp = dev.meas.spectrum(fs=fs)
        peak = float(sp.freqs[int(np.argmax(sp.lin))])
        print(f"gen {freq:5d} Hz -> captured peak {peak:8.1f} Hz "
              f"@ {sp.db.max():6.1f} dB")
    dev.set_generator(p2=0, p1=0, div=1, p7=0, p6=0, p5=0, div2=1)
    sp = dev.meas.spectrum(fs=fs)
    print(f"gen STOP         -> captured peak {sp.db.max():6.1f} dB (noise)"
          f" at {float(sp.freqs[int(np.argmax(sp.lin))]):8.1f} Hz")
    return 0


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    cmd = argv[0]
    dev = open_sim()
    try:
        if cmd == "probe":
            return cmd_probe(dev)
        if cmd == "speaker" and len(argv) > 1:
            return cmd_speaker(dev, argv[1] == "on")
        if cmd == "sample":
            return cmd_sample(dev)
        if cmd == "gen" and len(argv) > 1:
            return cmd_gen(dev, int(argv[1]))
        if cmd == "measure":
            return cmd_measure(dev, fs=51200.0)
        if cmd == "sweep":
            return cmd_sweep(dev, fs=51200.0)
        print(f"unknown command {cmd!r}", file=sys.stderr)
        return 2
    finally:
        dev.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
```

```src/gui.py
"""Standalone SKM app shell: three top-level modes (PySide6 + pyqtgraph).

Top of the window is a mode bar with three flat buttons above which
nothing else exists — switching a mode replaces the whole interface
(visible mode captions are the Russian product wording):

  - "SKM" — measurement screen that mirrors the original SKM-2 PO (TMF):
    INFO column (frequency / level readouts), measurement colour switch
    (green FON = background, red SIGNAL+FON = signal over background),
    dark-navy spectrum canvas with the yellow peak cursor, export of
    both measured layers into a text file, and the TONE button that
    toggles the in-process tone playback ("acoustic system playback").
    Sources: in-process simulator (same RE'd protocol), FTDI D2XX
    hardware, or the precomputed-spectrum file pair.
  - "Tone generator" — the full TonePlayer panel on the integrated
    engine (see skm.tp_panel).
  - "Frequency analyzer" — plain stub for a future mode.

Threading: all device I/O happens in a LinkThread worker; the UI thread
never touches the transport (the RE'd layer is synchronous and
poll-heavy). Results arrive as numpy arrays via signals, so only
values referenced from the arrival signal are read from other threads.

UI wording is Russian (product language); code comments stay English.
Run:  uv run python src/main.py
"""
from __future__ import annotations

import os
from datetime import datetime

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QThread, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from skm import D2XXTransport, PairTransport, Simulator, SkmDevice, Spectrum, toneplayer
from skm.spectra import SpectrumFile
from skm.tp_panel import TonePlayerPanel

FMIN, FMAX = 10.0, 20000.0          # SKM spectrum span (DFM band panel)
FILE_FMAX = 32000.0                 # test-data files span up to 32000 Hz
DEFAULT_FS = 51200.0                # simulator stream fs; for HW settable
DB_FLOOR = 1e-6                     # V floor for 20*log10 of file spectra
STREAM_INTERVAL_S = 0.5             # continuous measure period (device modes)

# Palette — light blue-grey chrome like the original SKM-2 PO UI.
COL_WINDOW = "#eef1f6"
COL_MODEBAR = "#dfe7f2"
COL_PANEL = "#f7f9fc"
COL_PANEL_BORDER = "#b9c6d6"
COL_CANVAS = "#3a3f5e"
COL_CANVAS_AXIS = "#aeb6d6"
COL_CANVAS_GRID = "#535a85"
COL_TEXT_VALUE = "#1f4d8f"
COL_FON = "#22c55e"                 # green background layer
COL_SIGNAL = "#ef4444"              # red signal layer
COL_CURSOR = "#f2c94c"              # yellow vertical peak cursor

QSS = f"""
QMainWindow, QWidget#pageSkm, QWidget#pageStub {{
    background: {COL_WINDOW};
}}
QWidget#modeBar {{
    background: {COL_MODEBAR};
    border-bottom: 1px solid {COL_PANEL_BORDER};
}}
QPushButton#modeButton {{
    background: transparent; border: none; padding: 12px 24px 9px 24px;
    font-weight: 600; font-size: 13px; color: #33415c;
}}
QPushButton#modeButton:checked {{
    background: {COL_PANEL}; color: {COL_TEXT_VALUE};
    border-top: 3px solid #3d7ecc;
}}
QWidget#toolbar {{
    background: #e4ebf4; border-bottom: 1px solid {COL_PANEL_BORDER};
}}
QWidget#toolbar QPushButton {{
    background: {COL_PANEL}; border: 1px solid {COL_PANEL_BORDER};
    border-radius: 4px; padding: 6px 14px; color: #22314f;
}}
QWidget#toolbar QPushButton:hover {{ background: #e9f0f8; }}
QPushButton#btnTone {{
    background: #fbfdff; border: 1px solid #9fb0c2;
    padding: 6px 26px; font-weight: 800; color: #22314f;
}}
QPushButton#btnTone:checked {{
    background: #3d7ecc; color: #ffffff; border-color: #3d7ecc;
}}
QLabel#lblDevices {{
    color: #5a6675; font-weight: 700; padding: 4px 12px;
    border: 1px solid {COL_PANEL_BORDER}; border-radius: 4px;
    background: #dbe2ec;
}}
QWidget#leftPanel {{
    background: {COL_PANEL}; border: 1px solid {COL_PANEL_BORDER};
    border-radius: 6px;
}}
QLabel#infoTitle {{
    color: #33415c; font-weight: 800; font-size: 13px; letter-spacing: 1px;
}}
QLabel#infoCaption {{ color: #77838f; font-size: 11px; }}
QLabel#infoValue {{
    color: {COL_TEXT_VALUE}; font-size: 17px; font-weight: 800;
}}
QPushButton#colorButton {{
    background: {COL_PANEL}; border: 1px solid {COL_PANEL_BORDER};
    border-radius: 4px; padding: 8px 0; font-size: 15px;
}}
QPushButton#colorButton[sel="1"] {{
    border: 2px solid #3d7ecc; background: #eaf2fc;
}}
QWidget#pageStub QLabel {{ color: #77838f; }}
"""


def _rd(value, digits: int = 1) -> str:
    """Russian decimal-comma formatting with thin-space thousands."""
    return f"{value:,.{digits}f}".replace(",", " ").replace(".", ",")


# --------------------------------------------------------------- worker

class MeasurementResult:
    __slots__ = ("spec", "pairs", "ok", "err")

    def __init__(self, spec: Spectrum | None = None,
                 pairs: dict[str, Spectrum] | None = None,
                 ok: bool = True, err: str = "") -> None:
        self.spec = spec        # Spectrum of one device capture
        self.pairs = pairs      # file mode: both stored spectra at once
        self.ok = ok
        self.err = err


class LinkThread(QThread):
    """Owns the device (or the loaded file spectra); executes commands
    posted by the UI and runs the continuous measure loop."""

    state_changed = Signal(str)
    result_ready = Signal(object)          # MeasurementResult
    connection_changed = Signal(str)       # "" | "sim" | "d2xx" | "files"

    def __init__(self) -> None:
        super().__init__()
        self.dev: SkmDevice | None = None
        self.files: dict[str, SpectrumFile] | None = None
        self._queue: list[tuple[str, object]] = []
        self.streaming = False
        self.oneshot = False
        self.interval_s = STREAM_INTERVAL_S
        self.fs = DEFAULT_FS

    # called from the UI thread ----------------------------------------
    def submit(self, name: str, fn) -> None:
        self._queue.append(("cmd", (name, fn)))

    def connect_simulator(self) -> None:
        self._queue.append(("connect", ("sim", "")))

    def connect_d2xx(self, description: str = "CKM 23v1") -> None:
        self._queue.append(("connect", ("d2xx", description)))

    def connect_files(self) -> None:
        self._queue.append(("connect_files", None))

    def disconnect(self) -> None:
        self.streaming = False
        self._queue.append(("disconnect", None))

    def request_measure(self) -> None:
        self.oneshot = True

    def stop(self) -> None:
        self.streaming = False
        self._queue.append(("quit", None))

    # worker side --------------------------------------------------------
    def run(self) -> None:
        import time
        next_t = 0.0
        running = True
        while running:
            while self._queue:
                kind, arg = self._queue.pop(0)
                try:
                    if kind == "quit":
                        running = False
                        self._disconnect()
                    elif kind == "connect":
                        self._connect(arg)
                    elif kind == "connect_files":
                        self._connect_files()
                    elif kind == "disconnect":
                        self._disconnect()
                    elif kind == "cmd" and self.dev is not None:
                        arg[1](self.dev)
                except Exception as exc:                    # noqa: BLE001
                    self.state_changed.emit(f"Ошибка: {exc}")
            if self._input_ready() and (self.streaming or self.oneshot):
                now = time.monotonic()
                if self.oneshot or (self.streaming and now >= next_t):
                    self.oneshot = False
                    self._do_measure()
                    next_t = now + self.interval_s
            time.sleep(0.02)

    def _input_ready(self) -> bool:
        return self.dev is not None or self.files is not None

    def _connect(self, desc) -> None:
        self._disconnect()
        if desc[0] == "sim":
            transport = PairTransport(Simulator())
        else:
            transport = D2XXTransport(description=desc[1])
        dev = SkmDevice(transport)
        dev.open()
        if not dev.handshake():
            transport.close()
            self.dev = None
            self.state_changed.emit("УСТРОЙСТВА ОТКЛЮЧЕНЫ")
            self.connection_changed.emit("")
            return
        self.dev = dev
        self.state_changed.emit("УСТРОЙСТВА ПОДКЛЮЧЕНЫ")
        self.connection_changed.emit(desc[0])

    def _connect_files(self) -> None:
        self._close_device()
        try:
            self.files = {kind: SpectrumFile.load(kind) for kind in
                          ("noise", "signal_noise")}
        except Exception as exc:                        # noqa: BLE001
            self.files = None
            self.state_changed.emit(f"Ошибка: {exc}")
            self.connection_changed.emit("")
            return
        self.state_changed.emit("УСТРОЙСТВА ПОДКЛЮЧЕНЫ")
        self.oneshot = True
        self.connection_changed.emit("files")

    def _close_device(self) -> None:
        if self.dev is not None:
            try:
                self.dev.close()
            except Exception:                           # noqa: S110
                pass                                    # best effort close
        self.dev = None

    def _disconnect(self) -> None:
        self._close_device()
        self.files = None
        self.state_changed.emit("УСТРОЙСТВА ОТКЛЮЧЕНЫ")
        self.connection_changed.emit("")

    def _do_measure(self) -> None:
        """One measurement: file mode publishes both stored spectra,
        device modes capture a fresh spectrum from the stream."""
        try:
            if self.files is not None:
                pairs = {kind: self._file_spectrum(sf)
                         for kind, sf in self.files.items()}
                self.result_ready.emit(MeasurementResult(pairs=pairs))
                return
            dev = self.dev
            if dev is None:
                raise RuntimeError("нет подключения")
            self.result_ready.emit(
                MeasurementResult(spec=dev.meas.spectrum(fs=self.fs)))
        except Exception as exc:                        # noqa: BLE001
            self.result_ready.emit(MeasurementResult(ok=False, err=str(exc)))

    @staticmethod
    def _file_spectrum(sf: SpectrumFile) -> Spectrum:
        """Wrap a precomputed spectrum into the Spectrum shape."""
        volts = np.asarray(sf.volts)
        db = 20.0 * np.log10(np.maximum(volts, DB_FLOOR))
        return Spectrum(freqs=np.asarray(sf.freqs_hz), lin=volts, db=db)


# ------------------------------------------------------------------- UI

class MainWindow(QMainWindow):
    """App shell: mode bar + stacked pages."""

    MODE_SKM = 0
    MODE_TONE = 1
    MODE_ANALYZER = 2

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("СКМ-2 ПО")
        self.resize(1220, 800)
        self._fmax = FMAX          # widened in file mode (files go to 32000)
        self._conn_kind = ""       # "" | "sim" | "d2xx" | "files"
        self._selected = "fon"     # colour being measured (live layer)

        self.thread = LinkThread()
        self.thread.state_changed.connect(self.on_state)
        self.thread.result_ready.connect(self.on_result)
        self.thread.connection_changed.connect(self.on_connection)

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # --- mode bar (topmost element, above everything) ---------------
        mode_bar = QWidget(objectName="modeBar")
        mode_bar.setObjectName("modeBar")
        bar_l = QHBoxLayout(mode_bar)
        bar_l.setContentsMargins(8, 0, 12, 0)
        bar_l.setSpacing(4)
        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)
        for page, caption in enumerate(
                ("СКМ", "ГЕНЕРАТОР ЧАСТОТ", "АНАЛИЗАТОР ЧАСТОТ")):
            btn = QPushButton(caption)
            btn.setObjectName("modeButton")
            btn.setCheckable(True)
            btn.setChecked(page == self.MODE_SKM)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self._mode_group.addButton(btn, page)
            btn.toggled.connect(
                lambda on, p=page: self._on_mode(p) if on else None)
            bar_l.addWidget(btn)
        bar_l.addStretch(1)
        root.addWidget(mode_bar)

        # --- stacked pages ----------------------------------------------
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_skm_page())
        self.tp_panel = TonePlayerPanel()
        self.stack.addWidget(self.tp_panel)
        self.stack.addWidget(self._build_stub_page())
        self.stack.setCurrentIndex(self.MODE_SKM)
        root.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self.thread.start()

        # keep the TONE toggle in sync with the player state
        self._tone_timer = QTimer(self)
        self._tone_timer.setInterval(300)
        self._tone_timer.timeout.connect(self._sync_tone)
        self._tone_timer.start()

    # ----------------------------------------------------- SKM page
    def _build_skm_page(self) -> QWidget:
        page = QWidget(objectName="pageSkm")
        page.setObjectName("pageSkm")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # toolbar: source selector + connect/disconnect | TONE | devices
        toolbar = QWidget(objectName="toolbar")
        toolbar.setObjectName("toolbar")
        tl = QHBoxLayout(toolbar)
        tl.setContentsMargins(10, 6, 10, 6)
        tl.setSpacing(6)
        self.cb_conn = QComboBox()
        self.cb_conn.addItems(
            ["СИМУЛЯТОР СКМ-23", "ФАЙЛЫ (ТЕСТ-ДАННЫЕ)", "СКМ-23 (D2XX)"])
        self.cb_conn.setMinimumWidth(190)
        tl.addWidget(self.cb_conn)
        self.btn_conn = QPushButton("ПОДКЛЮЧИТЬ")
        self.btn_conn.clicked.connect(self.on_connect)
        tl.addWidget(self.btn_conn)
        self.btn_disc = QPushButton("ОТКЛЮЧИТЬ")
        self.btn_disc.clicked.connect(self.thread.disconnect)
        tl.addWidget(self.btn_disc)
        self.btn_exp = QPushButton("ЭКСПОРТ ИЗМЕРЕНИЙ")
        self.btn_exp.clicked.connect(self.export_txt)
        tl.addWidget(self.btn_exp)
        tl.addStretch(1)
        self.btn_tone = QPushButton("TONE")
        self.btn_tone.setObjectName("btnTone")
        self.btn_tone.setCheckable(True)
        self.btn_tone.setToolTip("Воспроизведение акустической системы "
                                 "(запуск генератора частот)")
        self.btn_tone.toggled.connect(self._on_tone_toggled)
        tl.addWidget(self.btn_tone)
        self.lbl_devices = QLabel("УСТРОЙСТВА ОТКЛЮЧЕНЫ")
        self.lbl_devices.setObjectName("lblDevices")
        tl.addWidget(self.lbl_devices)
        lay.addWidget(toolbar)

        body = QHBoxLayout()
        body.setContentsMargins(8, 8, 8, 8)
        body.setSpacing(8)

        # left INFO / MEASUREMENT column, like the original TMF
        left_w = QWidget(objectName="leftPanel")
        left_w.setObjectName("leftPanel")
        left_w.setFixedWidth(186)
        left = QVBoxLayout(left_w)
        left.setContentsMargins(12, 12, 12, 12)
        left.setSpacing(4)

        title_info = QLabel("ИНФОРМАЦИЯ")
        title_info.setObjectName("infoTitle")
        left.addWidget(title_info)
        cap_freq = QLabel("ЧАСТОТА")
        cap_freq.setObjectName("infoCaption")
        left.addWidget(cap_freq)
        self.lb_freq = QLabel("—")
        self.lb_freq.setObjectName("infoValue")
        left.addWidget(self.lb_freq)
        cap_level = QLabel("УРОВЕНЬ")
        cap_level.setObjectName("infoCaption")
        left.addWidget(cap_level)
        self.lb_level = QLabel("—")
        self.lb_level.setObjectName("infoValue")
        left.addWidget(self.lb_level)
        left.addSpacing(20)

        title_meas = QLabel("ИЗМЕРЕНИЯ")
        title_meas.setObjectName("infoTitle")
        left.addWidget(title_meas)
        cap_color = QLabel("УКАЖИТЕ ЦВЕТ\nСПЕКТРОГРАММЫ")
        cap_color.setObjectName("infoCaption")
        left.addWidget(cap_color)
        color_row = QHBoxLayout()
        color_row.setSpacing(6)
        self.btn_fon = QPushButton("●")
        self.btn_fon.setObjectName("colorButton")
        self.btn_fon.setCheckable(True)
        self.btn_fon.setChecked(True)
        self.btn_fon.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_fon.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_fon.setToolTip("Замер фона (зелёная кривая)")
        self.btn_fon.setStyleSheet(
            f"QPushButton#colorButton {{ color: {COL_FON}; }}")
        self.btn_signal = QPushButton("●")
        self.btn_signal.setObjectName("colorButton")
        self.btn_signal.setCheckable(True)
        self.btn_signal.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_signal.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_signal.setToolTip("Замер сигнала + фона (красная кривая)")
        self.btn_signal.setStyleSheet(
            f"QPushButton#colorButton {{ color: {COL_SIGNAL}; }}")
        color_row.addWidget(self.btn_fon)
        color_row.addWidget(self.btn_signal)
        left.addLayout(color_row)
        self.btn_fon.toggled.connect(
            lambda on: self._on_color("fon") if on else None)
        self.btn_signal.toggled.connect(
            lambda on: self._on_color("signal") if on else None)

        left.addSpacing(20)
        self.btn_measure = QPushButton("ИЗМЕРИТЬ")
        self.btn_measure.clicked.connect(self.thread.request_measure)
        left.addWidget(self.btn_measure)
        left.addStretch(1)
        body.addWidget(left_w)

        # canvas: dark navy spectrum with the yellow peak cursor
        self.pw_spec = pg.PlotWidget(background=COL_CANVAS)
        self.pl_spec = self.pw_spec.getPlotItem()
        self.pl_spec.setLabel("bottom", "Частота, Гц",
                              color=COL_CANVAS_AXIS)
        self.pl_spec.setLabel("left", "Уровень, дБ",
                              color=COL_CANVAS_AXIS)
        for axis in ("bottom", "left"):
            ai = self.pl_spec.getAxis(axis)
            ai.setTextPen(pg.mkPen(COL_CANVAS_AXIS))
            ai.setPen(pg.mkPen(COL_CANVAS_GRID))
        self.pl_spec.showGrid(x=True, alpha=0.25)
        self._apply_canvas_range()
        self.curve_fon = self.pw_spec.plot(
            pen=pg.mkPen(color=COL_FON, width=2))
        self.curve_signal = self.pw_spec.plot(
            pen=pg.mkPen(color=COL_SIGNAL, width=2))
        cursor = pg.InfiniteLine(
            angle=90, movable=False, pen=pg.mkPen(color=COL_CURSOR, width=2))
        cursor.setVisible(False)
        self.cursor_line = cursor
        self.pl_spec.addItem(cursor)
        self.layers: dict[str, dict[str, float]] = {
            "fon": {"freq": None, "level": None},
            "signal": {"freq": None, "level": None},
        }
        body.addWidget(self.pw_spec, 1)
        lay.addLayout(body, 1)
        return page

    def _build_stub_page(self) -> QWidget:
        page = QWidget(objectName="pageStub")
        page.setObjectName("pageStub")
        lay = QVBoxLayout(page)
        lay.addStretch(1)
        title = QLabel("АНАЛИЗАТОР ЧАСТОТ")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub = QLabel("Режим будет реализован позже.")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(title)
        lay.addWidget(sub)
        lay.addStretch(1)
        return page

    # ------------------------------------------------------- events/slots
    @Slot(int)
    def _on_mode(self, page: int) -> None:
        self.stack.setCurrentIndex(page)
        # stream only while the SKM page is visible and devices are live
        self.thread.streaming = (page == self.MODE_SKM
                                 and self._conn_kind in ("sim", "d2xx"))

    def _apply_canvas_range(self) -> None:
        self.pl_spec.setXRange(FMIN, self._fmax, padding=0)

    @Slot(str)
    def on_state(self, txt: str) -> None:
        self.lbl_devices.setText(txt)

    @Slot(str)
    def on_connection(self, kind: str) -> None:
        """kind: "" | "sim" | "d2xx" | "files"."""
        self._conn_kind = kind
        self._fmax = FILE_FMAX if kind == "files" else FMAX
        self._apply_canvas_range()
        self.stack.setCurrentIndex(self.MODE_SKM)
        if self._mode_group.button(self.MODE_SKM) is not None:
            btn = self._mode_group.button(self.MODE_SKM)
            btn.setChecked(True)      # a connection shows the SKM page
        self.thread.streaming = kind in ("sim", "d2xx")

    @Slot(object)
    def on_result(self, res) -> None:
        if not res.ok:
            self.statusBar().showMessage(f"Ошибка измерения: {res.err}",
                                         4000)
            return
        if res.pairs is not None:               # file mode: both layers
            self._store_layer("fon", res.pairs.get("noise"))
            self._store_layer("signal", res.pairs.get("signal_noise"))
        elif res.spec is not None:
            self._store_layer(self._selected, res.spec)
        self._refresh_info()
        self.statusBar().showMessage("", 10)

    def _store_layer(self, key: str, spec) -> None:
        if spec is None:
            return
        x, y = spec.freqs, spec.db
        mask = (x >= FMIN) & (x <= self._fmax)
        xm, ym = x[mask], y[mask]
        if not xm.size:
            return
        i = int(np.argmax(ym))
        layer = self.layers[key]
        layer["freq"] = float(xm[i])
        layer["level"] = float(ym[i])
        curve = self.curve_fon if key == "fon" else self.curve_signal
        curve.setData(xm, ym)
        self._apply_canvas_range()      # keep the fixed span (no autorange)

    def _on_color(self, key: str) -> None:
        if self._selected == key:
            return
        self._selected = key
        self.btn_fon.blockSignals(True)
        self.btn_signal.blockSignals(True)
        self.btn_fon.setProperty("sel", key == "fon")
        self.btn_signal.setProperty("sel", key == "signal")
        style = self.btn_fon.style()
        if style is not None:
            style.unpolish(self.btn_fon)
            style.polish(self.btn_fon)
        style = self.btn_signal.style()
        if style is not None:
            style.unpolish(self.btn_signal)
            style.polish(self.btn_signal)
        self.btn_fon.blockSignals(False)
        self.btn_signal.blockSignals(False)
        self._refresh_info()

    def _refresh_info(self) -> None:
        layer = self.layers[self._selected]
        if layer["freq"] is None:
            self.lb_freq.setText("—")
            self.lb_level.setText("—")
            self.cursor_line.setVisible(False)
            return
        self.lb_freq.setText(f"{_rd(layer['freq'], 1)} Гц")
        self.lb_level.setText(f"{_rd(layer['level'], 1)} дБ")
        self.cursor_line.setPos(layer["freq"])
        self.cursor_line.setVisible(True)

    def on_connect(self) -> None:
        match self.cb_conn.currentIndex():
            case 0:
                self.thread.connect_simulator()
            case 1:
                self.thread.connect_files()
            case 2:
                self.thread.connect_d2xx()

    # ------------------------------------------------------------- tone
    @Slot()
    def _sync_tone(self) -> None:
        """Keep the TONE toggle matching the player state (no signals)."""
        self.btn_tone.blockSignals(True)
        playing = False
        try:
            eng = toneplayer.engine()
            playing = eng.player.state.name.lower() in ("playing", "paused")
        except Exception:                           # noqa: BLE001
            self.btn_tone.setEnabled(False)
            self.btn_tone.setChecked(False)
            self.btn_tone.blockSignals(False)
            return
        self.btn_tone.setEnabled(True)
        self.btn_tone.setChecked(playing)
        self.btn_tone.blockSignals(False)

    def _on_tone_toggled(self, on: bool) -> None:
        try:
            eng = toneplayer.engine()
        except Exception as exc:                    # noqa: BLE001
            self.btn_tone.setChecked(False)
            self.statusBar().showMessage(
                f"Генератор недоступен: {exc}", 6000)
            return
        state = eng.player.state.name.lower()
        try:
            if on and state == "idle":
                eng.player.start(0)                 # the first band
            elif not on and state != "idle":
                eng.player.stop()
        except Exception as exc:                    # noqa: BLE001
            self.statusBar().showMessage(str(exc), 6000)
        self._sync_tone()

    # ------------------------------------------------------------ export
    def write_export(self, path: str) -> str:
        """Save both measured layers into a text file (original dialog)."""
        now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        source = self.cb_conn.currentText()
        parts = ["СКМ-2 ПО — результаты измерений",
                 f"Дата: {now}",
                 f"Источник: {source}",
                 ""]
        labels = {"fon": "ФОН (зелёная кривая)",
                  "signal": "СИГНАЛ+ФОН (красная кривая)"}
        written = 0
        for key, label in labels.items():
            layer = self.layers[key]
            if layer["freq"] is None:
                continue
            x, y = self._series(key)
            parts.append(f"[{label}]")
            parts.append(f"Пик: {_rd(layer['freq'], 1)} Гц; "
                         f"уровень: {_rd(layer['level'], 1)} дБ")
            parts.append("ЧАСТОТА, Гц;УРОВЕНЬ, дБ")
            rows = "\n".join(f"{_rd(a, 1)};{_rd(b, 1)}"
                             for a, b in zip(x, y, strict=True))
            parts.append(rows)
            parts.append("")
            written += 1
        if written == 0:
            return "нет данных"
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(parts))
        return "saved"

    def _series(self, key: str):
        curve = self.curve_fon if key == "fon" else self.curve_signal
        data = curve.getData()
        if data is None or len(data) != 2 or data[0] is None:
            return (), ()
        x, y = data
        return x, y

    def export_txt(self) -> None:
        default = self._export_default_name()
        path, _ = QFileDialog.getSaveFileName(
            self, "СОХРАНИТЬ ФАЙЛ КАК ...", default,
            "Текстовый файл|*.txt")
        if not path:
            return
        res = self.write_export(path)
        if res == "saved":
            self.statusBar().showMessage(f"Сохранено: {path}", 5000)
        else:
            self.statusBar().showMessage("Нет измерений для экспорта", 4000)

    def _export_default_name(self) -> str:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return os.path.join(os.path.expanduser("~"), f"skm_meas_{stamp}.txt")

    # -------------------------------------------------------------- close
    def closeEvent(self, ev) -> None:                       # noqa: N802
        self.thread.stop()
        self.thread.wait(2000)
        self.tp_panel.flush_save()      # persist TonePlayer edits
        toneplayer.shutdown()           # stop the in-process audio stream
        super().closeEvent(ev)


def main() -> int:
    app = QApplication([])
    app.setStyle("Fusion")
    app.setStyleSheet(QSS)
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
```

```src/gui_smoke.py
"""Headless smoke test for the GUI.

Exercises the mode shell, the SKM page (simulator measurement, colour
layers, export, TONE toggle), the tone generator page and the stub
page, grabbing PNGs along the way.
Run:  uv run python src/gui_smoke.py out.png
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

from PySide6.QtWidgets import QApplication

from gui import QSS, MainWindow
from skm import toneplayer


def _wait_until(app: QApplication, fn, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.02)
        if fn():
            return True
    return False


def _settle(app: QApplication, seconds: float = 0.4) -> None:
    """Pump the event loop so timers (refresh/pollers) catch up."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.02)


def main() -> int:
    out = sys.argv[1] if len(sys.argv) > 1 else \
        f"{tempfile.gettempdir()}/skm_gui.png"
    # TonePlayer settings copy: smoke must not touch the real dist file
    tp_dir = Path(tempfile.mkdtemp(prefix="skm_tp_"))
    shutil.copy(toneplayer.settings_path(), tp_dir / "settings.json")
    os.environ["SKM_TONE_SETTINGS"] = str(tp_dir / "settings.json")
    app = QApplication([])
    app.setStyleSheet(QSS)
    win = MainWindow()
    win.show()
    win.resize(1180, 760)
    end = time.monotonic() + 0.5
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.02)

    # 1) SKM page: simulator connect + continuous measurement
    if win.stack.currentIndex() != MainWindow.MODE_SKM:
        print("FAIL: SKM mode is not the first page", file=sys.stderr)
        return 1
    win.on_connect()                      # combo index 0 = СИМУЛЯТОР
    if not _wait_until(app, lambda: win.layers["fon"]["freq"] is not None,
                       10.0):
        print("FAIL: background layer not measured", file=sys.stderr)
        return 1
    print("SKM info фон:", win.lb_freq.text(), win.lb_level.text())

    # 2) switch the colour to red: the next measurements fill the signal layer
    win.btn_signal.click()
    if not _wait_until(app, lambda: win.layers["signal"]["freq"] is not None,
                       10.0):
        print("FAIL: signal layer not measured", file=sys.stderr)
        return 1
    print("SKM info сигнал:", win.lb_freq.text(), win.lb_level.text())
    _settle(app)
    png = out.replace(".png", "_skm.png")
    win.grab().save(png)
    print("saved", png)

    # 3) export both layers to a text file (without the dialog)
    export_path = os.path.join(tempfile.gettempdir(), "skm_warning_export.txt")
    if win.write_export(export_path) != "saved":
        print("FAIL: export reported no data", file=sys.stderr)
        return 1
    txt = Path(export_path).read_text(encoding="utf-8")
    for marker in ("ФОН", "СИГНАЛ+ФОН"):
        if marker not in txt:
            print(f"FAIL: export missing {marker}", file=sys.stderr)
            return 1
    print("export ok:", export_path)

    # 4) TONE button: start/stop the acoustic playback from the SKM page
    win.btn_tone.click()
    if not _wait_until(app, lambda: win.btn_tone.isChecked(), 8.0):
        print("FAIL: TONE did not start the playback", file=sys.stderr)
        return 1
    print("TONE on, engine:", toneplayer.engine().player.state.name.lower())
    win.btn_tone.click()
    if not _wait_until(app,
                       lambda: not win.btn_tone.isChecked(), 5.0):
        print("FAIL: TONE did not stop the playback", file=sys.stderr)
        return 1

    # 5) tone generator page: the full TonePlayer panel still works
    win._mode_group.button(MainWindow.MODE_TONE).click()
    if win.stack.currentIndex() != MainWindow.MODE_TONE:
        print("FAIL: tone page did not switch", file=sys.stderr)
        return 1
    panel = win.tp_panel
    band = panel._columns[0]
    band.slider.setValue(band.slider.maximum())       # level -> +10 dB
    _settle(app)
    if abs(panel._eng.player.level_at(0) - 10.0) > 1e-9:
        print("FAIL: band level edit did not reach the engine",
              file=sys.stderr)
        return 1
    png = out.replace(".png", "_tp.png")
    win.grab().save(png)
    print("saved", png, "| bands:", len(panel._columns),
          "| mode:", panel._play_button_mode,
          "| engine:", panel._eng.player.state.name.lower())

    # 6) analyzer stub page
    win._mode_group.button(MainWindow.MODE_ANALYZER).click()
    if win.stack.currentIndex() != MainWindow.MODE_ANALYZER:
        print("FAIL: stub page did not switch", file=sys.stderr)
        return 1
    _settle(app)
    png = out.replace(".png", "_stub.png")
    win.grab().save(png)
    print("saved", png)

    win.thread.stop()
    win.thread.wait(2000)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

```src/main.py
"""Entry point: the SKM measurement screen (standalone GUI)."""
from __future__ import annotations

from gui import main

if __name__ == "__main__":
    raise SystemExit(main())
```

```src/skm/__init__.py
"""SKM-2PO device link core (reverse-engineered from CKM2PO.exe)."""

from .constants import BAUD, DEVICE_DESCRIPTIONS, DEVICE_SERIAL, SENTINEL
from .device import DeviceError, SkmDevice
from .measurement import MeasurementEngine, Spectrum
from .protocol import Protocol
from .simulator import PairTransport, Simulator
from .transport import D2XXTransport, LoopbackTransport

__all__ = [
    "BAUD", "DEVICE_DESCRIPTIONS", "DEVICE_SERIAL", "SENTINEL",
    "DeviceError", "SkmDevice", "MeasurementEngine", "Spectrum",
    "Protocol", "PairTransport", "Simulator",
    "D2XXTransport", "LoopbackTransport",
]
```

```src/skm/constants.py
"""Protocol constants, RE'd from CKM2PO.exe (Ghidra) 2026-11.

Evidence map (Ghidra addresses):
  TX buffer      DAT_0059e764   (command frame built here byte-by-byte)
  RX buffer      DAT_00596764   (65536 bytes, filled by FT_Read drain)
  RX count       DAT_00596760
  error sentinel 0x499602D2 (= 1234567890 decimal — "status code" returned
                 by TOTAL layer when FT_* status != 0)
"""

# transport ---------------------------------------------------------------
SENTINEL = 0x499602D2        # FUN_0058a258: "exchange failed" marker
RX_BUFSZ = 0x10000           # FUN_00589164 reads at most 65536 bytes
TX_BUFSZ = 14                # longest frame: 'H' + 10 payload bytes ('aadc')

# baud from DRIVER i386 build / FUN_00589474 (RS-232 variant sets it too)
BAUD = 9600

# discovery (FUN_00570b84): open by description, serial hardcoded
DEVICE_DESCRIPTIONS = {
    3: ["CKM 23v1", "CKM 23v2", "CKM 23v3", "CKM 23v3RS"],   # version flag 3
    1: ["CKM 21v1", "CKM 21v2"],                            # version flag 1
}
DEVICE_SERIAL = "12345678"

# single-byte commands ----------------------------------------------------
CMD_KEEPALIVE = "A"       # FUN_005894b8/00589630/005897a8: A -> poll up to 51
                          #   retries until 7 reply bytes collected
CMD_F_QUERY = "F"         # FUN_00589904: F -> 2-byte reply parsed to double
                          # FUN_0058a6d4: F -> 3-byte echo reply [F,b1,b2]
CMD_MEASURE_START = "N"   # FUN_00589aec: N -> continuous byte stream until
                          #   65536 captured or 100 consecutive empty polls,
                          #   then app sends 'S'
CMD_MEASURE_STOP = "S"
CMD_CH_X = "X"            # FUN_00589f6c: param 1 -> 'X' (no reply)
CMD_CH_Y = "Y"            #             param 2/4 -> 'Y'
CMD_SET = {1: "I", 2: "B", 3: "C", 4: "D", 5: "E"}   # FUN_0058a024: no reply
CMD_QUERY = "Q"           # FUN_0058a10c: Q -> 1-byte reply (101 polls)
CMD_RANGE = "R"           # FUN_0058a3a8: R + '0'/'1'/'2' (no reply, ret 0/3)
CMD_SPEAKER_OFF = "U"     # FUN_0058a440: U/V -> 1-byte reply (1001 polls)
CMD_SPEAKER_ON = "V"
CMD_SET_REPLY = {1: "M", 2: "B", 3: "C", 4: "D", 5: "E"}  # FUN_0058a818:
                          # 1-byte reply (101 polls)
CMD_SAMPLE = "J"          # FUN_0058a988: J -> [J,hi,lo] 12-bit (0xFF hi -> 0)
CMD_GENERATOR = "H"       # FUN_0058aadc: H + 10-byte payload (11 total), no
                          #   direct reply; app then sends 'I' and expects
                          #   6 reply bytes (≤101 polls)

# retry budgets observed (empty poll loops, before "no reply" verdict)
RETRY_KEEPALIVE = 0x33    # 51
RETRY_SET_REPLY = 0x65    # 101  (M/B/C/D/E, Q, F-query, speaker uses 0x3E9)
RETRY_SPEAKER = 0x3E9     # 1001
RETRY_F_READ = 0x65
RETRY_J_READ = 0x65
RETRY_MEASURE_IDLE = 0x65  # 100 consecutive empty polls stop capture
MEASURE_WRAP = 0x10000     # capture wraps at 65536 samples

# generator frame layout (FUN_0058aadc): indices into TX buffer
#  0:'H' 1:p2 2:p1 3-4:div16(+/-1 guard,0->1) 5:2 6:p7 7:p6 8:p5 9-10:div16
GEN_DIV_HI = 3
GEN_DIV_LO = 4
```

```src/skm/device.py
"""High-level SKM operations (one SkmDevice == one open channel).

API mirrors the CKM2PO command wrappers; docstrings carry the Ghidra
addresses of the functions being mirrored.
"""

from __future__ import annotations

from .constants import (
    BAUD,
    CMD_CH_X,
    CMD_CH_Y,
    CMD_F_QUERY,
    CMD_GENERATOR,
    CMD_KEEPALIVE,
    CMD_MEASURE_START,
    CMD_MEASURE_STOP,
    CMD_QUERY,
    CMD_RANGE,
    CMD_SAMPLE,
    CMD_SET,
    CMD_SET_REPLY,
    CMD_SPEAKER_OFF,
    CMD_SPEAKER_ON,
    RETRY_F_READ,
    RETRY_J_READ,
    RETRY_KEEPALIVE,
    RETRY_SET_REPLY,
    RETRY_SPEAKER,
)
from .measurement import MeasurementEngine
from .protocol import Protocol
from .transport import Transport


class DeviceError(RuntimeError):
    pass


class SkmDevice:
    def __init__(self, transport: Transport, poll_ms: int = 2) -> None:
        self.t = transport
        self.p = Protocol(transport, poll_ms=poll_ms)
        self.version_flag = 3  # CKM-23
        self.speaker = False
        self.meas = MeasurementEngine(self)

    # -- session ------------------------------------------------------
    def open(self, baud: int = BAUD) -> None:
        self.t.open()
        self.t.set_baud(baud)

    def close(self) -> None:
        self.t.close()

    def handshake(self) -> bool:
        """'A' keep-alive with 7-byte exchange (FUN_005894b8,
        <=51 retries). Returns True iff reply body came back."""
        self.p.drain()
        self.p.send(bytes([ord(CMD_KEEPALIVE)]))
        self.p.sleep(2)
        r = self.p.receive(ord(CMD_KEEPALIVE), 7, RETRY_KEEPALIVE)
        return bool(r)

    # -- speakers (FUN_0058a440) -----------------------------------
    def set_speaker(self, on: bool) -> bool:
        cmd = CMD_SPEAKER_ON if on else CMD_SPEAKER_OFF
        self.p.drain()
        self.p.send(bytes([ord(cmd)]))
        self.p.sleep(2)
        r = self.p.receive(ord(cmd), 1, RETRY_SPEAKER)
        self.speaker = on
        return bool(r)

    # -- selects without replies (FUN_0058a024 / 00589f6c / 0058a3a8) ----
    def select_source(self, which: int) -> None:
        """I/B/C/D/E as in FUN_0058a024 (1..5)."""
        self.p.drain()
        self.p.send(bytes([ord(CMD_SET[which])]))
        self.p.sleep(2)

    def select_channel(self, x: bool = True, y: bool = False) -> None:
        """'X' (param 1) and/or 'Y' (param 2/4) — FUN_00589f6c."""
        self.p.drain()
        if x:
            self.p.send(bytes([ord(CMD_CH_X)]))
        if y:
            self.p.send(bytes([ord(CMD_CH_Y)]))
        self.p.sleep(2)

    def set_range(self, idx: int) -> bool:
        """'R'+'0'..'2' (FUN_0058a3a8): 0..2, no reply; False if bus dead."""
        self.p.drain()
        self.p.send(bytes([ord(CMD_RANGE), ord("0") + idx]))
        self.p.sleep(2)
        return not self.p.last_sentinel

    # -- reply commands ----------------------------------------------
    def query_status(self) -> int | None:
        """'Q' -> 1 byte (FUN_0058a10c, 101 retries). No echo check RE'd."""
        self.p.drain()
        self.p.send(bytes([ord(CMD_QUERY)]))
        self.p.sleep(2)
        r = self.p.receive(ord(CMD_QUERY), 1, RETRY_SET_REPLY)
        return r[0] if len(r) >= 1 else None

    def set_with_reply(self, which: int) -> int | None:
        """'M'/'B'/'C'/'D'/'E' w/ 1-byte reply (FUN_0058a818)."""
        self.p.drain()
        self.p.send(bytes([ord(CMD_SET_REPLY[which])]))
        self.p.sleep(2)
        r = self.p.receive(ord(CMD_SET_REPLY[which]), 1, RETRY_SET_REPLY)
        return r[0] if len(r) >= 1 else None

    def read_sample(self) -> int | None:
        """'J' 12-bit read (FUN_0058a988): [J,hi,lo]; hi==0xFF -> 0."""
        self.p.drain()
        self.p.send(bytes([ord(CMD_SAMPLE)]))
        self.p.sleep(2)
        r = self.p.receive(ord(CMD_SAMPLE), 3, RETRY_J_READ, echo=True)
        if len(r) < 3:
            return None
        hi, lo = r[1], r[2]
        return 0 if hi == 0xFF else (hi << 8) + lo

    def read_freq(self) -> tuple[int, int] | None:
        """'F' 3-byte echo reply (FUN_0058a6d4): returns (b1, b2-1)."""
        self.p.drain()
        self.p.send(bytes([ord(CMD_F_QUERY)]))
        self.p.sleep(2)
        r = self.p.receive(ord(CMD_F_QUERY), 3, RETRY_F_READ, echo=True)
        if len(r) < 3:
            return None
        return r[1], r[2] - 1

    # -- generator (FUN_0058aadc) ----------------------------------
    def set_generator(self, p2: int, p1: int, div: int, p7: int, p6: int,
                      p5: int, div2: int) -> bool:
        """'H' + 12-byte frame; div bytes use the +/-1, zero->identity
        guard RE'd from the wrapper; then 'I' and a 6-byte reply (101)."""
        def enc(lo: int) -> tuple[int, int]:
            if lo < 0:
                hi, lo2 = -((-lo >> 8) & 0xFF), -((lo) & 0xFF)
                if hi == 0:
                    hi = 0xFF
                return hi, lo2 if lo2 != 0 else 0xFF
            hi, lo2 = (lo >> 8) & 0xFF, lo & 0xFF
            if lo2 == 0:
                lo2 = 1
            if hi == 0:
                hi = 0xFF
            return hi, lo2

        frame = bytes([ord(CMD_GENERATOR), p2 & 0xFF, p1 & 0xFF]) \
            + bytes(enc(div)) + bytes([2, p7 & 0xFF, p6 & 0xFF, p5 & 0xFF]) \
            + bytes(enc(div2))
        self.p.drain()
        self.p.send(frame)
        self.p.sleep(2)
        self.p.send(bytes([ord("I")]))
        r = self.p.receive(ord("I"), 6, RETRY_SET_REPLY)
        return bool(r)

    # -- measurement ----------------------------------------------------
    def measure_bytes(self, wrap: int = 0x10000, idle_limit: int = 100,
                      idle_ms: float = 2.0) -> bytes:
        """FUN_00589aec: drain-check keeps the bus clean, 'N' -> capture
        byte stream until `wrap` samples OR `idle_limit` consecutive
        empty polls; then 'S'."""
        self.p.drain()
        self.p.send(bytes([ord(CMD_MEASURE_START)]))
        acc = bytearray()
        idle = 0
        while len(acc) < wrap and idle < idle_limit:
            chunk = self.p.drain()
            if chunk:
                acc.extend(chunk)
                idle = 0
            else:
                idle += 1
                self.p.sleep(idle_ms)
        self.p.send(bytes([ord(CMD_MEASURE_STOP)]))
        self.p.sleep(2)
        return bytes(acc[:wrap])
```

```src/skm/measurement.py
"""Measurement engine: 'N'-stream capture -> 65536-point spectrum.

Mirrors FUN_00589aec post-processing (65536 element loop then FFT with
FUN_004175b0/00415460 and band building). The app treats the captured
byte stream as a sequence of 65536 eight-bit ADC samples (the ring
buffer wraps after 0x10000 elements), so the spectrum input is
samples - 128.0 (device codes are unsigned) — RE-assumption recorded in
analysis/notes.md; configurable via `signed=False=True|False`.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .constants import MEASURE_WRAP


@dataclass
class Spectrum:
    freqs: np.ndarray        # bin centers, Hz
    lin: np.ndarray          # linear magnitudes (same length as freqs)
    db: np.ndarray           # 20*log10 magnitude, -inf floors to -160

    def band_db(self, f: float, half: float | None = None) -> float:
        m = (self.freqs >= f - (half or f * 0.03)) & \
            (self.freqs <= f + (half or f * 0.03))
        if not m.any():
            return -160.0
        return float(self.db[m].max())


class MeasurementEngine:
    def __init__(self, device, signed: bool = False) -> None:
        self.d = device
        self.signed = signed

    def capture(self, wrap: int = MEASURE_WRAP) -> np.ndarray:
        raw = self.d.measure_bytes(wrap=wrap)
        if not raw:
            raise RuntimeError("no measurement stream captured")
        if len(raw) < wrap:
            raw = raw + bytes(wrap - len(raw))
        x = np.frombuffer(raw[:wrap], dtype=np.uint8).astype(np.float64)
        if self.signed:
            x = ((x.view(np.int8)).astype(np.float64))
        else:
            x = x - 128.0
        return x

    def spectrum(self, fs: float, wrap: int = MEASURE_WRAP) -> Spectrum:
        x = self.capture(wrap=wrap)
        x = x - x.mean()                      # remove residual DC
        win = np.hanning(len(x))
        mag = np.abs(np.fft.rfft(x * win))
        freqs = np.fft.rfftfreq(len(x), d=1.0 / fs)
        db = np.full_like(mag, -160.0)
        nz = mag > 1e-12
        db[nz] = 20.0 * np.log10(mag[nz])
        return Spectrum(freqs=freqs, lin=mag, db=db)
```

```src/skm/protocol.py
"""Low-level exchange helpers mirroring the app's TOTAL layer.

Pattern RE'd from FUN_00589xxx wrappers:
  1) drain()            — FT_GetQueueStatus + FT_Read everything (FUN_00589164)
  2) failed() check     — sentinel 0x499602D2 (FUN_0058a258)
  3) build frame in the single TX buffer, FT_Write (FUN_00589144)
  4) pump-sleep (FUN_005891c8/20c)
  5) receive-until: accumulate newly drained bytes; on an empty poll count
     a retry; stop when replies complete OR retries exhausted. Byte 0 must
     echo the command (checked in 0058a988 etc.).
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from .transport import Transport


@dataclass
class Exchange:
    cmd: bytes
    reply: bytes

    def ok(self) -> bool:
        return bool(self.reply)


NO_REPLY = Exchange(b"", b"")


class Protocol:
    """Frame/receive layer on a Transport. One instance per open device."""

    def __init__(self, transport: Transport, poll_ms: int = 2) -> None:
        self.t = transport
        self.poll_ms = poll_ms
        self.last_sentinel = False

    # -- primitives (FUN_00589164 / 00589144 / 0058a258 equivalents) --------
    def drain(self) -> bytes:
        """Read everything currently queued; sentinel on FT error."""
        n = self.t.queue()
        if n is None or n < 0:
            self.last_sentinel = True
            return bytes([0]) * 0
        if n == 0:
            return b""
        return self.t.read(n, timeout=0.05)

    def send(self, frame: bytes) -> None:
        self.t.write(frame)

    def sleep(self, ms: float) -> None:
        time.sleep(ms / 1000.0)

    # -- generic receive-until loop ------------------------------------
    def receive(self, cmd: int, want: int, retries: int,
                echo: bool = False) -> bytes:
        """Collect `want` reply bytes; `retries` empty polls allowed.
        Mirror of 0058a440/0058a988/0058a818 loops. `echo=True` checks
        acc[0]==cmd (RE: only 'F' a6d4 and 'J' a988 verify the echo)."""
        acc = bytearray()
        empty = 0
        while len(acc) < want and empty < retries:
            chunk = self.drain()
            if chunk:
                acc.extend(chunk)
                empty = 0
            else:
                empty += 1
                self.sleep(self.poll_ms)
        if echo and acc and acc[0] != cmd:
            return b""          # echo mismatch -> treat as failure
        return bytes(acc) if len(acc) >= want else b""

    def frame(self, *payload: bytes) -> bytes:
        return b"".join(payload)
```

```src/skm/simulator.py
"""Byte-level SKM-23 device simulator.

Faithful to the RE'd protocol shapes (FUN_00589xxx wrappers + measurement
loop FUN_00589aec). The measured scene ("what the 'N' stream sounds like")
is generated synthetically so the measurement engine and the visualization
can be developed and demoed without hardware: a sine test tone (stepwise
rewritten by the 'H' generator command, with amplitude/noise knobs) on top
of a Gaussian noise floor. The D2XXTransport swaps this out 1:1 for HW.

Wiring: `PairTransport` (host side) <-> `Simulator` device side over a
queue pair — no serial stack needed.
"""

from __future__ import annotations

import math
import queue
import random
import threading
import time

from .constants import BAUD


class PairTransport:
    """App-side end of the pipe to a Simulator. Drop-in for D2XXTransport."""

    def __init__(self, peer: Simulator) -> None:
        self.peer = peer
        self.baud = BAUD
        peer.attach(self)

    def open(self) -> None:
        pass

    def close(self) -> None:
        self.peer.detach()

    def write(self, data: bytes) -> None:
        self.peer.on_bytes(data)

    def read(self, want: int, timeout: float = 1.0) -> bytes:
        return self.peer.read_for_host(want, timeout)

    def queue(self) -> int:
        return self.peer.host_queue.qsize()

    def set_baud(self, baud: int) -> None:
        self.baud = baud


class Simulator:
    """CKM-23 behaviour. Single-threaded event pump driven from
    `on_bytes`; replies land in `host_queue`. Most commands reply with
    1 byte; 'N' starts a continuous sample stream until 'S' is received."""

    stream_fs = 51200.0         # sample rate of the 'N' byte stream (8 bit)
    GEN_AMP = 100.0             # tone amplitude applied on generator-ON

    def __init__(self, tone_freq: float = 1000.0, tone_amp: float = 100.0,
                 noise_sigma: float = 3.0) -> None:
        self.host_queue: queue.Queue[int] = queue.Queue()
        self._measuring = False
        self._phase = 0.0
        # -- synthetic scene behind the 'N' stream -------------------------
        self.tone_freq = tone_freq  # test tone frequency, Hz (0 = silence)
        self.tone_amp = tone_amp    # dev counts (8-bit), amplitude
        self.noise_sigma = noise_sigma  # Gaussian noise floor, dev counts
        # -- protocol state ------------------------------------------------
        self.gain_ch = [0, 0]       # R0..R2 / P1..2 state per channel (X=0,Y=1)
        self.speaker = 0            # 'U'/'V'
        self.source = 0             # 'I'..'E'  (0..4)
        self.mode = 0               # 'M'..'E' separate 5-state group
        self.freq_bins = (2, 1)     # 'F' reply [b1, b2-1]
        self.j12 = 2048             # 'J' submodule value
        self.generator = False      # last 'H' state
        self.alive = True
        self._lock = threading.Lock()

    # -- scene control (direct API for tests/CLI; also driven by 'H') -----
    def set_scene(self, freq: float | None = None, amp: float | None = None,
                  noise: float | None = None) -> None:
        """Rewrite the synthetic scene emitted by the 'N' stream."""
        with self._lock:
            if freq is not None:
                self.tone_freq = freq
            if amp is not None:
                self.tone_amp = amp
            if noise is not None:
                self.noise_sigma = noise

    # -- plumbing ---------------------------------------------------------
    def attach(self, transport: PairTransport) -> None:
        self._t = transport

    def detach(self) -> None:
        pass

    def _reply(self, *vals: int) -> None:
        for v in vals:
            self.host_queue.put(v & 0xFF)

    def read_for_host(self, want: int, timeout: float) -> bytes:
        out = bytearray()
        deadline = time.monotonic() + timeout
        while len(out) < want and time.monotonic() < deadline:
            try:
                out.append(self.host_queue.get(timeout=max(
                    0.0, deadline - time.monotonic())))
            except queue.Empty:
                break
        return bytes(out)

    # -- the 'N' stream ----------------------------------------------------
    def _emit_stream_chunk(self) -> None:
        """Continuously emit 8-bit samples while measuring."""
        while self._measuring and self.alive:
            with self._lock:
                n = 512
                vals = bytearray()
                for _ in range(n):
                    self._phase += 2 * math.pi * self.tone_freq / self.stream_fs
                    s = (128.0
                         + self.tone_amp * math.sin(self._phase)
                         + random.gauss(0.0, self.noise_sigma))
                    vals.append(max(0, min(255, int(s))))
            for v in vals:
                self.host_queue.put(v)
            time.sleep(n / self.stream_fs)

    # -- command decoder ----------------------------------------------------
    def on_bytes(self, data: bytes) -> None:
        i = 0
        while i < len(data):
            cmd = data[i]
            i += 1
            if cmd == ord("A"):            # keep-alive: 'A' + 6 status bytes
                self._reply(ord("A"), 0x31, 0x32, 0x33, 0x34, 0x35, 0x0D)
            elif cmd == ord("F"):          # 3-byte echo reply [F,b1,b2]
                self._reply(ord("F"), self.freq_bins[0], self.freq_bins[1] + 1)
            elif cmd == ord("N"):
                self._measuring = True
                threading.Thread(target=self._emit_stream_chunk,
                                 daemon=True).start()
            elif cmd == ord("S"):
                self._measuring = False
            elif cmd == ord("X"):
                self.gain_ch[0] = 0
            elif cmd == ord("Y"):
                self.gain_ch[1] = 1
            elif cmd in b"IBCDE":
                self.source = b"IBCDE".index(cmd)
                if cmd == ord("I"):        # 'I' after 'H' expects a 6B reply
                    self._reply(0x31, 0x32, 0x33, 0x0D, 0x0A, 0)
            elif cmd == ord("Q"):
                self._reply(0x30 + (self.speaker & 1))
            elif cmd == ord("R"):
                self.gain_ch[0] = data[i] - ord("0")
                i += 1
            elif cmd in b"UV":
                self.speaker = 1 if cmd == ord("V") else 0
                self._reply(0x01)
            elif cmd in b"":
                pass
            elif cmd == ord("M"):
                self.mode = 0
                self._reply(0x01)
            elif cmd == ord("J"):
                v = self.j12
                self._reply(ord("J"), (v >> 8) & 0x0F, v & 0xFF)
            elif cmd == ord("H"):
                # 'H' + 10-byte payload (11-byte frame per FUN_0058aadc):
                # [H,p2,p1,div16,2,p7,p6,p5,div16]. The RE semantics of the
                # fields are unresolved; DEMO interpretation here: p2==0 stops
                # the generator (silence), otherwise the first divider word
                # sets the emitted tone as stream_fs/div (same encode as the
                # app side in device.set_generator).
                payload = data[i:i + 10]
                i += 10
                self._on_generator(payload)
            else:
                pass  # ignore unknown bytes (device firmware behaviour)

    # -- 'H' scene mapping ----------------------------------------------
    def _on_generator(self, payload: bytes) -> None:
        """Apply the 'H' payload to the scene (demo interpretation)."""
        if len(payload) < 5:
            return
        p2 = payload[0]
        if p2 == 0:                                 # STOP: silence the tone
            self.generator = False
            self.set_scene(amp=0.0)
            return
        hi, lo = payload[2], payload[3]
        div = lo if hi == 0xFF else (hi << 8) + lo  # inverse of the ±1 guard
        if div <= 0:
            return
        self.generator = True
        self.set_scene(freq=self.stream_fs / div, amp=self.__class__.GEN_AMP)
```

```src/skm/spectra.py
"""Precomputed spectrum files as an input source.

Duplicates the input of the signal-processor project: its `test_data`
directory holds two ready-made spectra as `freq<tab>voltage` text tables
with a 1 Hz grid (comments start with '#', '[' or '('):

  noise.txt         — "pure noise" spectrum (U_n)
  signal_noise.txt  — "signal + noise" spectrum (U_sn)

The GUI can connect to this file pair as to a third input kind and switch
between the two display modes (noise / signal + noise) without touching
the device transport.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

COMMENTS = ("#", "[", "(")


@dataclass(slots=True)
class SpectrumFile:
    """A parsed spectrum file: 1 Hz frequency grid + voltage levels, V."""

    path: Path
    kind: str                 # "noise" | "signal_noise"
    freqs_hz: list[float]
    volts: list[float]

    @classmethod
    def load(cls, kind: str, path: Path | None = None) -> SpectrumFile:
        if path is None:
            path = default_test_data_dir() / f"{kind}.txt"
        freqs: list[float] = []
        volts: list[float] = []
        with path.open(encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith(COMMENTS):
                    continue
                parts = line.replace(",", ".").split()
                if len(parts) < 2:
                    continue
                try:
                    freqs.append(float(parts[0]))
                    volts.append(float(parts[1]))
                except ValueError:      # tolerate stray non-numeric rows
                    continue
        if not freqs:
            raise ValueError(f"no spectrum rows in {path}")
        return cls(path=path, kind=kind, freqs_hz=freqs, volts=volts)


def default_test_data_dir() -> Path:
    """Resolve the signal-processor test_data directory.

    Order: SKM_TEST_DATA_DIR env override, then the sibling repository
    layout used on this machine (<projects>/signal-processor/test_data).
    """
    override = os.environ.get("SKM_TEST_DATA_DIR")
    if override:
        return Path(override)
    # spectra.py -> skm/ -> src/ -> <repo>/ -> <projects>/
    return Path(__file__).resolve().parents[2].parent / "signal-processor" / "test_data"


FILE_KINDS = ("noise", "signal_noise")
```

```src/skm/toneplayer.py
"""TonePlayer engine host for SKM.

SKM imports the companion app's Qt-free audio modules directly from
../tone-player/src (put on sys.path here), so tone playback happens in
the SKM process itself using TonePlayer's own engine
(`audio_engine.TonePlayer`: sine table + RawOutputStream). The playback
mechanism of TonePlayer is not altered: the engine, settings model and
validation are the very same code, imported; the full TonePlayer UI is
rebuilt in PySide6 by `tp_panel.py` on top of this module.

Persistent state is TonePlayer's `settings.json` (bands, levels, master
gain, output device, autoplay); it must sit next to the TonePlayer
executable: in dev the sibling repository (../tone-player/dist/), for
the frozen SKM app — next to the SKM executable (the "same folder"
deployment). Overrides: SKM_TONE_PLAYER_SRC (engine source dir),
SKM_TONE_SETTINGS (settings.json path).
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QCoreApplication  # noqa: F401 -- Qt ready check
from PySide6.QtNetwork import QLocalSocket  # noqa: F401 -- reserved: IPC later

#: Engine source directory override (dir containing audio_engine.py).
ENV_TONE_PLAYER_SRC = "SKM_TONE_PLAYER_SRC"
#: TonePlayer settings.json path override.
ENV_TONE_SETTINGS = "SKM_TONE_SETTINGS"


# ------------------------------------------------------------ engine path

def engine_src_dir() -> Path:
    """Directory with TonePlayer's Qt-free audio modules."""
    override = os.environ.get(ENV_TONE_PLAYER_SRC, "").strip()
    if override:
        return Path(override)
    # toneplayer.py -> skm/ -> src/ -> <skm repo>/ -> <projects>/
    return Path(__file__).resolve().parents[3] / "tone-player" / "src"


def _ensure_engine_importable() -> None:
    """Make `audio_engine` and friends importable (dev: sibling repo src).

    In the frozen SKM bundle the engine modules are collected by
    PyInstaller (see SKM.spec) and the FrozenImporter resolves the
    top-level names without any sys.path entry.
    """
    src = engine_src_dir()
    if (src / "audio_engine.py").is_file():
        if str(src) not in sys.path:
            sys.path.insert(0, str(src))     # engine lives there and only there
    elif not getattr(sys, "frozen", False):
        raise FileNotFoundError(
            f"TonePlayer engine sources not found in {src} "
            f"(set {ENV_TONE_PLAYER_SRC})")


# -------------------------------------------------------------- settings

def settings_path() -> Path:
    """TonePlayer's settings.json (bands, levels, master gain, output)."""
    override = os.environ.get(ENV_TONE_SETTINGS, "").strip()
    if override:
        path = Path(override)
    elif getattr(sys, "frozen", False):
        path = Path(sys.executable).resolve().parent / "settings.json"
    else:
        # toneplayer.py -> skm/ -> src/ -> <skm repo>/ -> <projects>/
        path = (Path(__file__).resolve().parents[3] / "tone-player" /
                "dist" / "settings.json")
    if not path.is_file():
        raise FileNotFoundError(
            f"TonePlayer settings.json is required, not found: {path}")
    return path


# ------------------------------------------------------------- integration

@dataclass(slots=True)
class Engine:
    """Shared playback engine: one TonePlayer instance for the whole app."""

    player: object   # audio_engine.TonePlayer
    config: object   # models.ToneConfig
    settings: object # models.Settings (frozen dataclass, replaced on edits)


_engine: Engine | None = None
_engine_error: str | None = None


def _build_engine() -> Engine:
    """Create the engine exactly as TonePlayer's MainWindow does."""
    _ensure_engine_importable()
    # Imports happen here, after sys.path preparation (dev build).
    from audio_engine import (  # type: ignore
        TonePlayer,  # type: ignore[import-not-found]
        find_device,
        list_output_devices,
    )
    from models import MASTER_BASE_DB, ToneConfig  # type: ignore[import-not-found]
    from settings_store import load_settings_at_startup  # type: ignore[import-not-found]

    settings = load_settings_at_startup(settings_path())
    player = TonePlayer(
        ToneConfig.from_settings(settings),
        settings.levels,
        MASTER_BASE_DB + settings.master_gain_db,
        level_scale=settings.level_scale,
    )
    player.set_autoplay(settings.autoplay)
    devices = list_output_devices()
    configured = find_device(devices, settings.device)
    player.set_device(configured.index if configured is not None else None)
    return Engine(player=player,
                  config=ToneConfig.from_settings(settings),
                  settings=settings)


def engine() -> Engine:
    """The shared engine instance, loaded lazily; errors are remembered."""
    global _engine, _engine_error
    if _engine is None:
        try:
            _engine = _build_engine()
            _engine_error = None
        except Exception as exc:                    # noqa: BLE001
            _engine_error = f"{type(exc).__name__}: {exc}"
    if _engine is None and _engine_error is not None:
        raise RuntimeError(_engine_error)
    return _engine  # type: ignore[return-value]


def engine_error() -> str | None:
    """Deferred load error, if any (."" when the engine is fine)."""
    return _engine_error if _engine is not None else _engine_error


def apply_settings(new_settings) -> Engine:
    """Replace the whole settings set, as TonePlayer's _apply_settings."""
    from audio_engine import find_device, list_output_devices  # type: ignore
    from models import MASTER_BASE_DB, ToneConfig  # type: ignore[import-not-found]

    eng = engine()
    eng.player.stop()
    eng.settings = new_settings
    eng.config = ToneConfig.from_settings(new_settings)
    eng.player.reconfigure(eng.config, new_settings.levels,
                           level_scale=new_settings.level_scale)
    eng.player.set_master_db(MASTER_BASE_DB + new_settings.master_gain_db)
    eng.player.set_autoplay(new_settings.autoplay)
    configured = find_device(list_output_devices(), new_settings.device)
    eng.player.set_device(configured.index if configured is not None else None)
    return eng


def save_settings() -> str:
    """Persist the current settings object via TonePlayer's own writer."""
    from settings_store import save_settings  # type: ignore[import-not-found]

    eng = engine()
    save_settings(settings_path(), eng.settings)
    return "saved"


# ------------------------------------------------------------- UI actions

def start_playing() -> str:
    """Play frequencies from the settings (band 0 first)."""
    from models import PlayerState  # type: ignore[import-not-found]

    eng = engine()
    if eng.player.state is PlayerState.PLAYING:
        return f"already playing: {describe()}"
    eng.player.start(0)
    return describe()


def stop_playing() -> str:
    """Stop playback (no-op when the engine never started)."""
    from models import PlayerState  # type: ignore[import-not-found]

    if _engine is None:
        return "stopped"
    if _engine.player.state is PlayerState.IDLE:
        return "stopped"
    _engine.player.stop()
    return describe()


def describe() -> str:
    """One-line status: state, frequency, level."""

    eng = engine()
    return (f"{eng.player.state.name.lower()} "
            f"{eng.player.current_frequency:.0f} Hz "
            f"{eng.player.current_gain_db:+.1f} dB")


def shutdown() -> None:
    """Stop the audio stream at app exit (engine call is synchronous)."""
    from models import PlayerState  # type: ignore[import-not-found]

    if _engine is None:
        return
    if _engine.player.state is not PlayerState.IDLE:
        _engine.player.stop()
```

```src/skm/tp_panel.py
"""TonePlayer playback panel: the original screen ported to PySide6.

A faithful 1:1 port of TonePlayer's main window (main_window.py +
band_widgets.py) on top of the integrated engine (skm.toneplayer):

  - header: settings (gear) button opening the settings dialog, preset
    combo ("По умолчанию" / user presets), preset save (bookmark) and
    delete (trash) buttons, output device combo and the
    "Автовоспроизведение" toggle switch;
  - transport row: the accent play button (icon-only, 38 px) and the
    stop button — exactly the two buttons the original has;
  - playback row: big mono frequency caption + "Тон N из M",
    progress bar and "осталось ..." counter;
  - band area: master volume column (ruler + frame) | divider |
    scrolling strip of narrow (66 px) band columns — value label only
    on the selected/current column (hover/editing/focus as in the
    original), accent frame on the sounding band, painter-drawn
    band play/pause icons, keyboard control (arrows navigate, Up/Down
    nudge the focused band, Space play/pause, Enter activate).

The playback mechanism is TonePlayer's own audio engine, imported
unchanged; persistence is TonePlayer's settings.json (debounced save).

Painting/colors are adapted to the light SKM chrome; layout, geometry,
state logic and wording come from the original app (Russian product
language, English code comments).
"""

from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path
from typing import Any

from PySide6.QtCore import (
    QEvent,
    QFileSystemWatcher,
    QPointF,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QIcon,
    QKeySequence,
    QPainter,
    QPen,
    QPixmap,
    QPolygonF,
    QRegion,
    QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QScrollBar,
    QSizePolicy,
    QSlider,
    QStyle,
    QStyleOptionSlider,
    QVBoxLayout,
    QWidget,
)

from skm import toneplayer
from skm.toneplayer import Engine
from skm.tp_settings import SettingsDialog

REFRESH_MS = 50
SAVE_DELAY_MS = 600
NOTICE_MS = 3500

# Column geometry — the same figures as the original tone-player widgets.
COLUMN_WIDTH = 66
COLUMN_VALUE_HEIGHT = 20
COLUMN_FREQUENCY_HEIGHT = 18
COLUMN_PLAY_SIZE = 28
COLUMN_SPACING = 6
COLUMN_MARGIN = 4
RULER_WIDTH = 40
RULER_SPACING = 4
FRAME_RADIUS = 10

BASE_FONT_PX = 14
FREQUENCY_VALUE_PX = 36
FREQUENCY_UNIT_PX = 16
FREQUENCY_BLOCK_WIDTH = 170

SANS_FAMILIES = ("IBM Plex Sans", "Noto Sans", "Segoe UI", "Ubuntu",
                 "DejaVu Sans")
MONO_FAMILIES = ("IBM Plex Mono", "JetBrains Mono", "Noto Sans Mono",
                 "Consolas", "DejaVu Sans Mono")

# Palette adapted to the light SKM chrome (original app is dark; role for
# role the same colors, layout and behaviour untouched).
COLOR_BG = "#eef1f6"
COLOR_SURFACE = "#f7f9fc"
COLOR_SURFACE_HOVER = "#e3edf8"
COLOR_BORDER = "#c3cdd9"
COLOR_BORDER_HOVER = "#9fb0c0"
COLOR_TEXT = "#20303f"
COLOR_MUTED = "#7b8794"
COLOR_DISABLED = "#a3aeb9"
COLOR_TRACK = "#dee6ef"
COLOR_ACCENT = "#2f88d6"
COLOR_ACCENT_HOVER = "#3f97e4"
COLOR_ON_ACCENT = "#ffffff"
COLOR_ICON = "#4a5764"
COLOR_ICON_DISABLED = "#a7b2bd"
COLOR_SWITCH_OFF = "#c2cdd8"

PLAY_BUTTON_LOOK = {
    "start": ("Запустить", "start"),
    "pause": ("Пауза", "pause"),
    "resume": ("Продолжить", "start"),
}


def _mods() -> tuple[Any, Any, Any, Any]:
    """Return (audio_engine, models, ui_text, settings_store) of TonePlayer.

    The call chain prepares the engine import paths first.
    """
    toneplayer.engine()
    import audio_engine  # type: ignore[import-not-found]
    import models  # type: ignore[import-not-found]
    import settings_store  # type: ignore[import-not-found]
    import ui_text  # type: ignore[import-not-found]

    return audio_engine, models, ui_text, settings_store


def _fmt_level(level_db: float) -> str:
    _, _, ui_text, _ = _mods()
    return ui_text.format_db(level_db, unit=False)


def _fmt_frequency(hz: float) -> str:
    _, _, ui_text, _ = _mods()
    return ui_text.format_frequency_value(hz)


def _fmt_scale(value_db: float) -> str:
    _, _, ui_text, _ = _mods()
    return ui_text.format_scale(value_db)


def _fmt_duration(seconds: float) -> str:
    _, _, ui_text, _ = _mods()
    return ui_text.format_duration(seconds)


def _track_y(position: int, maximum: int, height: int) -> float:
    """Track height for a position (maximum at the top)."""
    ratio = position / maximum if maximum > 0 else 0.0
    return height - ratio * height


def _wheel_scroll_delta(event: QEvent) -> int:
    """Wheel gesture/touchpad to a horizontal scroll delta."""
    pixel = event.pixelDelta()
    if not pixel.isNull():
        return pixel.x() or pixel.y()
    angle = event.angleDelta()
    return angle.x() or angle.y()


# ------------------------------------------------------------------ icons

def _draw_glyph(kind: str, size: int, color: str) -> QPixmap:
    """Painter-drawn glyphs of the original app (same shapes)."""
    ratio = 2
    pixmap = QPixmap(size * ratio, size * ratio)
    pixmap.setDevicePixelRatio(float(ratio))
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(size / 24, size / 24)
    qcolor = QColor(color)

    if kind == "settings":
        painter.setPen(QPen(qcolor, 2.0, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap,
                            Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(12.0, 12.0), 4.0, 4.0)
        for angle in range(0, 360, 45):
            radians = math.radians(angle)
            painter.drawLine(
                QPointF(12.0 + 6.5 * math.cos(radians),
                        12.0 + 6.5 * math.sin(radians)),
                QPointF(12.0 + 9.5 * math.cos(radians),
                        12.0 + 9.5 * math.sin(radians)))
    elif kind == "presetSave":
        painter.setPen(QPen(qcolor, 1.9, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap,
                            Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPolygon(QPolygonF([
            QPointF(7.0, 4.0), QPointF(17.0, 4.0), QPointF(17.0, 20.0),
            QPointF(12.0, 15.5), QPointF(7.0, 20.0)]))
    elif kind == "delete":
        painter.setPen(QPen(qcolor, 1.8, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap,
                            Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawLine(QPointF(5.0, 7.0), QPointF(19.0, 7.0))
        painter.drawLine(QPointF(9.0, 4.0), QPointF(15.0, 4.0))
        painter.drawRoundedRect(QRectF(7.0, 7.0, 10.0, 13.0), 2.0, 2.0)
        painter.drawLine(QPointF(10.0, 10.0), QPointF(10.0, 17.0))
        painter.drawLine(QPointF(14.0, 10.0), QPointF(14.0, 17.0))
    else:
        glyph = ("start" if kind == "bandStart" else
                 "pause" if kind == "bandPause" else kind)
        painter.setBrush(qcolor)
        if glyph == "start":
            painter.setPen(QPen(qcolor, 1.5, Qt.PenStyle.SolidLine,
                                Qt.PenCapStyle.RoundCap,
                                Qt.PenJoinStyle.RoundJoin))
            painter.drawPolygon(QPolygonF(
                [QPointF(7.5, 5), QPointF(7.5, 19), QPointF(19.5, 12)]))
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            if glyph == "pause":
                painter.drawRoundedRect(QRectF(6, 4, 4, 16), 1, 1)
                painter.drawRoundedRect(QRectF(14, 4, 4, 16), 1, 1)
            elif glyph == "stop":
                painter.drawRoundedRect(QRectF(5, 5, 14, 14), 2, 2)
    painter.end()
    return pixmap


def _make_icon(kind: str, size: int, normal: str, disabled: str) -> QIcon:
    icon = QIcon()
    icon.addPixmap(_draw_glyph(kind, size, normal), QIcon.Mode.Normal)
    icon.addPixmap(_draw_glyph(kind, size, disabled), QIcon.Mode.Disabled)
    return icon


def make_icons() -> dict[str, QIcon]:
    """The icon set of the original app."""
    return {
        "start": _make_icon("start", 18, COLOR_ON_ACCENT, COLOR_DISABLED),
        "pause": _make_icon("pause", 18, COLOR_ON_ACCENT, COLOR_DISABLED),
        "stop": _make_icon("stop", 18, COLOR_TEXT, COLOR_DISABLED),
        "settings": _make_icon("settings", 20, COLOR_ICON,
                               COLOR_ICON_DISABLED),
        "presetSave": _make_icon("presetSave", 18, COLOR_ICON,
                                 COLOR_ICON_DISABLED),
        "delete": _make_icon("delete", 18, COLOR_ICON, COLOR_ICON_DISABLED),
        "bandStart": _make_icon("bandStart", 14, COLOR_ICON,
                                COLOR_ICON_DISABLED),
        "bandPause": _make_icon("bandPause", 14, COLOR_ICON,
                                COLOR_ICON_DISABLED),
    }


def _pick_font_family(candidates: tuple[str, ...], fallback: str) -> str:
    available = set(QFontDatabase.families())
    for name in candidates:
        if name in available:
            return name
    return fallback


# ------------------------------------------------------------- stylesheet

_STYLESHEET = f"""
QDialog {{
    background-color: {COLOR_BG};
}}
TonePlayerPanel {{
    background: {COLOR_BG};
}}
QWidget {{
    color: {COLOR_TEXT};
}}
QToolTip {{
    background-color: {COLOR_SURFACE};
    color: {COLOR_TEXT};
    border: 1px solid {COLOR_BORDER};
    padding: 4px 6px;
}}
QLabel {{
    background: transparent;
}}
QLabel#captionLabel, QLabel#subtitleLabel,
QLabel#statusLabel, QLabel#bandValue, QLabel#bandFrequency,
QLabel#fieldLabel {{
    color: {COLOR_MUTED};
}}
QLabel#subtitleLabel, QLabel#statusLabel {{ font-size: 13px; }}
QLabel#captionLabel, QLabel#fieldLabel {{ font-size: 13px; }}
QLabel#sectionLabel {{
    color: {COLOR_TEXT};
    font-size: 16px;
    font-weight: 600;
    padding-top: 6px;
}}
QLabel#bandValue {{ font-size: 12px; }}
QLabel#bandFrequency {{ font-size: 11px; }}

QFrame#divider {{ background-color: {COLOR_BORDER}; }}
QScrollArea {{ background: transparent; border: none; }}
BandStrip {{ background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}

QPushButton {{
    background-color: transparent;
    border: 1px solid {COLOR_BORDER};
    border-radius: 12px;
    padding: 0 12px;
    font-size: 16px;
    font-weight: 500;
}}
QPushButton:hover:enabled {{
    background-color: {COLOR_SURFACE};
    border-color: {COLOR_BORDER_HOVER};
}}
QPushButton:pressed:enabled {{ background-color: {COLOR_TRACK}; }}
QPushButton:focus {{ border-color: {COLOR_ACCENT}; }}
QPushButton:disabled {{ color: {COLOR_DISABLED}; }}
QPushButton#navButton {{
    background-color: {COLOR_SURFACE};
    padding: 0;
}}
QPushButton#navButton:hover:enabled {{
    background-color: {COLOR_SURFACE_HOVER};
}}
QPushButton#navButton:pressed:enabled {{ background-color: {COLOR_TRACK}; }}
QPushButton#navButton:disabled {{ background-color: transparent; }}
QPushButton#bandPlay {{
    background-color: transparent;
    border: none;
    border-radius: 14px;
    padding: 0;
}}
QPushButton#bandPlay:hover:enabled {{
    background-color: {COLOR_TRACK};
}}
QPushButton#playButton {{
    background-color: {COLOR_ACCENT};
    color: {COLOR_ON_ACCENT};
    border: 1px solid {COLOR_ACCENT};
    font-size: 17px;
    font-weight: 600;
}}
QPushButton#playButton:hover:enabled {{
    background-color: {COLOR_ACCENT_HOVER};
    border-color: {COLOR_ACCENT_HOVER};
}}
QPushButton#playButton:pressed:enabled {{
    background-color: {COLOR_ACCENT};
}}
QPushButton#playButton:focus {{ border: 2px solid {COLOR_TEXT}; }}
QPushButton#playButton:disabled {{
    background-color: {COLOR_SURFACE};
    color: {COLOR_DISABLED};
    border: 1px solid {COLOR_BORDER};
}}

QProgressBar {{
    border: none;
    border-radius: 3px;
    background-color: {COLOR_TRACK};
}}
QProgressBar::chunk {{
    background-color: {COLOR_ACCENT};
    border-radius: 3px;
}}

QSlider::groove:vertical {{
    width: 6px;
    background-color: {COLOR_TRACK};
    border-radius: 3px;
}}
QSlider::handle:vertical {{
    background-color: {COLOR_ACCENT};
    height: 16px;
    margin: 0 -6px;
    border-radius: 8px;
}}
QSlider::handle:vertical:hover {{ background-color: {COLOR_ACCENT_HOVER}; }}

QComboBox {{
    background-color: {COLOR_SURFACE};
    border: 1px solid {COLOR_BORDER};
    border-radius: 10px;
    padding: 0 12px;
    font-size: 14px;
}}
QComboBox:hover:enabled {{ border-color: {COLOR_BORDER_HOVER}; }}
QComboBox:focus {{ border-color: {COLOR_ACCENT}; }}
QComboBox:disabled {{ color: {COLOR_DISABLED}; }}
QComboBox::drop-down {{ border: none; width: 30px; }}
QComboBox::down-arrow {{ image: none; }}
QComboBox QAbstractItemView {{
    background-color: {COLOR_SURFACE};
    border: 1px solid {COLOR_BORDER};
    selection-background-color: {COLOR_BORDER_HOVER};
    selection-color: {COLOR_TEXT};
    outline: 0;
    padding: 4px;
}}

QDoubleSpinBox, QSpinBox {{
    background-color: {COLOR_SURFACE};
    border: 1px solid {COLOR_BORDER};
    border-radius: 8px;
    padding: 5px 8px;
    min-height: 24px;
}}
QDoubleSpinBox:focus, QSpinBox:focus {{ border-color: {COLOR_ACCENT}; }}
QPlainTextEdit {{
    background-color: {COLOR_SURFACE};
    border: 1px solid {COLOR_BORDER};
    border-radius: 8px;
    padding: 6px;
}}
QLineEdit {{
    background-color: {COLOR_SURFACE};
    color: {COLOR_TEXT};
    border: 1px solid {COLOR_BORDER};
    border-radius: 8px;
    padding: 7px 10px;
    min-height: 22px;
    selection-background-color: {COLOR_ACCENT};
    selection-color: {COLOR_ON_ACCENT};
}}
QLineEdit:focus {{ border-color: {COLOR_ACCENT}; }}

QScrollBar:horizontal {{
    background: transparent;
    height: 8px;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: {COLOR_BORDER_HOVER};
    border-radius: 4px;
    min-width: 40px;
}}
QScrollBar::handle:horizontal:hover {{ background: {COLOR_MUTED}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background: transparent;
}}
"""


# ------------------------------------------------------------------ slider

class LevelSlider(QSlider):
    """Vertical slider with the zero line and the focus ring (original)."""

    navigate_requested = Signal(int)
    activate_requested = Signal()
    scroll_requested = Signal(int)
    focus_changed = Signal(bool)

    def __init__(self, scale: Any, parent: QWidget | None = None) -> None:
        super().__init__(Qt.Orientation.Vertical, parent)
        self._scale = scale
        self.setRange(0, scale.position_count)
        self._apply_steps()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Expanding)

    def _apply_steps(self) -> None:
        self.setSingleStep(1)
        self.setPageStep(max(round(1.0 / self._scale.step_db), 1))

    def set_scale(self, scale: Any) -> None:
        """Change range/step keeping the position when it fits."""
        self._scale = scale
        self.setRange(0, scale.position_count)
        self._apply_steps()
        self.update()

    def zero_position(self) -> int:
        """Position for 0 dB."""
        return self._scale.position(0.0)

    def handle_rect(self, position: int | None = None) -> QRectF:
        """Handle rect from the style geometry for position."""
        option = QStyleOptionSlider()
        self.initStyleOption(option)                     # type: ignore[attr-defined]
        if position is not None:
            option.sliderPosition = position
            option.sliderValue = position
        style = self.style()
        if style is None:
            return QRectF()
        rect = style.subControlRect(
            QStyle.ComplexControl.CC_Slider, option,
            QStyle.SubControl.SC_SliderHandle, self)
        return QRectF(rect)

    def handle_center_y(self, position: int) -> float:
        """Handle center height for position (style geometry)."""
        rect = self.handle_rect(position)
        if rect.isNull():
            return _track_y(position, self.maximum(), self.height())
        return rect.center().y()

    def paintEvent(self, ev) -> None:                    # noqa: N802
        super().paintEvent(ev)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        handle = self.handle_rect()

        # Dashed zero line, hidden under the handle (as in the original).
        painter.save()
        if not handle.isNull():
            painter.setClipRegion(QRegion(
                self.rect()).subtracted(
                QRegion(handle.toRect().adjusted(-2, -2, 2, 2))))
        y = self.handle_center_y(self.zero_position())
        painter.setPen(QPen(QColor(COLOR_BORDER_HOVER), 1,
                            Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(8.0, y), QPointF(self.width() - 8.0, y))
        painter.restore()

        # Focus ring around the handle (as in the original).
        if self.hasFocus() and not handle.isNull():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(COLOR_TEXT), 2))
            ring = QRectF(handle).adjusted(1.5, 1.5, -1.5, -1.5)
            painter.drawRoundedRect(ring, ring.height() / 2,
                                    ring.height() / 2)

    def mouseDoubleClickEvent(self, ev) -> None:         # noqa: N802
        self.setValue(self.zero_position())
        if ev is not None:
            ev.accept()

    def contextMenuEvent(self, ev) -> None:              # noqa: N802
        self.setValue(self.zero_position())
        if ev is not None:
            ev.accept()

    def keyPressEvent(self, ev) -> None:                 # noqa: N802
        if ev is not None and ev.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            self.navigate_requested.emit(
                -1 if ev.key() == Qt.Key.Key_Left else 1)
            ev.accept()
            return
        if ev is not None and ev.key() in (Qt.Key.Key_Return,
                                           Qt.Key.Key_Enter):
            self.activate_requested.emit()
            ev.accept()
            return
        super().keyPressEvent(ev)

    def wheelEvent(self, ev) -> None:                    # noqa: N802
        if ev is None:
            return
        self.scroll_requested.emit(_wheel_scroll_delta(ev))
        ev.accept()

    def focusInEvent(self, ev) -> None:                  # noqa: N802
        super().focusInEvent(ev)
        self.focus_changed.emit(True)

    def focusOutEvent(self, ev) -> None:                 # noqa: N802
        super().focusOutEvent(ev)
        self.focus_changed.emit(False)


# ------------------------------------------------------------------- ruler

class LevelRuler(QWidget):
    """Shared level scale beside the columns: max, zero and min marks."""

    def __init__(self, scale: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scale = scale
        self._slider: LevelSlider | None = None
        self.setFixedWidth(RULER_WIDTH)
        self.setSizePolicy(QSizePolicy.Policy.Fixed,
                           QSizePolicy.Policy.Expanding)

    def set_scale(self, scale: Any) -> None:
        self._scale = scale
        self.update()

    def set_slider(self, slider: LevelSlider | None) -> None:
        self._slider = slider
        self.update()

    def paintEvent(self, ev) -> None:                    # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = QFont(self.font())
        font.setPixelSize(11)
        painter.setFont(font)

        positions = (
            (self._scale.position(self._scale.max_db),
             _fmt_scale(self._scale.max_db)),
            (self._scale.position(0.0), "0"),
            (self._scale.position(self._scale.min_db),
             _fmt_scale(self._scale.min_db)),
        )
        if self._slider is not None:
            slider_top = self._slider.mapToGlobal(
                self._slider.rect().topLeft()).y()
            ruler_top = self.mapToGlobal(self.rect().topLeft()).y()
            top = float(slider_top - ruler_top)
            y_positions = [top + self._slider.handle_center_y(position)
                           for position, _ in positions]
        else:
            y_positions = [
                _track_y(position, self._scale.position_count, self.height())
                for position, _ in positions]
        for (_, text), y in zip(positions, y_positions, strict=True):
            painter.setPen(QPen(QColor(COLOR_BORDER_HOVER), 1))
            painter.drawLine(QPointF(self.width() - 12.0, y),
                             QPointF(self.width() - 5.0, y))
            painter.setPen(QColor(COLOR_MUTED))
            label_y = min(max(y - 8.0, 0.0), max(0.0, self.height() - 16.0))
            painter.drawText(QRectF(0.0, label_y, self.width() - 15.0, 16.0),
                             int(Qt.AlignmentFlag.AlignRight
                                 | Qt.AlignmentFlag.AlignVCenter), text)


# ---------------------------------------------------------------- band strip

def _paint_column_frame(widget: QWidget, *, accent: bool) -> None:
    """Column border; accent = the sounding band (as in the original)."""
    painter = QPainter(widget)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(COLOR_SURFACE_HOVER if accent
                            else COLOR_SURFACE))
    painter.setPen(QPen(QColor(COLOR_ACCENT if accent else COLOR_BORDER), 1))
    painter.drawRoundedRect(
        QRectF(widget.rect()).adjusted(1, 1, -1, -1),
        FRAME_RADIUS, FRAME_RADIUS)
    painter.end()


class MasterFrame(QWidget):
    """Master column: the same width as a band column (original)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(COLUMN_WIDTH)
        self.setSizePolicy(QSizePolicy.Policy.Fixed,
                           QSizePolicy.Policy.Expanding)


class _BandColumn(QWidget):
    """One band column: value, vertical slider, frequency, play button."""

    def __init__(self, index: int, band: Any, scale: Any,
                 icons: dict[str, QIcon], *,
                 on_level, on_play, on_select, on_activate,
                 on_navigate, on_scroll,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.index = index
        self._scale = scale
        self._on_level = on_level
        self._on_play = on_play
        self._on_select = on_select
        self._current = False
        self._playing = False
        self._hover = False
        self._editing = False
        self._icons = icons

        self.setFixedWidth(COLUMN_WIDTH)
        self.setSizePolicy(QSizePolicy.Policy.Fixed,
                           QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(COLUMN_MARGIN, COLUMN_MARGIN,
                                  COLUMN_MARGIN, COLUMN_MARGIN)
        layout.setSpacing(COLUMN_SPACING)

        self.value_label = QLabel()
        self.value_label.setObjectName("bandValue")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.value_label.setFixedHeight(COLUMN_VALUE_HEIGHT)
        layout.addWidget(self.value_label)

        self.slider = LevelSlider(scale, self)
        self.slider.setAccessibleName(
            f"Уровень {_fmt_frequency(band.frequency_hz)} Гц")
        self.slider.setValue(scale.position(band.level_db))
        self.slider.valueChanged.connect(self._on_value_changed)
        self.slider.sliderPressed.connect(self._on_slider_pressed)
        self.slider.sliderReleased.connect(self._on_slider_released)
        self.slider.navigate_requested.connect(on_navigate)
        self.slider.scroll_requested.connect(on_scroll)
        self.slider.activate_requested.connect(
            lambda: on_activate(self.index))
        self.slider.focus_changed.connect(self._on_slider_focus_changed)
        layout.addWidget(self.slider, 1)

        self.frequency_label = QLabel(_fmt_frequency(band.frequency_hz))
        self.frequency_label.setObjectName("bandFrequency")
        self.frequency_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.frequency_label.setFixedHeight(COLUMN_FREQUENCY_HEIGHT)
        layout.addWidget(self.frequency_label)

        self.play_button = QPushButton()
        self.play_button.setObjectName("bandPlay")
        self.play_button.setFixedSize(COLUMN_PLAY_SIZE, COLUMN_PLAY_SIZE)
        self.play_button.setIcon(icons["bandStart"])
        self.play_button.setIconSize(QSize(14, 14))
        self.play_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.play_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.play_button.clicked.connect(lambda: on_play(self.index))
        layout.addWidget(self.play_button, 0, Qt.AlignmentFlag.AlignHCenter)

        self.set_level(band.level_db)
        self._update_tooltip()
        self.set_current(False, False)

    def set_level(self, level_db: float) -> None:
        """Show the level without emitting a change signal."""
        self.slider.blockSignals(True)
        self.slider.setValue(self._scale.position(level_db))
        self.slider.blockSignals(False)
        self._update_text()

    def set_current(self, current: bool, playing: bool) -> None:
        """current — selected tone column; playing — it sounds now."""
        if (current, playing) == (self._current, self._playing):
            return
        self._current = current
        self._playing = playing
        icon = (self._icons["bandPause"] if current and playing
                else self._icons["bandStart"])
        self.play_button.setIcon(icon)
        self._update_text()
        self.update()

    def set_scale(self, scale: Any) -> None:
        self._scale = scale
        self.slider.set_scale(scale)
        self._update_tooltip()

    def _level(self) -> float:
        return self._scale.at_position(self.slider.value())

    def _update_text(self) -> None:
        # Same visibility rule as the original: only the selected column
        # (or the hovered/edited/focused one) shows its value label; the
        # others stay empty so no stale numbers survive a click.
        visible = (self._current or self.slider.hasFocus()
                   or self._hover or self._editing)
        self.value_label.setText(
            _fmt_level(self._level()) if visible else "")
        self._update_tooltip()

    def _update_tooltip(self) -> None:
        text = (
            f"{self.frequency_label.text()} Гц\n"
            f"Уровень: {_fmt_level(self._level())}\n"
            "↑ ↓ — изменить, ← → — выбор ползунка\n"
            "Enter — включить воспроизведение, Пробел — пауза\n"
            "Двойной щелчок или правая кнопка — сбросить в 0 дБ"
        )
        self.setToolTip(text)
        self.slider.setToolTip(text)
        self.frequency_label.setToolTip(text)

    def _on_value_changed(self, _position: int) -> None:
        self._update_text()
        self._on_level(self.index, self._level())

    def _on_slider_pressed(self) -> None:
        self._editing = True
        self._on_select(self.index)
        self._update_text()

    def _on_slider_released(self) -> None:
        self._editing = False
        self._update_text()

    def _on_slider_focus_changed(self, _focused: bool) -> None:
        self._update_text()

    def mousePressEvent(self, ev) -> None:               # noqa: N802
        self._on_select(self.index)
        self.slider.setFocus()
        super().mousePressEvent(ev)

    def contextMenuEvent(self, ev) -> None:              # noqa: N802
        self.set_level(0.0)
        self._on_level(self.index, 0.0)
        if ev is not None:
            ev.accept()

    def enterEvent(self, ev) -> None:                    # noqa: N802
        self._hover = True
        self._update_text()
        super().enterEvent(ev)

    def leaveEvent(self, ev) -> None:                    # noqa: N802
        self._hover = False
        self._editing = False
        self._update_text()
        super().leaveEvent(ev)

    def paintEvent(self, ev) -> None:                    # noqa: N802
        if self._current:
            _paint_column_frame(self, accent=self._playing)
        super().paintEvent(ev)


class BandStrip(QWidget):
    """Strip of band columns with the shared ruler (original BandStrip)."""

    def __init__(self, scale: Any, icons: dict[str, QIcon], *,
                 on_level, on_play, on_select, on_activate,
                 on_navigate, on_scroll,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scale = scale
        self._icons = icons
        self._on_level = on_level
        self._on_play = on_play
        self._on_select = on_select
        self._on_activate = on_activate
        self._on_navigate = on_navigate
        self._on_scroll = on_scroll
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(4, 0, 8, 0)
        self._layout.setSpacing(RULER_SPACING)
        self._columns: list[_BandColumn] = []
        self.ruler = LevelRuler(scale)
        self._layout.addWidget(self.ruler)
        self._layout.addStretch(1)
        self.setSizePolicy(QSizePolicy.Policy.Minimum,
                           QSizePolicy.Policy.Expanding)

    @property
    def count(self) -> int:
        """Number of columns in the strip."""
        return len(self._columns)

    def set_bands(self, bands, scale: Any) -> None:
        """Rebuild the columns for a new band set."""
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._columns = []
        self._scale = scale
        self.ruler = LevelRuler(scale)
        self._layout.addWidget(self.ruler)
        for index, band in enumerate(bands):
            column = _BandColumn(
                index, band, scale, self._icons,
                on_level=self._on_level, on_play=self._on_play,
                on_select=self._on_select, on_activate=self._on_activate,
                on_navigate=self._on_navigate, on_scroll=self._on_scroll)
            self._columns.append(column)
            self._layout.addWidget(column)
        if self._columns:
            self.ruler.set_slider(self._columns[0].slider)
        self._layout.addStretch(1)

    def set_current(self, index: int, playing: bool) -> None:
        for number, column in enumerate(self._columns):
            column.set_current(number == index, playing and number == index)

    def set_scale(self, scale: Any) -> None:
        self._scale = scale
        self.ruler.set_scale(scale)
        for column in self._columns:
            column.set_scale(scale)

    def column(self, index: int) -> _BandColumn:
        return self._columns[index]


class BandScrollArea(QScrollArea):
    """Scroll area of the original: wheel scrolls the strip horizontally."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def wheelEvent(self, ev) -> None:                    # noqa: N802
        if ev is None:
            return
        bar = self.horizontalScrollBar()
        if bar is not None:
            bar.setValue(bar.value() - _wheel_scroll_delta(ev))
        ev.accept()


# -------------------------------------------------------------------- switch

class ToggleSwitch(QAbstractButton):
    """The original autoplay toggle switch."""

    _TRACK_WIDTH = 48
    _TRACK_HEIGHT = 26
    _KNOB = 20
    _PAD = 3
    _RING = 2

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(self._TRACK_WIDTH + 2 * self._RING,
                          self._TRACK_HEIGHT + 2 * self._RING)

    def paintEvent(self, ev) -> None:                    # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():
            painter.setOpacity(0.5)

        checked = self.isChecked()
        track = QRectF(self._RING, self._RING, self._TRACK_WIDTH,
                       self._TRACK_HEIGHT)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(COLOR_ACCENT if checked
                                else COLOR_SWITCH_OFF))
        painter.drawRoundedRect(track, self._TRACK_HEIGHT / 2,
                                self._TRACK_HEIGHT / 2)

        knob_x = (track.right() - self._PAD - self._KNOB if checked
                  else track.left() + self._PAD)
        painter.setBrush(QColor(COLOR_ON_ACCENT if checked
                                else COLOR_MUTED))
        painter.drawEllipse(QRectF(knob_x, track.top() + self._PAD,
                                   self._KNOB, self._KNOB))

        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(COLOR_TEXT), 2))
            radius = self.height() / 2 - 1
            painter.drawRoundedRect(
                QRectF(1, 1, self.width() - 2, self.height() - 2),
                radius, radius)


class ChevronComboBox(QComboBox):
    """Combo with the hand-painted chevron of the original."""

    def paintEvent(self, ev) -> None:                    # noqa: N802
        super().paintEvent(ev)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = (COLOR_MUTED if self.isEnabled() else COLOR_ICON_DISABLED)
        painter.setPen(QPen(QColor(color), 1.8, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap,
                            Qt.PenJoinStyle.RoundJoin))
        center_x = self.width() - 20.0
        center_y = self.height() / 2
        painter.drawPolyline(QPolygonF([
            QPointF(center_x - 4, center_y - 2),
            QPointF(center_x, center_y + 2),
            QPointF(center_x + 4, center_y - 2)]))


# -------------------------------------------------------------------- panel

class TonePlayerPanel(QWidget):
    """The TonePlayer screen (original port) as a mode page."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._eng: Engine | None = None
        self._engine_error = ""
        try:
            self._eng = toneplayer.engine()
        except Exception as exc:                    # noqa: BLE001
            self._engine_error = str(exc)

        self._strip: BandStrip | None = None
        self._finishing_handled = False
        self._notice = ""
        self._save_error = ""
        self._focused = 0
        self._play_button_mode = ""
        self._last_band_index = -1
        self._devices: list[Any] = []
        self._icons = make_icons()

        self._sans_family = _pick_font_family(
            SANS_FAMILIES,
            QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont)
            .family())
        self._mono_family = _pick_font_family(
            MONO_FAMILIES,
            QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
            .family())
        base_font = QFont(self._sans_family)
        base_font.setPixelSize(BASE_FONT_PX)
        self.setFont(base_font)
        self.setStyleSheet(_STYLESHEET)

        if self._eng is not None:
            audio, _, _, _ = _mods()
            self._devices = list(audio.list_output_devices())

        self._build_ui()
        self._settings_watcher = QFileSystemWatcher(self)
        self._reload_timer = QTimer(self)
        self._reload_timer.setSingleShot(True)
        self._reload_timer.setInterval(250)
        self._reload_timer.timeout.connect(self._reload_settings)

        if self._eng is not None:
            self._refresh_presets()
            self._rebuild_bands()
            try:
                self._settings_path = toneplayer.settings_path()
                self._settings_file_bytes = self._read_settings_file()
                self._settings_watcher.addPath(str(self._settings_path))
                self._settings_watcher.fileChanged.connect(
                    self._on_settings_file_changed)
            except Exception:                       # noqa: BLE001
                self._settings_file_bytes = b""
                self._settings_path = None

            self._space_shortcut = QShortcut(
                QKeySequence(Qt.Key.Key_Space), self)
            self._space_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
            self._space_shortcut.setAutoRepeat(False)
            self._space_shortcut.activated.connect(self.play_pause)

            self._settings_shortcut = QShortcut(
                QKeySequence("Ctrl+,"), self)
            self._settings_shortcut.setContext(
                Qt.ShortcutContext.WindowShortcut)
            self._settings_shortcut.activated.connect(self._open_settings)

            self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            self.setFocus()

            self._refresh_timer = QTimer(self)
            self._refresh_timer.setInterval(REFRESH_MS)
            self._refresh_timer.timeout.connect(self._refresh)
            self._refresh_timer.start()

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(SAVE_DELAY_MS)
        self._save_timer.timeout.connect(self._save_settings)

        self._notice_timer = QTimer(self)
        self._notice_timer.setSingleShot(True)
        self._notice_timer.setInterval(NOTICE_MS)
        self._notice_timer.timeout.connect(self._clear_notice)

        if self._eng is not None:
            self._refresh()

    # ----------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        if self._eng is None:
            # Degraded mode: show what is wrong, keep the app usable.
            self.status_label = QLabel(
                f"engine unavailable: {self._engine_error}")
            self.status_label.setWordWrap(True)
            root.addWidget(self.status_label)
            return

        root.addLayout(self._build_header())
        root.addLayout(self._build_playback())
        root.addLayout(self._build_bands(), 1)

        self.status_label = QLabel()
        self.status_label.setObjectName("statusLabel")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.status_label)

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)

        self.settings_button = self._icon_button("settings", "Настройки")
        self.settings_button.clicked.connect(self._open_settings)
        row.addWidget(self.settings_button)

        self.preset_selector = ChevronComboBox()
        self.preset_selector.setFixedHeight(38)
        self.preset_selector.setMinimumWidth(150)
        self.preset_selector.setMaximumWidth(210)
        self.preset_selector.setToolTip(
            "Пресет: полосы эквалайзера и устройство вывода")
        self.preset_selector.currentIndexChanged.connect(
            self._on_preset_changed)
        row.addWidget(self.preset_selector)

        self.preset_save_button = self._icon_button("presetSave",
                                                   "Сохранить пресет")
        self.preset_save_button.clicked.connect(self._on_save_preset)
        row.addWidget(self.preset_save_button)

        self.preset_delete_button = self._icon_button("delete",
                                                     "Удалить пресет")
        self.preset_delete_button.clicked.connect(self._on_delete_preset)
        row.addWidget(self.preset_delete_button)

        row.addStretch(1)

        audio, _, _, _ = _mods()
        device_label = QLabel("Устройство:")
        device_label.setObjectName("fieldLabel")
        row.addWidget(device_label)

        self.device_selector = ChevronComboBox()
        self.device_selector.setFixedHeight(38)
        self.device_selector.setMinimumWidth(150)
        self.device_selector.setMaximumWidth(270)
        self.device_selector.setToolTip("Устройство вывода")
        self.device_selector.addItem(audio.DEFAULT_DEVICE_LABEL, None)
        for device in self._devices:
            self.device_selector.addItem(device.label, device.index)
        configured = audio.find_device(self._devices, self._eng.settings.device)
        self.device_selector.setCurrentIndex(
            0 if configured is None
            else self.device_selector.findData(configured.index))
        if configured is None and self._eng.settings.device is not None:
            self._show_notice(
                f"Устройство «{self._eng.settings.device}» не найдено,"
                " выбрано устройство по умолчанию.")
        self.device_selector.currentIndexChanged.connect(
            self._on_device_changed)
        row.addWidget(self.device_selector)

        self.autoplay_label = QLabel("Автовоспроизведение")
        self.autoplay_label.setObjectName("captionLabel")
        row.addWidget(self.autoplay_label)

        self.autoplay_button = ToggleSwitch()
        self.autoplay_button.setChecked(self._eng.settings.autoplay)
        self.autoplay_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.autoplay_button.setAccessibleName(
            self.autoplay_text(self._eng.settings.autoplay))
        self.autoplay_button.setToolTip(
            "Включено: во время воспроизведения новая частота звучит сразу.\n"
            "Выключено: частота переключается без звука.")
        self.autoplay_button.toggled.connect(self._on_autoplay_toggled)
        row.addWidget(self.autoplay_button)
        return row

    def _icon_button(self, icon_kind: str, tooltip: str) -> QPushButton:
        button = QPushButton()
        button.setObjectName("navButton")
        button.setFixedSize(38, 38)
        button.setIcon(self._icons[icon_kind])
        button.setIconSize(QSize(19, 19))
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    def _build_playback(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)

        self.play_button = QPushButton()
        self.play_button.setObjectName("playButton")
        self.play_button.setIcon(self._icons["start"])
        self.play_button.setIconSize(QSize(18, 18))
        self.play_button.setFixedSize(38, 38)
        self.play_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.play_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.play_button.setToolTip("Запустить (Пробел)")
        self.play_button.setAccessibleName("Запустить")
        self.play_button.clicked.connect(self.play_pause)
        row.addWidget(self.play_button)

        self.stop_button = self._icon_button("stop", "Остановить")
        self.stop_button.clicked.connect(self.stop)
        row.addWidget(self.stop_button)

        frequency_box = QVBoxLayout()
        frequency_box.setSpacing(0)
        self.frequency_label = QLabel()
        self.frequency_label.setTextFormat(Qt.TextFormat.RichText)
        self.frequency_label.setFixedWidth(FREQUENCY_BLOCK_WIDTH)
        self.frequency_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        frequency_box.addWidget(self.frequency_label)

        self.tone_counter_label = QLabel()
        self.tone_counter_label.setObjectName("captionLabel")
        self.tone_counter_label.setFixedWidth(FREQUENCY_BLOCK_WIDTH)
        self.tone_counter_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        frequency_box.addWidget(self.tone_counter_label)
        row.addLayout(frequency_box)

        row.addSpacing(8)
        self.tone_progress = QProgressBar()
        self.tone_progress.setRange(0, 100)
        self.tone_progress.setTextVisible(False)
        self.tone_progress.setFixedHeight(8)
        self.tone_progress.setSizePolicy(QSizePolicy.Policy.Expanding,
                                         QSizePolicy.Policy.Fixed)
        row.addWidget(self.tone_progress, 1)

        self.remaining_label = QLabel()
        mono_font = QFont(self._mono_family)
        mono_font.setPixelSize(14)
        mono_font.setWeight(QFont.Weight.DemiBold)
        self.remaining_label.setFont(mono_font)
        self.remaining_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.remaining_label.setMinimumWidth(116)
        row.addWidget(self.remaining_label)
        return row

    def _frequency_html(self, value: str, unit: str = "Гц") -> str:
        html = (
            f"<span style=\"font-family:'{self._mono_family}'; "
            f"font-size:{FREQUENCY_VALUE_PX}px; font-weight:600; "
            f"color:{COLOR_ACCENT};\">{value}</span>"
        )
        if unit:
            html += (
                f"<span style=\"font-family:'{self._sans_family}'; "
                f"font-size:{FREQUENCY_UNIT_PX}px; font-weight:500; "
                f"color:{COLOR_MUTED};\">&nbsp;{unit}</span>"
            )
        return html

    def _build_bands(self) -> QGridLayout:
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(4)

        grid.addWidget(self._build_master(), 0, 0)

        divider = QFrame()
        divider.setObjectName("divider")
        divider.setFixedWidth(1)
        grid.addWidget(divider, 0, 1, 2, 1)

        self._band_scroll = BandScrollArea()
        grid.addWidget(self._band_scroll, 0, 2)

        self._band_bar = QScrollBar(Qt.Orientation.Horizontal)
        self._band_bar.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        inner = self._band_scroll.horizontalScrollBar()
        if inner is not None:
            inner.rangeChanged.connect(self._sync_band_bar)
            inner.valueChanged.connect(self._band_bar.setValue)
            self._band_bar.valueChanged.connect(inner.setValue)
        grid.addWidget(self._band_bar, 1, 2)

        grid.setRowStretch(0, 1)
        grid.setColumnStretch(2, 1)
        return grid

    def _sync_band_bar(self) -> None:
        inner = self._band_scroll.horizontalScrollBar()
        if inner is None:
            return
        self._band_bar.setRange(inner.minimum(), inner.maximum())
        self._band_bar.setPageStep(inner.pageStep())
        self._band_bar.setSingleStep(inner.singleStep())
        self._band_bar.setValue(inner.value())

    def _build_master(self) -> QWidget:
        _, models, _, _ = _mods()
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(4, 0, 0, 0)
        row.setSpacing(RULER_SPACING)

        self.master_ruler = LevelRuler(models.MASTER_GAIN_SCALE)
        row.addWidget(self.master_ruler)

        frame = MasterFrame()
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(COLUMN_MARGIN, COLUMN_MARGIN,
                                  COLUMN_MARGIN, COLUMN_MARGIN)
        layout.setSpacing(COLUMN_SPACING)

        self.master_value_label = QLabel()
        self.master_value_label.setObjectName("bandValue")
        self.master_value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.master_value_label.setFixedHeight(COLUMN_VALUE_HEIGHT)
        layout.addWidget(self.master_value_label)

        self.master_slider = LevelSlider(models.MASTER_GAIN_SCALE)
        self.master_slider.setAccessibleName("Общая громкость")
        self.master_slider.setToolTip(
            "Общая громкость\n↑ ↓ — изменить; → — перейти к полосам")
        self.master_slider.valueChanged.connect(self._on_master_changed)
        self.master_slider.navigate_requested.connect(self._navigate)
        layout.addWidget(self.master_slider, 1)
        self.master_ruler.set_slider(self.master_slider)

        caption = QLabel("Громкость")
        caption.setObjectName("bandFrequency")
        caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        caption.setFixedHeight(COLUMN_FREQUENCY_HEIGHT)
        caption.setToolTip("Общая громкость")
        layout.addWidget(caption)

        placeholder = QWidget()
        placeholder.setFixedHeight(COLUMN_PLAY_SIZE)
        layout.addWidget(placeholder)

        row.addWidget(frame)
        self._master_frame = frame
        self._sync_master()
        return box

    # ------------------------------------------------------------ helpers
    @staticmethod
    def autoplay_text(enabled: bool) -> str:
        return ("Автовоспроизведение: "
                + ("включено" if enabled else "выключено"))

    def _current_index(self) -> int:
        return self._eng.player.tone_index if self._eng is not None else 0

    def _show_notice(self, text: str) -> None:
        self._notice = text
        if text:
            self._notice_timer.start()
        else:
            self._notice_timer.stop()

    def _clear_notice(self) -> None:
        if not self._notice:
            return
        self._notice = ""
        self._refresh()

    def _store(self, settings) -> None:
        """Record the changed settings object and schedule persistence."""
        self._eng.settings = settings
        self._save_timer.start()

    def _save_settings(self) -> None:
        if self._eng is None:
            return
        self._save_timer.stop()
        # A foreign edit wins: reload it instead of overwriting (original).
        content = self._read_settings_file()
        if content and content != self._settings_file_bytes:
            self._reload_settings()
            return
        try:
            from settings_store import save_settings  # type: ignore

            save_settings(self._settings_path, self._eng.settings)
        except Exception as exc:                    # noqa: BLE001
            self._save_error = str(exc)
        else:
            self._save_error = ""
            self._settings_file_bytes = self._read_settings_file()
            if (self._settings_path is not None
                    and self._settings_path not in
                    self._settings_watcher.files()):
                self._settings_watcher.addPath(str(self._settings_path))

    def _read_settings_file(self) -> bytes:
        try:
            return self._settings_path.read_bytes()
        except OSError:
            return b""

    def _on_settings_file_changed(self, path: str) -> None:
        if self._settings_path is None or Path(path) != self._settings_path:
            return
        files = self._settings_watcher.files()
        if Path(path) not in files:
            self._settings_watcher.addPath(str(self._settings_path))
        self._reload_timer.start()

    def _reload_settings(self) -> None:
        if self._eng is None or self._settings_path is None:
            return
        if self._settings_path not in self._settings_watcher.files():
            self._settings_watcher.addPath(str(self._settings_path))
        content = self._read_settings_file()
        if not content or content == self._settings_file_bytes:
            return
        self._save_timer.stop()
        _, _, _, settings_store = _mods()
        try:
            settings = settings_store.load_settings(self._settings_path)
        except Exception as exc:                    # noqa: BLE001
            self._show_notice(f"Не удалось перечитать настройки: {exc}")
            self._refresh()
            return
        self._settings_file_bytes = content
        if settings == self._eng.settings:
            return
        self._apply_settings(
            settings,
            notice="Настройки перечитаны из файла.",
            persist=False)

    def flush_save(self) -> None:
        """Persist pending edits at app exit."""
        if self._eng is not None and self._save_timer.isActive():
            self._save_settings()

    # ------------------------------------------------------------ actions
    def play_pause(self) -> None:
        if self._eng is None:
            return
        _, models, _, _ = _mods()
        state = self._eng.player.state
        if state is models.PlayerState.PLAYING:
            self._eng.player.pause()
            self._refresh()
        elif state is models.PlayerState.PAUSED:
            self._eng.player.resume()
            self._refresh()
        else:
            index = (0 if state is models.PlayerState.FINISHED
                     else self._get_focused_band_index())
            self._start_playback(index)

    def stop(self) -> None:
        if self._eng is None:
            return
        self._eng.player.stop()
        self._finishing_handled = False
        self._refresh()

    def _start_playback(self, index: int) -> None:
        try:
            self._eng.player.start(index)
        except Exception as exc:                    # noqa: BLE001
            QMessageBox.critical(self, "Ошибка воспроизведения", str(exc))
            return
        self._finishing_handled = False
        self._refresh()

    def _on_activate_band(self, index: int) -> None:
        _, models, _, _ = _mods()
        state = self._eng.player.state
        if state is models.PlayerState.PLAYING:
            self._start_playback(index)
            return
        self._eng.player.select(index)
        self._finishing_handled = False
        self._refresh()

    def _on_band_level(self, index: int, level_db: float) -> None:
        if self._eng is None:
            return
        self._eng.player.set_level_at(index, level_db)

    def _on_band_select(self, index: int) -> None:
        self._focused = index
        self._focus_band(index)

    def _focus_band(self, index: int) -> None:
        if self._strip is not None and index < self._strip.count:
            self._focused = index
            self._strip.column(index).slider.setFocus()
            if self._band_scroll is not None:
                self._band_scroll.ensureWidgetVisible(
                    self._strip.column(index), 48, 0)

    def _on_band_play(self, index: int) -> None:
        self._focus_band(index)
        _, models, _, _ = _mods()
        state = self._eng.player.state
        if index == self._eng.player.tone_index:
            if state is models.PlayerState.PLAYING:
                self._eng.player.pause()
                self._refresh()
                return
            if state is models.PlayerState.PAUSED:
                self._eng.player.resume()
                self._refresh()
                return
        self._start_playback(index)

    def _on_master_changed(self, position: int) -> None:
        _, models, _, _ = _mods()
        gain_db = models.MASTER_GAIN_SCALE.at_position(position)
        self._eng.player.set_master_db(models.MASTER_BASE_DB + gain_db)
        self._store(replace(self._eng.settings, master_gain_db=gain_db))
        self._refresh()

    def _on_device_changed(self, index: int) -> None:
        audio, _, _, _ = _mods()
        data = self.device_selector.itemData(index)
        device = next((item for item in self._devices
                       if item.index == data), None)
        try:
            self._eng.player.set_device(
                device.index if device is not None else None)
        except Exception:                           # noqa: BLE001 -- playing
            return
        self._show_notice("")
        self._store(replace(
            self._eng.settings,
            device=device.label if device is not None else None))
        self._refresh()

    def _on_autoplay_toggled(self, enabled: bool) -> None:
        if self._eng is None:
            return
        self._eng.player.set_autoplay(enabled)
        self.autoplay_button.setAccessibleName(self.autoplay_text(enabled))
        self._store(replace(self._eng.settings, autoplay=enabled))

    def _open_settings(self) -> None:
        if self._eng is None:
            return
        dialog = SettingsDialog(self._eng.settings, self)
        dialog.setStyleSheet(self.styleSheet())
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_settings = dialog.settings()
            active_name = self._eng.settings.active_preset
            if active_name is not None:
                new_presets = tuple(
                    replace(p, bands=new_settings.bands)
                    if p.name.casefold() == active_name.casefold() else p
                    for p in new_settings.presets)
                new_settings = replace(new_settings, presets=new_presets)
            else:
                new_settings = replace(new_settings,
                                       default_bands=new_settings.bands)
            self._apply_settings(new_settings)

    def _apply_settings(self, settings, *, notice: str = "",
                        persist: bool = True) -> None:
        """Replace the settings like the original _apply_settings."""
        toneplayer.apply_settings(settings)
        self._eng.settings = settings
        audio, _, _, _ = _mods()
        configured = audio.find_device(self._devices, settings.device)
        self._eng.player.set_device(
            configured.index if configured is not None else None)
        text = notice
        if configured is None and settings.device is not None:
            text = (f"Устройство «{settings.device}» не найдено, "
                    "выбрано устройство по умолчанию.")
        self._show_notice(text)
        self._sync_device_selector()
        self._sync_autoplay()
        self._sync_master()
        self._rebuild_bands()
        self._refresh_presets()
        if persist:
            self._store(settings)
        self._refresh()

    def _sync_device_selector(self) -> None:
        target = self._eng.player.device
        self.device_selector.blockSignals(True)
        index = (0 if target is None
                 else self.device_selector.findData(target))
        self.device_selector.setCurrentIndex(max(index, 0))
        self.device_selector.blockSignals(False)

    def _sync_autoplay(self) -> None:
        self.autoplay_button.blockSignals(True)
        self.autoplay_button.setChecked(self._eng.settings.autoplay)
        self.autoplay_button.blockSignals(False)
        self.autoplay_button.setAccessibleName(
            self.autoplay_text(self._eng.settings.autoplay))

    def _sync_master(self) -> None:
        _, models, _, _ = _mods()
        position = models.MASTER_GAIN_SCALE.position(
            self._eng.settings.master_gain_db)
        self.master_slider.blockSignals(True)
        self.master_slider.setValue(position)
        self.master_slider.blockSignals(False)
        self.master_value_label.setText(_fmt_level(
            self._eng.settings.master_gain_db))

    # ------------------------------------------------------------- presets
    def _refresh_presets(self) -> None:
        self.preset_selector.blockSignals(True)
        self.preset_selector.clear()
        self.preset_selector.addItem("По умолчанию", None)
        for preset in self._eng.settings.presets:
            self.preset_selector.addItem(preset.name, preset.name)
        if self._eng.settings.active_preset is not None:
            index = self.preset_selector.findData(
                self._eng.settings.active_preset)
            if index >= 0:
                self.preset_selector.setCurrentIndex(index)
        self.preset_selector.blockSignals(False)
        is_user_preset = self._eng.settings.active_preset is not None
        self.preset_delete_button.setEnabled(is_user_preset)
        self.settings_button.setEnabled(True)
        self.settings_button.setToolTip("Настройки")

    def _on_preset_changed(self, index: int) -> None:
        if self._eng is None:
            return
        _, models, _, _ = _mods()
        import presets  # type: ignore[import-not-found]

        data = self.preset_selector.itemData(index)
        if data is None:
            self._eng.player.stop()
            default_bands = (
                self._eng.settings.default_bands
                if self._eng.settings.default_bands
                else tuple(models.Band(b.frequency_hz, 0.0)
                           for b in self._eng.settings.bands))
            settings = replace(self._eng.settings, bands=default_bands,
                               active_preset=None)
            self._eng.settings = settings
            self._finishing_handled = False
            toneplayer.apply_settings(settings)
            self._focused = 0
            self._rebuild_bands()
            self._sync_device_selector()
            self._refresh_presets()
            self._store(settings)
            self._refresh()
            return

        name = str(data)
        available = {device.label for device in self._devices}
        try:
            application = presets.apply_preset(self._eng.settings, name,
                                               available)
        except presets.PresetError as error:
            QMessageBox.warning(self, "Пресет не применён", str(error))
            self._refresh_presets()
            return
        notice = ""
        if application.missing_device is not None:
            notice = (f"Устройство «{application.missing_device}» из пресета "
                      "не найдено, выбрано устройство по умолчанию.")
        self._apply_settings(application.settings, notice=notice)

    def _ask_preset_name(self, default: str) -> str | None:
        """The original preset-name dialog (QDialog + QLineEdit)."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Сохранить пресет")
        dialog.setMinimumWidth(400)
        dialog.setStyleSheet(self.styleSheet())

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        layout.addWidget(QLabel("Имя пресета:"))

        edit = QLineEdit(default)
        edit.setFixedHeight(38)
        edit.selectAll()
        layout.addWidget(edit)

        buttons = QDialogButtonBox()
        save = buttons.addButton("Сохранить",
                                 QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton("Отмена", QDialogButtonBox.ButtonRole.RejectRole)
        if save is not None:
            save.setDefault(True)
            save.setObjectName("playButton")
        buttons.setFixedHeight(38)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        edit.returnPressed.connect(dialog.accept)
        layout.addWidget(buttons)

        edit.setFocus()
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return edit.text()

    def _on_save_preset(self) -> None:
        if self._eng is None:
            return
        import presets  # type: ignore[import-not-found]

        default = self._eng.settings.active_preset or "Пресет"
        name = self._ask_preset_name(default)
        if name is None:
            return
        try:
            existing = presets.find_preset(self._eng.settings, name.strip())
            overwrite = False
            if existing is not None:
                answer = QMessageBox.question(
                    self, "Пресет уже существует",
                    f"Заменить пресет «{existing.name}»?",
                    QMessageBox.StandardButton.Yes
                    | QMessageBox.StandardButton.No)
                if answer != QMessageBox.StandardButton.Yes:
                    return
                overwrite = True
            current_bands = tuple(
                type(band)(band.frequency_hz, self._eng.player.level_at(i))
                for i, band in enumerate(self._eng.settings.bands))
            settings = presets.save_preset(
                self._eng.settings, name, bands=current_bands,
                overwrite=overwrite)
        except presets.PresetError as error:
            QMessageBox.warning(self, "Пресет не сохранён", str(error))
            return
        self._eng.settings = settings
        self._show_notice(f"Пресет «{settings.active_preset}» сохранён.")
        self._store(settings)
        self._refresh_presets()
        self._refresh()

    def _on_delete_preset(self) -> None:
        if self._eng is None:
            return
        import presets  # type: ignore[import-not-found]

        name = self._eng.settings.active_preset
        if name is None:
            return
        answer = QMessageBox.question(
            self, "Удалить пресет", f"Удалить пресет «{name}»?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            settings = presets.delete_preset(self._eng.settings, name)
        except presets.PresetError as error:
            QMessageBox.warning(self, "Пресет не удалён", str(error))
            return
        self._apply_settings(settings)

    # ------------------------------------------------------------- bands
    def _rebuild_bands(self) -> None:
        if self._eng is None:
            return
        focused_index: int | None = None
        focus = QApplication.focusWidget()
        if focus is not None and self._strip is not None:
            for index in range(self._strip.count):
                if focus is self._strip.column(index).slider:
                    focused_index = index
                    break
        if self._strip is not None:
            self._strip.deleteLater()
        strip = BandStrip(
            self._eng.settings.level_scale,
            self._icons,
            on_level=self._on_band_level,
            on_play=self._on_band_play,
            on_select=self._on_band_select,
            on_activate=self._on_activate_band,
            on_navigate=self._navigate,
            on_scroll=self._scroll_bands)
        strip.set_bands(self._eng.settings.bands,
                        self._eng.settings.level_scale)
        self._strip = strip
        if self._band_scroll is not None:
            self._band_scroll.setWidget(strip)
        self._columns = strip._columns          # alias for tests/tooling
        self._last_band_index = -1
        tail = len(self._eng.settings.bands) - 1
        if focused_index is not None:
            index = min(focused_index, tail)
        else:
            index = min(self._focused, tail)
        self._focused = index
        strip.column(index).slider.setFocus()
        self._sync_band_bar()

    def _scroll_bands(self, delta: int) -> None:
        bar = self._band_scroll.horizontalScrollBar()
        if bar is not None:
            bar.setValue(bar.value() - delta)

    def _get_focused_band_index(self) -> int:
        if self._strip is not None:
            focus = QApplication.focusWidget()
            for i in range(self._strip.count):
                if focus is self._strip.column(i).slider:
                    self._focused = i
                    return i
        tail = (len(self._eng.settings.bands) - 1
                if self._eng is not None else 0)
        return min(max(self._focused, 0), max(tail, 0))

    def _is_any_band_slider_focused(self) -> bool:
        if self._strip is not None:
            focus = QApplication.focusWidget()
            for i in range(self._strip.count):
                if focus is self._strip.column(i).slider:
                    return True
        return False

    # ------------------------------------------------------ keyboard
    def keyPressEvent(self, ev) -> None:                 # noqa: N802
        """Original keys: arrows navigate, Space plays/pauses."""
        if (ev is not None and self._eng is not None
                and ev.modifiers() == Qt.KeyboardModifier.NoModifier):
            key = ev.key()
            if key == Qt.Key.Key_Left:
                self._navigate(-1)
                ev.accept()
                return
            if key == Qt.Key.Key_Right:
                self._navigate(1)
                ev.accept()
                return
            if key == Qt.Key.Key_Up:
                self._nudge_active_band(1)
                ev.accept()
                return
            if key == Qt.Key.Key_Down:
                self._nudge_active_band(-1)
                ev.accept()
                return
            if key == Qt.Key.Key_Space:
                self.play_pause()
                ev.accept()
                return
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._on_activate_current()
                ev.accept()
                return
        super().keyPressEvent(ev)

    def _navigate(self, offset: int) -> None:
        """Move the slider focus (from master Right = to the bands)."""
        if self._eng is None:
            return
        if self.master_slider.hasFocus():
            if offset > 0:
                self._focus_band(self._focused)
            return
        current = self._get_focused_band_index()
        if offset < 0 and current == 0:
            focus = QApplication.focusWidget()
            first_slider = (self._strip.column(0).slider
                            if self._strip is not None and self._strip.count
                            else None)
            if focus is self or focus is first_slider:
                self.master_slider.setFocus()
                return
        tail = len(self._eng.settings.bands) - 1
        new_index = min(max(current + offset, 0), tail)
        self._focused = new_index
        self._focus_band(new_index)

    def _nudge_active_band(self, direction: int) -> None:
        """Up/Down: nudge the focused band level by one step."""
        if self._eng is None:
            return
        index = self._get_focused_band_index()
        scale = self._eng.settings.level_scale
        current = self._eng.player.level_at(index)
        level = scale.clamp(current + direction * scale.step_db)
        if level != current:
            self._on_band_level(index, level)
            if self._strip is not None and index < self._strip.count:
                self._strip.column(index).set_level(level)

    def _on_activate_current(self) -> None:
        if self._eng is None or self.master_slider.hasFocus():
            return
        self._on_activate_band(self._get_focused_band_index())

    # ------------------------------------------------------------ refresh
    def _refresh(self) -> None:
        if self._eng is None:
            self.status_label.setText(
                f"engine unavailable: {self._engine_error}")
            return
        _, models, ui_text, _ = _mods()
        player = self._eng.player
        state = player.state
        progress = player.progress()

        if state is models.PlayerState.FINISHED and not self._finishing_handled:
            self._finishing_handled = True
            player.finish()
            state = player.state
            progress = player.progress()

        self.frequency_label.setText(self._frequency_html(
            ui_text.format_frequency_value(player.current_frequency)))
        self.tone_counter_label.setText(
            f"Тон {progress.tone_index + 1} из {self._eng.config.tone_count}")
        self.remaining_label.setText(
            f"осталось {ui_text.format_duration(progress.tone_remaining)}")
        self.tone_progress.setValue(
            int(round(progress.tone_fraction * 100)))

        busy = state in (models.PlayerState.PLAYING,
                         models.PlayerState.PAUSED)
        self.stop_button.setEnabled(busy)
        self.device_selector.setEnabled(not busy)

        mode = ("pause" if state is models.PlayerState.PLAYING else
                "resume" if state is models.PlayerState.PAUSED else "start")
        if mode != self._play_button_mode:
            self._play_button_mode = mode
            label, icon_kind = PLAY_BUTTON_LOOK[mode]
            self.play_button.setIcon(self._icons[icon_kind])
            self.play_button.setToolTip(f"{label} (Пробел)")
            self.play_button.setAccessibleName(label)

        playing = state is models.PlayerState.PLAYING
        if self._strip is not None:
            self._strip.set_current(progress.tone_index, playing)
            if progress.tone_index != self._last_band_index:
                self._last_band_index = progress.tone_index
                focused_idx = self._get_focused_band_index()
                if (focused_idx == progress.tone_index
                        or not self._is_any_band_slider_focused()):
                    if progress.tone_index < self._strip.count:
                        self._band_scroll.ensureWidgetVisible(
                            self._strip.column(progress.tone_index), 48, 0)

        self.master_value_label.setText(_fmt_level(
            player.master_db - models.MASTER_BASE_DB))

        # Rulers track slider geometry live: repaint them every tick so a
        # just-settled layout never leaves a stale mark (stale-label class).
        if self._strip is not None:
            self._strip.ruler.update()
        self.master_ruler.update()

        status = player.last_status or self._save_error or self._notice
        self.status_label.setText(status)
        self.status_label.setVisible(bool(status))
```

```src/skm/transport.py
"""Byte transports for the SKM link.

Transport is deliberately the thinnest possible interface (the app's TOTAL
layer is only FT_Open/description-discovery + generic D2XX read/write):
  open() / close() / write(data) / read(max, timeout) / queue() / baud setter.
"""

from __future__ import annotations

import ctypes
import time
from typing import Protocol

from .constants import BAUD


class Transport(Protocol):
    def open(self) -> None: ...
    def close(self) -> None: ...
    def write(self, data: bytes) -> None: ...
    def read(self, want: int, timeout: float = 1.0) -> bytes: ...
    def queue(self) -> int: ...
    def set_baud(self, baud: int) -> None: ...


class LoopbackTransport:
    """Pair with SimulatorTransport not needed: `SimulatedTransport`
    talks to the in-process simulator directly. This class is for tests."""

    def __init__(self) -> None:
        self._rx = bytearray()

    def inject(self, data: bytes) -> None:
        self._rx.extend(data)

    def open(self) -> None:
        pass

    def close(self) -> None:
        pass

    def write(self, data: bytes) -> None:
        pass

    def read(self, want: int, timeout: float = 1.0) -> bytes:
        out = bytes(self._rx[:want])
        del self._rx[:want]
        return out

    def queue(self) -> int:
        return len(self._rx)

    def set_baud(self, baud: int) -> None:
        pass


class D2XXTransport:
    """FTDI D2XX via ctypes (ftd2xx.dll), matching the app's imports
    (FT_Open is by device *number*; discovery uses FT_ListDevices with
    descriptions — see FUN_00570b84). Windows-only."""

    FT_OK = 0
    FT_LIST_BY_INDEX = 0x80000000
    FT_LIST_ALL = 0x80000001
    OPEN_BY_DESCRIPTION = 2
    OPEN_BY_SERIAL = 3

    def __init__(self, description: str = "", serial: str = "12345678") -> None:
        self.description = description
        self.serial = serial
        self.baud = BAUD
        self._h = None
        self._dll = None

    def _ft(self):
        if self._dll is None:
            self._dll = ctypes.WinDLL("ftd2xx.dll")
        return self._dll

    def list_devices(self) -> list[tuple[str, str, str]]:
        """Returns [(desc, serial, port)] — approximates FT_ListDevices."""
        d = self._ft()
        n = ctypes.c_ulong()
        st = d.FT_CreateDeviceInfoList(ctypes.byref(n))
        if st != self.FT_OK:
            raise OSError(f"FT_CreateDeviceInfoList {st}")
        flagged = ctypes.c_ulong(self.FT_LIST_ALL)
        locid = (ctypes.c_ulong * 256)()
        devtype = (ctypes.c_ulong * 256)()
        devids = (ctypes.c_ulong * 256)()
        desc = (ctypes.c_wchar_p * 256)()
        serials = (ctypes.c_wchar_p * 256)()
        ret = []
        if d.FT_GetDeviceInfoList(flagged, ctypes.byref(n), locid, devtype,
                                  devids, desc, serials) == self.FT_OK:
            for i in range(n.value):
                ret.append((desc[i], serials[i], str(locid[i])))
        return ret

    def open(self) -> None:
        d = self._ft()
        h = ctypes.c_void_p()
        code = None
        if self.description:
            code = d.FT_OpenEx(self.description.encode("utf-16-le") or
                               self.description, self.OPEN_BY_DESCRIPTION,
                               ctypes.byref(h))
        if code != self.FT_OK and self.serial:
            code = d.FT_OpenEx(self.serial.encode(), self.OPEN_BY_SERIAL,
                               ctypes.byref(h))
        if code != self.FT_OK:
            raise OSError(f"FT_OpenEx failed {code}")
        self._h = h
        d.FT_SetBaudRate(h, self.baud)
        # 8N1 like the app's FT_SetDataCharacteristics(8,0,0)
        d.FT_SetDataCharacteristics(h, 8, 0, 0)
        d.FT_SetFlowControl(h, 0, 0, 0)  # none

    def close(self) -> None:
        if self._h is not None:
            self._ft().FT_Close(self._h)
            self._h = None

    def write(self, data: bytes) -> None:
        got = ctypes.c_ulong()
        if self._h is None:
            raise OSError("write on closed transport")
        d = self._ft()
        st = d.FT_Write(self._h, data, len(data), ctypes.byref(got))
        if st != self.FT_OK:
            raise OSError(f"FT_Write {st}")
        if got.value != len(data):
            raise OSError("short write")

    def queue(self) -> int:
        rx = ctypes.c_ulong()
        if self._h is None:
            return -1
        if self._ft().FT_GetQueueStatus(self._h, ctypes.byref(rx)) != self.FT_OK:
            return -1
        return rx.value

    def read(self, want: int, timeout: float = 1.0) -> bytes:
        if self._h is None:
            raise OSError("read on closed transport")
        d = self._ft()
        got = ctypes.c_ulong()
        out = bytearray()
        deadline = time.monotonic() + timeout
        while len(out) < want and time.monotonic() < deadline:
            rx = self.queue()
            if rx <= 0:
                time.sleep(0.001)
                continue
            buf = (ctypes.c_ubyte * min(rx, want - len(out)))()
            st = d.FT_Read(self._h, buf, len(buf), ctypes.byref(got))
            if st != self.FT_OK:
                raise OSError(f"FT_Read {st}")
            out.extend(buf[:got.value])
        return bytes(out)

    def set_baud(self, baud: int) -> None:
        self.baud = baud
        if self._h is not None:
            self._ft().FT_SetBaudRate(self._h, baud)
```

