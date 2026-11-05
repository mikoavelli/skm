"""CLI for the skm link core.

  python3 -m skmapp.cli probe        # discovery + handshake + status
  python3 -m skmapp.cli speaker on|off
  python3 -m skmapp.cli sample       # 'J' 12-bit probe reads
  python3 -m skmapp.cli gen 1000     # 'H' generator demo
  python3 -m skmapp.cli measure      # capture + spectrum, print bands
"""
from __future__ import annotations

import sys

import numpy as np

from skm import PairTransport, Simulator, SkmDevice


def open_sim() -> SkmDevice:
    sim = Simulator()
    dev = SkmDevice(PairTransport(sim))
    dev.open()
    return dev


def cmd_probe(dev: SkmDevice) -> int:
    ok = dev.handshake()
    print(f"handshake 'A': {'OK' if ok else 'NO REPLY'}")
    print(f"status 'Q': {dev.query_status()}")
    print(f"freq 'F': {dev.read_freq()}")
    print(f"sample 'J': {dev.read_sample()}")
    print(f"speaker 'V/U' toggle: on={dev.set_speaker(True)} "
          f"q={dev.query_status()} off={dev.set_speaker(False)} "
          f"q={dev.query_status()}")
    return 0


def cmd_speaker(dev: SkmDevice, on: bool) -> int:
    print("OK" if dev.set_speaker(on) else "NO REPLY")
    return 0


def cmd_sample(dev: SkmDevice) -> int:
    for _ in range(5):
        print("J =", dev.read_sample())
    return 0


def cmd_gen(dev: SkmDevice, freq: int) -> int:
    # div approximation: stream_fs/frequency guard-wrapped (RE: FUN_0058aadc)
    div = max(1, int(Simulator.stream_fs / freq))
    ok = dev.set_generator(p2=1, p1=2, div=div, p7=3, p6=4, p5=5, div2=div)
    print(f"H frame sent ({'ok' if ok else 'no reply'}), div={div}")
    return 0


def cmd_measure(dev: SkmDevice, fs: float) -> int:
    sp = dev.meas.spectrum(fs=fs)
    print(f"captured 65536 samples, bin={sp.freqs[1]:.2f} Hz")
    print(f"peak: {sp.freqs[int(np.argmax(sp.lin))]:.1f} Hz "
          f"@ {sp.db.max():.1f} dB")
    for f in (100, 500, 1000, 2000, 5000, 10000):
        print(f"  band {f:6d} Hz: {sp.band_db(f):7.1f} dB")
    return 0


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    cmd = argv[0]
    dev = open_sim()
    try:
        if cmd == "probe":
            return cmd_probe(dev)
        if cmd == "speaker" and len(argv) > 1:
            return cmd_speaker(dev, argv[1] == "on")
        if cmd == "sample":
            return cmd_sample(dev)
        if cmd == "gen" and len(argv) > 1:
            return cmd_gen(dev, int(argv[1]))
        if cmd == "measure":
            return cmd_measure(dev, fs=51200.0)
        print(f"unknown command {cmd!r}", file=sys.stderr)
        return 2
    finally:
        dev.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
