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
