# skm — СКМ-2ПО communication/measurement mechanism (standalone app)

A standalone application that replicates the communication and measurement
mechanism of СКМ devices, extracted by reverse engineering the СКМ2ПО
(`CKM2PO.exe`) binary. Python core package + PySide6 GUI; works without real
hardware via a byte-level SKM-23 simulator built from the RE'd protocol.

Package layout (uv, `src/`):

- `src/skm/constants.py` — protocol constants (commands, sentinel, retry
  counts) with the Ghidra evidence references,
- `src/skm/transport.py` — byte transport ABC + FTDI D2XX transport (ctypes,
  for the Win10 VM / real hardware) + loopback transport for tests,
- `src/skm/simulator.py` — byte-level fake СКМ device (CKM-23 behaviour RE'd
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
  oscillogram + ЧАСТОТА/УРОВЕНЬ readouts), all device I/O in a QThread,
- `src/cli.py` — probe/speaker/sample/gen/measure CLI commands,
- `src/gui_smoke.py` — headless smoke test (connect → measure → PNG grabs),
- `SKM.spec` — PyInstaller build (Qt module/plugin pruning, numpy kept).

Evidence: the reverse-engineering base lives in the sibling `CKM2PO` project
repo — `analysis/meas/defns/FUN_*.c` (5858 decompiled bodies) and the "SKM
protocol total layer — extracted" section in `analysis/notes.md`.

## Build / run

```sh
uv sync && uv sync --group build   # runtime + build toolchain
uv run python src/cli.py probe     # CLI against the simulator
uv run python src/main.py          # GUI (needs display)
QT_QPA_PLATFORM=offscreen uv run python src/gui_smoke.py out.png   # headless test
uv run --group build pyinstaller SKM.spec   # single-file dist/SKM
SKM_ONEDIR=1 uv run --group build pyinstaller SKM.spec --noconfirm  # dist/SKM/ dir
```

Real СКМ hardware: Windows + `ftd2xx.dll` in PATH, connect via «FTDI: CKM 23v1»
in the GUI (D2XX discovery by description, as FUN_00570b84 does).
