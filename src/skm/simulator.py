"""Byte-level SKM-23 device simulator.

Faithful to the RE'd protocol shapes (FUN_00589xxx wrappers + measurement
loop FUN_00589aec). The measured scene ("what the 'N' stream sounds like")
is generated synthetically so the measurement engine and the visualization
can be developed and demoed without hardware: a sine test tone (stepwise
rewritten by the 'H' generator command, with amplitude/noise knobs) on top
of a Gaussian noise floor. The D2XXTransport swaps this out 1:1 for HW.

Wiring: `PairTransport` (host side) <-> `Simulator` device side over a
queue pair — no serial stack needed.
"""

from __future__ import annotations

import math
import queue
import random
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
    GEN_AMP = 100.0             # tone amplitude applied on generator-ON

    def __init__(self, tone_freq: float = 1000.0, tone_amp: float = 100.0,
                 noise_sigma: float = 3.0) -> None:
        self.host_queue: queue.Queue[int] = queue.Queue()
        self._measuring = False
        self._phase = 0.0
        # -- synthetic scene behind the 'N' stream -------------------------
        self.tone_freq = tone_freq  # test tone frequency, Hz (0 = silence)
        self.tone_amp = tone_amp    # dev counts (8-bit), amplitude
        self.noise_sigma = noise_sigma  # Gaussian noise floor, dev counts
        # -- protocol state ------------------------------------------------
        self.gain_ch = [0, 0]       # R0..R2 / P1..2 state per channel (X=0,Y=1)
        self.speaker = 0            # 'U'/'V'
        self.source = 0             # 'I'..'E'  (0..4)
        self.mode = 0               # 'M'..'E' separate 5-state group
        self.freq_bins = (2, 1)     # 'F' reply [b1, b2-1]
        self.j12 = 2048             # 'J' submodule value
        self.generator = False      # last 'H' state
        self.alive = True
        self._lock = threading.Lock()

    # -- scene control (direct API for tests/CLI; also driven by 'H') -----
    def set_scene(self, freq: float | None = None, amp: float | None = None,
                  noise: float | None = None) -> None:
        """Rewrite the synthetic scene emitted by the 'N' stream."""
        with self._lock:
            if freq is not None:
                self.tone_freq = freq
            if amp is not None:
                self.tone_amp = amp
            if noise is not None:
                self.noise_sigma = noise

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
                    self._phase += 2 * math.pi * self.tone_freq / self.stream_fs
                    s = (128.0
                         + self.tone_amp * math.sin(self._phase)
                         + random.gauss(0.0, self.noise_sigma))
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
                # 'H' + 10-byte payload (11-byte frame per FUN_0058aadc):
                # [H,p2,p1,div16,2,p7,p6,p5,div16]. The RE semantics of the
                # fields are unresolved; DEMO interpretation here: p2==0 stops
                # the generator (silence), otherwise the first divider word
                # sets the emitted tone as stream_fs/div (same encode as the
                # app side in device.set_generator).
                payload = data[i:i + 10]
                i += 10
                self._on_generator(payload)
            else:
                pass  # ignore unknown bytes (device firmware behaviour)

    # -- 'H' scene mapping ----------------------------------------------
    def _on_generator(self, payload: bytes) -> None:
        """Apply the 'H' payload to the scene (demo interpretation)."""
        if len(payload) < 5:
            return
        p2 = payload[0]
        if p2 == 0:                                 # STOP: silence the tone
            self.generator = False
            self.set_scene(amp=0.0)
            return
        hi, lo = payload[2], payload[3]
        div = lo if hi == 0xFF else (hi << 8) + lo  # inverse of the ±1 guard
        if div <= 0:
            return
        self.generator = True
        self.set_scene(freq=self.stream_fs / div, amp=self.__class__.GEN_AMP)
