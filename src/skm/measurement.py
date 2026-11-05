"""Measurement engine: 'N'-stream capture -> 65536-point spectrum.

Mirrors FUN_00589aec post-processing (65536 element loop then FFT with
FUN_004175b0/00415460 and band building). The app treats the captured
byte stream as a sequence of 65536 eight-bit ADC samples (the ring
buffer wraps after 0x10000 elements), so the spectrum input is
samples - 128.0 (device codes are unsigned) — RE-assumption recorded in
analysis/notes.md; configurable via `signed=False=True|False`.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .constants import MEASURE_WRAP


@dataclass
class Spectrum:
    freqs: np.ndarray        # bin centers, Hz
    lin: np.ndarray          # linear magnitudes (same length as freqs)
    db: np.ndarray           # 20*log10 magnitude, -inf floors to -160

    def band_db(self, f: float, half: float | None = None) -> float:
        m = (self.freqs >= f - (half or f * 0.03)) & \
            (self.freqs <= f + (half or f * 0.03))
        if not m.any():
            return -160.0
        return float(self.db[m].max())


class MeasurementEngine:
    def __init__(self, device, signed: bool = False) -> None:
        self.d = device
        self.signed = signed

    def capture(self, wrap: int = MEASURE_WRAP) -> np.ndarray:
        raw = self.d.measure_bytes(wrap=wrap)
        if not raw:
            raise RuntimeError("no measurement stream captured")
        if len(raw) < wrap:
            raw = raw + bytes(wrap - len(raw))
        x = np.frombuffer(raw[:wrap], dtype=np.uint8).astype(np.float64)
        if self.signed:
            x = ((x.view(np.int8)).astype(np.float64))
        else:
            x = x - 128.0
        return x

    def spectrum(self, fs: float, wrap: int = MEASURE_WRAP) -> Spectrum:
        x = self.capture(wrap=wrap)
        x = x - x.mean()                      # remove residual DC
        win = np.hanning(len(x))
        mag = np.abs(np.fft.rfft(x * win))
        freqs = np.fft.rfftfreq(len(x), d=1.0 / fs)
        db = np.full_like(mag, -160.0)
        nz = mag > 1e-12
        db[nz] = 20.0 * np.log10(mag[nz])
        return Spectrum(freqs=freqs, lin=mag, db=db)
