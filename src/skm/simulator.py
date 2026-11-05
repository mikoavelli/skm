"""Byte-level SKM-23 device simulator.

Faithful to the RE'd protocol shapes (FUN_00589xxx wrappers + measurement
loop FUN_00589aec). Device behaviour is deliberately parameterized so the
measurement engine can be developed against a known scene (sine sweep etc.)
and later swapped for real hardware.

Wiring: `PairTransport` (host side) <-> `Simulator` device side over a
queue pair — no serial stack needed; D2XXTransport replaces it 1:1 for HW.
"""

from __future__ import annotations

import math
import queue
import threading
import time

from .constants import BAUD


class PairTransport:
    """App-side end of the pipe to a Simulator. Drop-in for D2XXTransport."""

    def __init__(self, peer: Simulator) -> None:
        self.peer = peer
        self.baud = BAUD
        peer.attach(self)

    def open(self) -> None:
        pass

    def close(self) -> None:
        self.peer.detach()

    def write(self, data: bytes) -> None:
        self.peer.on_bytes(data)

    def read(self, want: int, timeout: float = 1.0) -> bytes:
        return self.peer.read_for_host(want, timeout)

    def queue(self) -> int:
        return self.peer.host_queue.qsize()

    def set_baud(self, baud: int) -> None:
        self.baud = baud


class Simulator:
    """CKM-23 behaviour. Single-threaded event pump driven from
    `on_bytes`; replies land in `host_queue`. Most commands reply with
    1 byte; 'N' starts a continuous sample stream until 'S' is received."""

    stream_fs = 51200.0         # sample rate of the 'N' byte stream (8 bit)
    stream_amp = 100.0          # dev counts (8-bit) amplitude of tone

    def __init__(self) -> None:
        self.host_queue: queue.Queue[int] = queue.Queue()
        self._measuring = False
        self._phase = 0.0
        self.gain_ch = [0, 0]       # R0..R2 / Р1..2 state per channel (X=0,Y=1)
        self.speaker = 0            # 'U'/'V'
        self.source = 0             # 'I'..'E'  (0..4)
        self.mode = 0               # 'M'..'E' separate 5-state group
        self.freq_bins = (2, 1)     # 'F' reply [b1, b2-1]
        self.j12 = 2048             # 'J' submodule value
        self.alive = True
        self._lock = threading.Lock()

    # -- plumbing ---------------------------------------------------------
    def attach(self, transport: PairTransport) -> None:
        self._t = transport

    def detach(self) -> None:
        pass

    def _reply(self, *vals: int) -> None:
        for v in vals:
            self.host_queue.put(v & 0xFF)

    def read_for_host(self, want: int, timeout: float) -> bytes:
        out = bytearray()
        deadline = time.monotonic() + timeout
        while len(out) < want and time.monotonic() < deadline:
            try:
                out.append(self.host_queue.get(timeout=max(
                    0.0, deadline - time.monotonic())))
            except queue.Empty:
                break
        return bytes(out)

    # -- the 'N' stream ----------------------------------------------------
    def _emit_stream_chunk(self) -> None:
        """Continuously emit 8-bit samples while measuring."""
        while self._measuring and self.alive:
            with self._lock:
                n = 512
                vals = bytearray()
                for _ in range(n):
                    self._phase += 2 * math.pi * 1000.0 / self.stream_fs
                    s = self.stream_amp * math.sin(self._phase) + 128.0
                    vals.append(max(0, min(255, int(s))))
            for v in vals:
                self.host_queue.put(v)
            time.sleep(n / self.stream_fs)

    # -- command decoder ----------------------------------------------------
    def on_bytes(self, data: bytes) -> None:
        i = 0
        while i < len(data):
            cmd = data[i]
            i += 1
            if cmd == ord("A"):            # keep-alive: 'A' + 6 status bytes
                self._reply(ord("A"), 0x31, 0x32, 0x33, 0x34, 0x35, 0x0D)
            elif cmd == ord("F"):          # 3-byte echo reply [F,b1,b2]
                self._reply(ord("F"), self.freq_bins[0], self.freq_bins[1] + 1)
            elif cmd == ord("N"):
                self._measuring = True
                threading.Thread(target=self._emit_stream_chunk,
                                 daemon=True).start()
            elif cmd == ord("S"):
                self._measuring = False
            elif cmd == ord("X"):
                self.gain_ch[0] = 0
            elif cmd == ord("Y"):
                self.gain_ch[1] = 1
            elif cmd in b"IBCDE":
                self.source = b"IBCDE".index(cmd)
                if cmd == ord("I"):        # 'I' after 'H' expects a 6B reply
                    self._reply(0x31, 0x32, 0x33, 0x0D, 0x0A, 0)
            elif cmd == ord("Q"):
                self._reply(0x30 + (self.speaker & 1))
            elif cmd == ord("R"):
                self.gain_ch[0] = data[i] - ord("0")
                i += 1
            elif cmd in b"UV":
                self.speaker = 1 if cmd == ord("V") else 0
                self._reply(0x01)
            elif cmd in b"":
                pass
            elif cmd == ord("M"):
                self.mode = 0
                self._reply(0x01)
            elif cmd == ord("J"):
                v = self.j12
                self._reply(ord("J"), (v >> 8) & 0x0F, v & 0xFF)
            elif cmd == ord("H"):
                # 'H' + 12 byte payload: consume silently (generator set)
                i += 12
            else:
                pass  # ignore unknown bytes (device firmware behaviour)
