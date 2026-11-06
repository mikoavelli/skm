"""Precomputed spectrum files as an input source.

Duplicates the input of the signal-processor project: its `test_data`
directory holds two ready-made spectra as `freq<tab>voltage` text tables
with a 1 Hz grid (comments start with '#', '[' or '('):

  noise.txt         — "pure noise" spectrum (U_n)
  signal_noise.txt  — "signal + noise" spectrum (U_sn)

The GUI can connect to this file pair as to a third input kind and switch
between the two display modes (noise / signal + noise) without touching
the device transport.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

COMMENTS = ("#", "[", "(")


@dataclass(slots=True)
class SpectrumFile:
    """A parsed spectrum file: 1 Hz frequency grid + voltage levels, V."""

    path: Path
    kind: str                 # "noise" | "signal_noise"
    freqs_hz: list[float]
    volts: list[float]

    @classmethod
    def load(cls, kind: str, path: Path | None = None) -> SpectrumFile:
        if path is None:
            path = default_test_data_dir() / f"{kind}.txt"
        freqs: list[float] = []
        volts: list[float] = []
        with path.open(encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith(COMMENTS):
                    continue
                parts = line.replace(",", ".").split()
                if len(parts) < 2:
                    continue
                try:
                    freqs.append(float(parts[0]))
                    volts.append(float(parts[1]))
                except ValueError:      # tolerate stray non-numeric rows
                    continue
        if not freqs:
            raise ValueError(f"no spectrum rows in {path}")
        return cls(path=path, kind=kind, freqs_hz=freqs, volts=volts)


def default_test_data_dir() -> Path:
    """Resolve the signal-processor test_data directory.

    Order: SKM_TEST_DATA_DIR env override, then the sibling repository
    layout used on this machine (<projects>/signal-processor/test_data).
    """
    override = os.environ.get("SKM_TEST_DATA_DIR")
    if override:
        return Path(override)
    # spectra.py -> skm/ -> src/ -> <repo>/ -> <projects>/
    return Path(__file__).resolve().parents[2].parent / "signal-processor" / "test_data"


FILE_KINDS = ("noise", "signal_noise")
