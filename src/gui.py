"""Standalone SKM measurement GUI (PySide6 + pyqtgraph).

Mirrors the CKM2PO measurement screen (TMF) on top of the `skm` core:
  - connect: in-process SKM simulator, FTDI D2XX hardware on Windows, or
    a precomputed-spectrum file pair (signal-processor test data) with two
    display modes: pure noise / signal + noise;
  - spectrum (10 Hz..20 kHz) + oscillogram of the 65536-sample 'N'/'S'
    capture, live-refreshed at a settable interval (worker thread);
  - INFO readouts FREQUENCY / LEVEL (peak freq / band level);
  - source select (I..'E'), channels X/Y, range R0..2, speaker 'U'/'V',
    generator 'H' (frequency + start/stop), handshake keep-alive.

Threading: all device I/O happens in a LinkThread; the UI thread never
touches the transport (the RE'd layer is synchronous and poll-heavy).
Results arrive as numpy arrays via signals; captions update from them.

Run:  uv run python src/main.py
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
    QRadioButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from skm import D2XXTransport, PairTransport, Simulator, SkmDevice, Spectrum
from skm.measurement import Spectrum as _Spectrum  # same class, for typing
from skm.spectra import SpectrumFile

FMIN, FMAX = 10.0, 20000.0          # SKM spectrum span (DFM band panel)
FILE_FMAX = 32000.0                 # test-data files span up to 32000 Hz
DEFAULT_FS = 51200.0                # simulator stream fs; for HW settable
DB_FLOOR = 1e-6                     # V floor for 20*log10 of file spectra


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
    """Owns the device (or the loaded file spectra); executes commands
    posted by the UI and runs the optional continuous measure loop."""

    state_changed = Signal(str)
    result_ready = Signal(object)          # MeasurementResult
    connection_changed = Signal(str)       # "" | "sim" | "d2xx" | "files"

    def __init__(self) -> None:
        super().__init__()
        self.dev: SkmDevice | None = None
        self.files: dict[str, SpectrumFile] | None = None
        self.file_kind = "noise"
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

    def connect_files(self) -> None:
        self._queue.append(("connect_files", None))

    def set_file_mode(self, kind: str) -> None:
        self._queue.append(("file_mode", kind))

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
                    elif kind == "file_mode":
                        self.file_kind = arg
                        self.oneshot = True
                    elif kind == "disconnect":
                        self._disconnect()
                    elif kind == "cmd" and self.dev is not None:
                        arg[1](self.dev)
                except Exception as exc:                    # noqa: BLE001
                    self.state_changed.emit(f"Error: {exc}")
            if self._input_ready() and (self.streaming or self.oneshot):
                now = time.monotonic()
                if self.oneshot or self.streaming and now >= next_t:
                    self.oneshot = False
                    self._do_measure()
                    next_t = now + self.interval_s
            time.sleep(0.02)

    def _input_ready(self) -> bool:
        return self.dev is not None or (
            self.files is not None and self.file_kind in self.files)

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
            self.state_changed.emit("DEVICES DISCONNECTED")
            self.connection_changed.emit("")
            return
        self.dev = dev
        self.state_changed.emit("CONNECTED (SKM)")
        self.connection_changed.emit(desc[0])

    def _connect_files(self) -> None:
        self._close_device()
        try:
            self.files = {kind: SpectrumFile.load(kind) for kind in
                          ("noise", "signal_noise")}
        except Exception as exc:                        # noqa: BLE001
            self.files = None
            self.state_changed.emit(f"Error: {exc}")
            self.connection_changed.emit("")
            return
        self.state_changed.emit("CONNECTED (FILES)")
        self.oneshot = True
        self.connection_changed.emit("files")

    def _close_device(self) -> None:
        if self.dev is not None:
            try:
                self.dev.close()
            except Exception:  # noqa: S110 -- best effort on HW disconnect
                pass
        self.dev = None

    def _disconnect(self) -> None:
        self._close_device()
        self.files = None
        self.state_changed.emit("DEVICES DISCONNECTED")
        self.connection_changed.emit("")

    def _do_measure(self) -> None:
        try:
            if self.files is not None:
                sf = self.files[self.file_kind]
                spec = self._file_spectrum(sf)
                self.result_ready.emit(MeasurementResult(None, spec, True))
                return
            dev = self.dev
            if dev is None:
                raise RuntimeError("not connected")
            samples = dev.meas.capture()
            spec = dev.meas.spectrum(fs=self.fs)
            self.result_ready.emit(MeasurementResult(samples, spec, True))
        except Exception as exc:                        # noqa: BLE001
            self.result_ready.emit(MeasurementResult(None, None, False,
                                                     str(exc)))

    @staticmethod
    def _file_spectrum(sf: SpectrumFile) -> _Spectrum:
        """Wrap a precomputed spectrum into the Spectrum shape."""
        volts = np.asarray(sf.volts)
        db = 20.0 * np.log10(np.maximum(volts, DB_FLOOR))
        return Spectrum(freqs=np.asarray(sf.freqs_hz), lin=volts, db=db)


# ------------------------------------------------------------------- UI

class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("SKM — measurement (standalone)")
        self.resize(1180, 760)
        self._fmax = FMAX          # widened in file mode (files go to 32000)
        self.thread = LinkThread()
        self.thread.state_changed.connect(self.on_state)
        self.thread.result_ready.connect(self.on_result)
        self.thread.connection_changed.connect(self.on_connection)
        self.thread.start()

        central = QWidget()
        root = QHBoxLayout(central)

        # ---- left info column --------------------------------------
        left = QVBoxLayout()

        info = QGroupBox("INFO")
        form = QFormLayout(info)
        self.lb_freq = QLabel("0 Hz")
        self.lb_level = QLabel("-160.0 dB")
        for lb in (self.lb_freq, self.lb_level):
            f = lb.font()
            f.setPointSize(15)
            f.setBold(True)
            lb.setFont(f)
        form.addRow("FREQUENCY", self.lb_freq)
        form.addRow("LEVEL", self.lb_level)
        left.addWidget(info)

        src = QGroupBox("MEASUREMENT / sources")
        src_l = QVBoxLayout(src)
        self.cb_source = QComboBox()
        self.cb_source.addItems(["MICROPHONE (I)", "ACCELEROMETER (B)",
                                 "FORCE SENSOR (C)", "ELECTRIC ANTENNA (D)",
                                 "MAGNETIC ANTENNA (E)"])
        self.cb_source.currentIndexChanged.connect(self.on_source)
        src_l.addWidget(self.cb_source)
        self.cb_range = QComboBox()
        self.cb_range.addItems(["Range 0 (R0)", "Range 1 (R1)",
                                "Range 2 (R2)"])
        self.cb_range.currentIndexChanged.connect(self.on_range)
        src_l.addWidget(self.cb_range)
        ch_row = QHBoxLayout()
        self.btn_ch_x = QPushButton("Channel X")
        self.btn_ch_y = QPushButton("Channel Y")
        self.btn_ch_x.setCheckable(True)
        self.btn_ch_y.setCheckable(True)
        self.btn_ch_x.setChecked(True)
        self.btn_ch_x.clicked.connect(self.on_channels)
        self.btn_ch_y.clicked.connect(self.on_channels)
        ch_row.addWidget(self.btn_ch_x)
        ch_row.addWidget(self.btn_ch_y)
        src_l.addLayout(ch_row)
        left.addWidget(src)

        acc = QGroupBox("Acoustic system")
        acc_l = QVBoxLayout(acc)
        b1 = QPushButton("SPEAKER ON (V)")
        b2 = QPushButton("SPEAKER OFF (U)")
        b1.clicked.connect(lambda: self.cmd("speaker_on",
                                            lambda d: d.set_speaker(True)))
        b2.clicked.connect(lambda: self.cmd("speaker_off",
                                            lambda d: d.set_speaker(False)))
        acc_l.addWidget(b1)
        acc_l.addWidget(b2)
        left.addWidget(acc)

        gen = QGroupBox("Generator ('H')")
        gen_l = QVBoxLayout(gen)
        gen_head = QHBoxLayout()
        gen_head.addWidget(QLabel("Frequency, Hz"))
        self.sp_gen = QSpinBox()
        self.sp_gen.setRange(1, 20000)
        self.sp_gen.setValue(1000)
        gen_head.addWidget(self.sp_gen)
        gen_l.addLayout(gen_head)
        g_row = QHBoxLayout()
        gb = QPushButton("ON (H)")
        gs = QPushButton("STOP")
        gb.clicked.connect(self.on_gen_on)
        gs.clicked.connect(self.on_gen_stop)
        g_row.addWidget(gb)
        g_row.addWidget(gs)
        gen_l.addLayout(g_row)
        left.addWidget(gen)

        meas = QGroupBox("Measurement")
        meas_l = QVBoxLayout(meas)
        self.cb_auto = QPushButton("Auto-measure: off")
        self.cb_auto.setCheckable(True)
        self.cb_auto.toggled.connect(self.on_auto)
        meas_l.addWidget(self.cb_auto)
        row = QHBoxLayout()
        row.addWidget(QLabel("Interval, s"))
        self.sp_int = QDoubleSpinBox()
        self.sp_int.setRange(0.5, 30.0)
        self.sp_int.setValue(2.0)
        self.sp_int.valueChanged.connect(lambda v: setattr(self.thread,
                                                           "interval_s", v))
        row.addWidget(self.sp_int)
        meas_l.addLayout(row)
        self.btn_once = QPushButton("MEASURE (N/S)")
        self.btn_once.clicked.connect(self.thread.request_measure)
        meas_l.addWidget(self.btn_once)
        left.addWidget(meas)

        # file-input display modes (active only in the Files connection)
        fm = QGroupBox("File input mode")
        fm_l = QVBoxLayout(fm)
        self.rb_noise = QRadioButton("Noise (U_n)")
        self.rb_signal = QRadioButton("Signal + noise (U_sn)")
        self.rb_noise.setChecked(True)
        self.rb_noise.toggled.connect(self.on_file_mode)
        self.rb_signal.toggled.connect(self.on_file_mode)
        fm_l.addWidget(self.rb_noise)
        fm_l.addWidget(self.rb_signal)
        self.grp_files = fm
        self.grp_files.setEnabled(False)
        left.addWidget(fm)

        left.addStretch(1)
        root.addLayout(left)

        # ---- right plots -------------------------------------------
        self.tabs = QTabWidget()
        self.pw_spec = pg.PlotWidget(title="Spectrum (dB)")
        self.pl_spec = self.pw_spec.getPlotItem()
        self.pl_spec.setLabel("bottom", "Frequency", units="Hz")
        self.pl_spec.setLabel("left", "Level", units="dB")
        self.pl_spec.setXRange(FMIN, FMAX)
        self.pl_spec.showGrid(x=True, alpha=0.25)
        self.spec_curve = self.pw_spec.plot(
            pen=pg.mkPen(color="#3da6e6", width=1))
        self.peak_marker = self.pw_spec.plot(
            pen=None, symbol="o", symbolSize=8, symbolBrush="#ffb020")

        self.pw_time = pg.PlotWidget(title="Oscillogram ('N' capture)")
        self.pl_time = self.pw_time.getPlotItem()
        self.pl_time.setLabel("bottom", "Time", units="s")
        self.pl_time.setLabel("left", "Code (8 bit − 128)")
        self.pl_time.showGrid(x=True, alpha=0.25)
        self.time_curve = self.pw_time.plot(pen=pg.mkPen(color="#3da6e6",
                                                         width=1))

        self.tabs.addTab(self.pw_spec, "Spectrum")
        self.tabs.addTab(self.pw_time, "Oscillogram")
        root.addWidget(self.tabs, 1)
        self.setCentralWidget(central)

        # ---- connection bar / status -------------------------------
        bar = QWidget()
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(0, 0, 0, 0)
        self.cb_conn = QComboBox()
        self.cb_conn.addItems(["SKM-23 Simulator", "FTDI: CKM 23v1",
                               "Files (test data)"])
        bl.addWidget(self.cb_conn)
        self.btn_conn = QPushButton("Connect")
        self.btn_conn.clicked.connect(self.on_connect)
        bl.addWidget(self.btn_conn)
        b2 = QPushButton("Disconnect")
        b2.clicked.connect(self.thread.disconnect)
        bl.addWidget(b2)
        b3 = QPushButton("Handshake 'A'")
        b3.clicked.connect(lambda: self.cmd("keepalive", lambda d: d.handshake()))
        bl.addWidget(b3)
        self.statusBar().addWidget(bar, 1)
        self.lbl_state = QLabel("DEVICES DISCONNECTED")
        self.statusBar().addWidget(self.lbl_state, 0)
        self.statusBar().showMessage(
            "Simulator follows the RE'd protocol; FTDI needs Windows + D2XX; "
            "Files display precomputed spectra", 8000)

    # ------------------------------------------------------- slots
    @Slot(str)
    def on_state(self, txt: str) -> None:
        self.lbl_state.setText(txt)

    @Slot(str)
    def on_connection(self, kind: str) -> None:
        """kind: "" | "sim" | "d2xx" | "files"."""
        self.grp_files.setEnabled(kind == "files")
        self.tabs.setTabEnabled(1, kind != "files")  # no time data in files
        self._fmax = FILE_FMAX if kind == "files" else FMAX
        self.pl_spec.setXRange(FMIN, self._fmax)

    @Slot(object)
    def on_result(self, res: MeasurementResult) -> None:
        spec: Spectrum | None = res.spec
        if not res.ok or spec is None:
            self.statusBar().showMessage(f"measurement failed: {res.err}",
                                         4000)
            return
        x, y = spec.freqs, spec.db
        mask = (x >= FMIN) & (x <= self._fmax)
        self.spec_curve.setData(x[mask], y[mask])
        xm, ym = x[mask], y[mask]
        i = int(np.argmax(ym))
        self.peak_marker.setData([xm[i]], [ym[i]])
        self.lb_freq.setText(f"{xm[i]:.0f} Hz")
        self.lb_level.setText(f"{ym[i]:.1f} dB")
        samples = res.samples
        if samples is None:              # file mode: no time-domain data
            self.time_curve.setData([], [])
            return
        n = len(samples)
        tail = samples[-1024:]          # ~20 periods of 1 kHz: scope-like
        self.time_curve.setData(np.arange(n - len(tail), n) / self.thread.fs,
                                tail)

    def on_connect(self) -> None:
        match self.cb_conn.currentIndex():
            case 0:
                self.thread.connect_simulator()
            case 1:
                self.thread.connect_d2xx()
            case 2:
                self.thread.connect_files()

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
        div = max(1, round(self.thread.fs / freq))
        self.cmd("gen", lambda d: d.set_generator(1, 2, div, 3, 4, 5, div))
        self.thread.request_measure()   # the scene changed: refresh the view

    def on_gen_stop(self) -> None:
        self.cmd("gen_stop", lambda d: d.set_generator(0, 0, 1, 0, 0, 0, 1))
        self.thread.request_measure()   # show the silence/noise floor

    def on_auto(self, on: bool) -> None:
        self.thread.streaming = on
        self.cb_auto.setText("Auto-measure: on" if on else "Auto-measure: off")

    def on_file_mode(self) -> None:
        kind = "signal_noise" if self.rb_signal.isChecked() else "noise"
        self.thread.set_file_mode(kind)

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
