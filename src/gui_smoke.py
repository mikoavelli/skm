"""Headless smoke test for the GUI.

Exercises the simulator scene roundtrip (generate retune), then the
file-input display modes (noise / signal + noise), grabbing PNGs.
Run:  uv run python src/gui_smoke.py out.png
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
from PySide6.QtWidgets import QApplication

from gui import MainWindow
from skm import toneplayer


def _wait_label(app: QApplication, win: MainWindow, text: str,
                seconds: float) -> bool:
    """Pump events until the FREQUENCY label shows `text` (or timeout)."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        if win.lb_freq.text() == text:
            return True
        time.sleep(0.02)
    return False


def _expected_label(app: QApplication, win: MainWindow, kind: str) -> str:
    """Peak caption computed from the parsed file (data-driven assert)."""
    sf = win.thread.files[kind]
    i = int(np.argmax(sf.volts))
    return f"{sf.freqs_hz[i]:.0f} Hz"


def _wait_status(app: QApplication, win: MainWindow, prefix: str,
                 seconds: float) -> bool:
    """Pump events until the status bar message starts with `prefix`."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        if win.statusBar().currentMessage().startswith(prefix):
            return True
        time.sleep(0.02)
    return False


def main() -> int:
    out = sys.argv[1] if len(sys.argv) > 1 else \
        f"{tempfile.gettempdir()}/skm_gui.png"
    # TonePlayer settings copy: smoke must not touch the real dist file
    tp_dir = Path(tempfile.mkdtemp(prefix="skm_tp_"))
    shutil.copy(toneplayer.settings_path(), tp_dir / "settings.json")
    os.environ["SKM_TONE_SETTINGS"] = str(tp_dir / "settings.json")
    app = QApplication([])
    app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    win.resize(1180, 760)

    # 1) simulator: handshake + measurement + generator scene retune
    win.on_connect()                      # combo index 0 = SKM-23 Simulator
    win.thread.request_measure()
    if not _wait_label(app, win, "1000 Hz", 10.0):
        print("FAIL: no 1000 Hz peak after first measure", file=sys.stderr)
        return 1
    win.btn_ch_y.setChecked(True)
    win.on_channels()
    win.sp_gen.setValue(5120)
    win.on_gen_on()                       # ON also re-measures
    if not _wait_label(app, win, "5120 Hz", 15.0):
        print("FAIL: generator did not retune the scene to 5120 Hz",
              file=sys.stderr)
        return 1

    spectra_png = out.replace(".png", "_sim.png")
    win.grab().save(spectra_png)
    print("saved", spectra_png)

    win.tabs.setCurrentIndex(1)           # oscillogram tab (sim connected)
    end = time.monotonic() + 0.3
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.02)
    osc_png = out.replace(".png", "_time.png")
    win.grab().save(osc_png)
    print("saved", osc_png)

    # 2) file input: connect the test-data pair, both display modes
    win.cb_conn.setCurrentIndex(2)
    win.on_connect()
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline and not win.grp_files.isEnabled():
        app.processEvents()
        time.sleep(0.02)
    if not _wait_label(app, win, _expected_label(app, win, "noise"), 5.0):
        print("FAIL: noise file spectrum not shown", file=sys.stderr)
        return 1
    noise_level = win.lb_level.text()

    win.tabs.setCurrentIndex(0)
    file_png = out
    win.grab().save(file_png)
    print("saved", file_png)

    win.rb_signal.setChecked(True)        # switch to signal + noise mode
    if not _wait_label(app, win, _expected_label(app, win, "signal_noise"),
                       5.0):
        print("FAIL: signal+noise file spectrum not shown", file=sys.stderr)
        return 1
    sn_level = win.lb_level.text()
    print(f"noise mode level: {noise_level}, signal+noise level: {sn_level}")
    win.rb_noise.setChecked(True)

    # 3) TonePlayer tab: full panel on the in-process engine
    win.tabs.setCurrentIndex(2)
    print("tone-player settings:", toneplayer.settings_path())
    panel = win.tp_panel
    band = panel._band_rows[0]
    print("bands:", len(panel._band_rows))
    band.slider.setValue(band.slider.maximum())          # level -> +10 dB
    deadline = time.monotonic() + 0.3
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.02)
    level = panel._eng.player.level_at(0)    # TonePlayer keeps levels runtime-only
    if abs(level - 10.0) > 1e-9:
        print(f"FAIL: band level edit did not reach the engine ({level})",
              file=sys.stderr)
        return 1
    print("band level applied:", level)
    panel.play_button.click()                            # transport Play
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline and \
            panel.freq_label.text() in ("", "-"):
        app.processEvents()
        time.sleep(0.1)
    print("freq label:", panel.freq_label.text(),
          "| counter:", panel.counter_label.text())
    panel.stop_button.click()
    tp_png = out.replace(".png", "_tp.png")
    win.grab().save(tp_png)
    print("saved", tp_png)

    print("state:", win.lbl_state.text())
    win.thread.stop()
    win.thread.wait(2000)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
