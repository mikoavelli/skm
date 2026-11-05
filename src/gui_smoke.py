"""Headless smoke test for the GUI: connect simulator, run one measurement,
grab the window to a PNG.  Run:  venv python -m skmapp.gui_smoke out.png
"""
from __future__ import annotations

import sys
import tempfile
import time

from PySide6.QtWidgets import QApplication

from gui import MainWindow


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
    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.02)
        if win.lb_freq.text() != "0 Гц":
            break

    # exercise a couple of controls so state is visible
    win.on_gen_on()
    win.btn_ch_y.setChecked(True)
    win.on_channels()
    end = time.monotonic() + 0.5
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.02)

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
