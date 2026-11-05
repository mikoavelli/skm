"""Standalone SKM measurement GUI (PySide6 + pyqtgraph).

Mirrors the CKM2PO measurement screen (TMF) on top of the `skm` core:
  - connect: in-process СКМ simulator, or FTDI D2XX hardware on Windows;
  - spectrum (10 Hz..20 kHz) + oscillogram of the 65536-sample 'N'/'S'
    capture, live-refreshed at a settable interval (worker thread);
  - ИНФОРМАЦИЯ readouts ЧАСТОТА / УРОВЕНЬ (peak freq / band level);
  - source select (I..'E'), channels X/Y, range R0..2, speaker 'U'/'V',
    generator 'H' (frequency + start/stop), handshake keep-alive.

Threading: all device I/O happens in a LinkThread; the UI thread never
touches the transport (the RE'd layer is synchronous and poll-heavy).
Results arrive as numpy arrays via signals; captions update from them.

Run:  python3 -m skmapp.gui
"""
from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QThread, Signal, Slot
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from skm import D2XXTransport, PairTransport, Simulator, SkmDevice, Spectrum

FMIN, FMAX = 10.0, 20000.0          # СКМ-2ПО spectrum span (DFM band panel)
DEFAULT_FS = 51200.0               # simulator stream fs; for HW settable


# --------------------------------------------------------------- worker

class MeasurementResult:
    __slots__ = ("samples", "spec", "ok", "err")

    def __init__(self, samples, spec: Spectrum | None, ok: bool,
                 err: str = "") -> None:
        self.samples = samples
        self.spec = spec
        self.ok = ok
        self.err = err


class LinkThread(QThread):
    """Owns the device; executes commands posted by the UI, and runs the
    optional continuous capture/measure loop."""

    state_changed = Signal(str)
    result_ready = Signal(object)          # MeasurementResult
    connected = Signal(bool)

    def __init__(self) -> None:
        super().__init__()
        self.dev: SkmDevice | None = None
        self._queue: list[tuple[str, object]] = []
        self.streaming = False
        self.oneshot = False
        self.interval_s = 2.0
        self.fs = DEFAULT_FS

    # called from the UI thread ----------------------------------------
    def submit(self, name: str, fn) -> None:
        self._queue.append(("cmd", (name, fn)))

    def connect_simulator(self) -> None:
        self._queue.append(("connect", ("sim", "")))

    def connect_d2xx(self, description: str = "CKM 23v1") -> None:
        self._queue.append(("connect", ("d2xx", description)))

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
                    elif kind == "disconnect":
                        self._disconnect()
                    elif kind == "cmd" and self.dev is not None:
                        arg[1](self.dev)
                except Exception as exc:                    # noqa: BLE001
                    self.state_changed.emit(f"Ошибка: {exc}")
            if self.dev is not None and (self.streaming or self.oneshot):
                now = time.monotonic()
                if self.oneshot or self.streaming and now >= next_t:
                    self.oneshot = False
                    self._do_measure()
                    next_t = now + self.interval_s
            time.sleep(0.02)

    def _connect(self, desc) -> None:
        self._disconnect()
        if desc[0] == "sim":
            t = PairTransport(Simulator())
        else:
            t = D2XXTransport(description=desc[1])
        dev = SkmDevice(t)
        dev.open()
        if not dev.handshake():
            t.close()
            self.state_changed.emit("УСТРОЙСТВА ОТКЛЮЧЕНЫ")
            self.connected.emit(False)
            return
        self.dev = dev
        self.state_changed.emit("ПОДКЛЮЧЕНО (СКМ)")
        self.connected.emit(True)

    def _disconnect(self) -> None:
        if self.dev is not None:
            try:
                self.dev.close()
            except Exception:  # noqa: S110 -- best effort on HW disconnect
                pass
        self.dev = None
        self.state_changed.emit("УСТРОЙСТВА ОТКЛЮЧЕНЫ")
        self.connected.emit(False)

    def _do_measure(self) -> None:
        try:
            dev = self.dev
            if dev is None:
                raise RuntimeError("not connected")
            samples = dev.meas.capture()
            spec = dev.meas.spectrum(fs=self.fs)
            self.result_ready.emit(MeasurementResult(samples, spec, True))
        except Exception as exc:                            # noqa: BLE001
            self.result_ready.emit(MeasurementResult(None, None, False,
                                                     str(exc)))


# ------------------------------------------------------------------- UI

