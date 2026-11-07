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
- `src/main.py` / `src/gui.py` — the measurement GUI (spectrum +
  oscillogram + FREQUENCY/LEVEL readouts), all device I/O in a QThread,
- `src/cli.py` — probe/speaker/sample/gen/measure CLI commands,
- `src/gui_smoke.py` — headless smoke test (connect → measure → PNG grabs),
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
- GUI auto-measure (`Auto-measure`) re-captures at a settable interval, which
  makes spectrum/oscillogram readouts live.

## TonePlayer integration (stub)

Two stub buttons in the "TonePlayer (stub)" panel drive the companion
tone-generator app (../tone-player); eventually these actions will be
implemented natively inside SKM.

- "Open TonePlayer" launches the TonePlayer executable. Its
  `settings.json` MUST sit next to the executable (TonePlayer is started
  from the same folder as SKM in the deployed layout; in dev the sibling
  repository `../tone-player/dist/` is used).
- "Play frequencies" / "Stop playback" toggles playback via the remote
  `msg` CLI channel: the TonePlayer binary supports `TonePlayer msg play`,
  `msg stop`, `msg status`, etc. — one JSON-line reply from the running
  instance. Errors (e.g. TonePlayer not running) surface in the status bar.
- Path resolution order: `SKM_TONE_PLAYER` env override, then the
  executable next to the frozen SKM app, then the dev sibling repo.

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
  the full file span (32000 Hz); the oscillogram tab is disabled since the
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
