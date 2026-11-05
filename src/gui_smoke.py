"""Headless smoke test for the GUI: connect simulator, run one measurement,
grab the window to a PNG.  Run:  venv python -m skmapp.gui_smoke out.png
"""
from __future__ import annotations

import sys
import tempfile
import time

from PySide6.QtWidgets import QApplication

from gui import MainWindow


def _wait_label(app: QApplication, win, text: str, s: float) -> bool:
    """Pump events until the FREQ label shows `text` (or timeout)."""
    deadline = time.monotonic() + s
    while time.monotonic() < deadline:
        app.processEvents()
        if win.lb_freq.text() == text:
            return True
        time.sleep(0.02)
    return False


def main() -> int:
    out = sys.argv[1] if len(sys.argv) > 1 else \
        f"{tempfile.gettempdir()}/skm_gui.png"
    app = QApplication([])
    app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    win.resize(1180, 760)

    win.on_connect()                 # queue simulator connect
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.02)

    win.thread.request_measure()
    if not _wait_label(app, win, "1000 Гц", 10.0):
        print("FAIL: no 1000 Hz peak after first measure", file=sys.stderr)
        return 1

    # exercise a couple of controls so state is visible
    win.btn_ch_y.setChecked(True)
    win.on_channels()

    # scene retune through the generator: 'H' rewrites the 'N' stream, the
    # next capture must peak at the new exact-division frequency. 5120 Hz
    # = stream_fs / 10 -> integer divider, no quantization error.
    win.sp_gen.setValue(5120)
    win.on_gen_on()
    if not _wait_label(app, win, "5120 Гц", 15.0):
        print("FAIL: generator did not retune the scene to 5120 Hz",
              file=sys.stderr)
        return 1
    win.on_gen_stop()

    pix = win.grab()
    pix.save(out)
    print("saved", out, pix.width(), "x", pix.height())

    win.tabs.setCurrentIndex(1)      # oscillogram tab
    end = time.monotonic() + 0.3
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.02)
    out2 = out.replace(".png", "_time.png")
    win.grab().save(out2)
    print("saved", out2)

    print("freq label:", win.lb_freq.text(), "level:", win.lb_level.text())
    print("state:", win.lbl_state.text())
    win.thread.stop()
    win.thread.wait(2000)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