class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("СКМ — измерения (standalone)")
        self.resize(1180, 760)
        self.thread = LinkThread()
        self.thread.state_changed.connect(self.on_state)
        self.thread.result_ready.connect(self.on_result)
        self.thread.start()

        central = QWidget()
        root = QHBoxLayout(central)

        # ---- left info column --------------------------------------
        left = QVBoxLayout()

        info = QGroupBox("ИНФОРМАЦИЯ")
        form = QFormLayout(info)
        self.lb_freq = QLabel("0 Гц")
        self.lb_level = QLabel("-160,0 дБ")
        for lb in (self.lb_freq, self.lb_level):
            f = lb.font()
            f.setPointSize(15)
            f.setBold(True)
            lb.setFont(f)
        form.addRow("ЧАСТОТА", self.lb_freq)
        form.addRow("УРОВЕНЬ", self.lb_level)
        left.addWidget(info)

        src = QGroupBox("ИЗМЕРЕНИЕ / источники")
        src_l = QVBoxLayout(src)
        self.cb_source = QComboBox()
        self.cb_source.addItems(["МИКРОФОН (I)", "АКСЕЛЕРОМЕТР (B)",
                                 "ДАТЧИК СИЛЫ (C)", "ЭЛЕКТРО АНТЕННА (D)",
                                 "МАГН. АНТЕННА (E)"])
        self.cb_source.currentIndexChanged.connect(self.on_source)
        src_l.addWidget(self.cb_source)
        self.cb_range = QComboBox()
        self.cb_range.addItems(["Диапазон 0 (R0)", "Диапазон 1 (R1)",
                                "Диапазон 2 (R2)"])
        self.cb_range.currentIndexChanged.connect(self.on_range)
        src_l.addWidget(self.cb_range)
        ch_row = QHBoxLayout()
        self.btn_ch_x = QPushButton("Канал X")
        self.btn_ch_y = QPushButton("Канал Y")
        self.btn_ch_x.setCheckable(True)
        self.btn_ch_y.setCheckable(True)
        self.btn_ch_x.setChecked(True)
        self.btn_ch_x.clicked.connect(self.on_channels)
        self.btn_ch_y.clicked.connect(self.on_channels)
        ch_row.addWidget(self.btn_ch_x)
        ch_row.addWidget(self.btn_ch_y)
        src_l.addLayout(ch_row)
        left.addWidget(src)

        acc = QGroupBox("Акустическая система")
        acc_l = QVBoxLayout(acc)
        b1 = QPushButton("ВКЛЮЧЕНИЕ АС (V)")
        b2 = QPushButton("ВЫКЛЮЧЕНИЕ АС (U)")
        b1.clicked.connect(lambda: self.cmd("speaker_on",
                                            lambda d: d.set_speaker(True)))
        b2.clicked.connect(lambda: self.cmd("speaker_off",
                                            lambda d: d.set_speaker(False)))
        acc_l.addWidget(b1)
        acc_l.addWidget(b2)
        left.addWidget(acc)

        gen = QGroupBox("Генератор ('H')")
        gen_l = QVBoxLayout(gen)
        gen_head = QHBoxLayout()
        gen_head.addWidget(QLabel("Частота, Гц"))
        self.sp_gen = QSpinBox()
        self.sp_gen.setRange(1, 20000)
        self.sp_gen.setValue(1000)
        gen_head.addWidget(self.sp_gen)
        gen_l.addLayout(gen_head)
        g_row = QHBoxLayout()
        gb = QPushButton("ВКЛ (H)")
        gs = QPushButton("СТОП")
        gb.clicked.connect(self.on_gen_on)
        gs.clicked.connect(self.on_gen_stop)
        g_row.addWidget(gb)
        g_row.addWidget(gs)
        gen_l.addLayout(g_row)
        left.addWidget(gen)

        meas = QGroupBox("Замер")
        meas_l = QVBoxLayout(meas)
        self.cb_auto = QPushButton("Авто-замер: выкл")
        self.cb_auto.setCheckable(True)
        self.cb_auto.toggled.connect(self.on_auto)
        meas_l.addWidget(self.cb_auto)
        row = QHBoxLayout()
        row.addWidget(QLabel("Интервал, с"))
        self.sp_int = QDoubleSpinBox()
        self.sp_int.setRange(0.5, 30.0)
        self.sp_int.setValue(2.0)
        self.sp_int.valueChanged.connect(lambda v: setattr(self.thread,
                                                           "interval_s", v))
        row.addWidget(self.sp_int)
        meas_l.addLayout(row)
        self.btn_once = QPushButton("ЗАМЕР (N/S)")
        self.btn_once.clicked.connect(self.thread.request_measure)
        meas_l.addWidget(self.btn_once)
        left.addWidget(meas)

        left.addStretch(1)
        root.addLayout(left)

        # ---- right plots -------------------------------------------
        self.tabs = QTabWidget()
        self.pw_spec = pg.PlotWidget(title="Спектр (дБ)")
        self.pl_spec = self.pw_spec.getPlotItem()
        self.pl_spec.setLabel("bottom", "Частота", units="Hz")
        self.pl_spec.setLabel("left", "Уровень", units="dB")
        self.pl_spec.setXRange(FMIN, FMAX)
        self.pl_spec.showGrid(x=True, alpha=0.25)
        self.spec_curve = self.pw_spec.plot(
            pen=pg.mkPen(color="#3da6e6", width=1))
        self.peak_marker = self.pw_spec.plot(
            pen=None, symbol="o", symbolSize=8, symbolBrush="#ffb020")

        self.pw_time = pg.PlotWidget(title="Осциллограмма (замер N)")
        self.pl_time = self.pw_time.getPlotItem()
        self.pl_time.setLabel("bottom", "Время", units="s")
        self.pl_time.setLabel("left", "Код (8 бит − 128)")
        self.pl_time.showGrid(x=True, alpha=0.25)
        self.time_curve = self.pw_time.plot(pen=pg.mkPen(color="#3da6e6",
                                                         width=1))

        self.tabs.addTab(self.pw_spec, "Спектр")
        self.tabs.addTab(self.pw_time, "Осциллограмма")
        root.addWidget(self.tabs, 1)
        self.setCentralWidget(central)

        # ---- connection bar / status -------------------------------
        bar = QWidget()
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(0, 0, 0, 0)
        self.cb_conn = QComboBox()
        self.cb_conn.addItems(["Симулятор СКМ-23", "FTDI: CKM 23v1"])
        bl.addWidget(self.cb_conn)
        self.btn_conn = QPushButton("Подключить")
        self.btn_conn.clicked.connect(self.on_connect)
        bl.addWidget(self.btn_conn)
        b2 = QPushButton("Отключить")
        b2.clicked.connect(self.thread.disconnect)
        bl.addWidget(b2)
        b3 = QPushButton("Handshake 'A'")
        b3.clicked.connect(lambda: self.cmd("keepalive", lambda d: d.handshake()))
        bl.addWidget(b3)
        self.statusBar().addWidget(bar, 1)
        self.lbl_state = QLabel("УСТРОЙСТВА ОТКЛЮЧЕНЫ")
        self.statusBar().addWidget(self.lbl_state, 0)
        self.statusBar().showMessage(
            "Симулятор ведёт себя по RE'нутому протоколу; FTDI — Windows + D2XX",
            8000)

    # ------------------------------------------------------- slots
    @Slot(str)
    def on_state(self, txt: str) -> None:
        self.lbl_state.setText(txt)

    @Slot(object)
    def on_result(self, res: MeasurementResult) -> None:
        spec: Spectrum | None = res.spec
        if not res.ok or spec is None or res.samples is None:
            self.statusBar().showMessage(f"замер не удался: {res.err}", 4000)
            return
        x, y = spec.freqs, spec.db
        mask = (x >= FMIN) & (x <= FMAX)
        self.spec_curve.setData(x[mask], y[mask])
        i = int(np.argmax(y[mask]))
        self.peak_marker.setData([x[mask][i]], [y[mask][i]])
        self.lb_freq.setText(f"{x[mask][i]:.0f} Гц")
        self.lb_level.setText(f"{y[i]:.1f} дБ".replace(".", ","))
        samples = res.samples
        n = len(samples)
        tail = samples[-1024:]          # ~20 periods of 1 kHz: scope-like
        self.time_curve.setData(np.arange(n - len(tail), n) / self.thread.fs,
                                tail)

    def on_connect(self) -> None:
        if self.cb_conn.currentIndex() == 0:
            self.thread.connect_simulator()
        else:
            self.thread.connect_d2xx()

    def cmd(self, name: str, fn) -> None:
        self.thread.submit(name, fn)

    def on_source(self, idx: int) -> None:
        self.cmd("source", lambda d: d.select_source(idx + 1))

    def on_range(self, idx: int) -> None:
        self.cmd("range", lambda d: d.set_range(idx))

    def on_channels(self) -> None:
        x = self.btn_ch_x.isChecked()
        y = self.btn_ch_y.isChecked()
        self.cmd("channels", lambda d: d.select_channel(x=x, y=y))

    def on_gen_on(self) -> None:
        freq = self.sp_gen.value()
        div = max(1, int(self.thread.fs / freq))
        self.cmd("gen", lambda d: d.set_generator(1, 2, div, 3, 4, 5, div))

    def on_gen_stop(self) -> None:
        self.cmd("gen_stop", lambda d: d.set_generator(0, 0, 1, 0, 0, 0, 1))

    def on_auto(self, on: bool) -> None:
        self.thread.streaming = on
        self.cb_auto.setText("Авто-замер: вкл" if on else "Авто-замер: выкл")

    def closeEvent(self, ev) -> None:                       # noqa: N802
        self.thread.stop()
        self.thread.wait(2000)
        super().closeEvent(ev)


def main() -> int:
    app = QApplication([])
    app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
