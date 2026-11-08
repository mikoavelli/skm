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
    win.on_connect()                      # combo index 0 = simulator
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
