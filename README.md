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
