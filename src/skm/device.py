"""High-level SKM operations (one SkmDevice == one open channel).

API mirrors the CKM2PO command wrappers; docstrings carry the Ghidra
addresses of the functions being mirrored.
"""

from __future__ import annotations

from .constants import (
    BAUD,
    CMD_CH_X,
    CMD_CH_Y,
    CMD_F_QUERY,
    CMD_GENERATOR,
    CMD_KEEPALIVE,
    CMD_MEASURE_START,
    CMD_MEASURE_STOP,
    CMD_QUERY,
    CMD_RANGE,
    CMD_SAMPLE,
    CMD_SET,
    CMD_SET_REPLY,
    CMD_SPEAKER_OFF,
    CMD_SPEAKER_ON,
    RETRY_F_READ,
    RETRY_J_READ,
    RETRY_KEEPALIVE,
    RETRY_SET_REPLY,
    RETRY_SPEAKER,
)
from .measurement import MeasurementEngine
from .protocol import Protocol
from .transport import Transport


class DeviceError(RuntimeError):
    pass


class SkmDevice:
    def __init__(self, transport: Transport, poll_ms: int = 2) -> None:
        self.t = transport
        self.p = Protocol(transport, poll_ms=poll_ms)
        self.version_flag = 3  # CKM-23
        self.speaker = False
        self.meas = MeasurementEngine(self)

    # -- session ------------------------------------------------------
    def open(self, baud: int = BAUD) -> None:
        self.t.open()
        self.t.set_baud(baud)

    def close(self) -> None:
        self.t.close()

    def handshake(self) -> bool:
        """'A' keep-alive with 7-byte exchange (FUN_005894b8,
        <=51 retries). Returns True iff reply body came back."""
        self.p.drain()
        self.p.send(bytes([ord(CMD_KEEPALIVE)]))
        self.p.sleep(2)
        r = self.p.receive(ord(CMD_KEEPALIVE), 7, RETRY_KEEPALIVE)
        return bool(r)

    # -- speakers (FUN_0058a440) -----------------------------------
    def set_speaker(self, on: bool) -> bool:
        cmd = CMD_SPEAKER_ON if on else CMD_SPEAKER_OFF
        self.p.drain()
        self.p.send(bytes([ord(cmd)]))
        self.p.sleep(2)
        r = self.p.receive(ord(cmd), 1, RETRY_SPEAKER)
        self.speaker = on
        return bool(r)

    # -- selects without replies (FUN_0058a024 / 00589f6c / 0058a3a8) ----
    def select_source(self, which: int) -> None:
        """I/B/C/D/E as in FUN_0058a024 (1..5)."""
        self.p.drain()
        self.p.send(bytes([ord(CMD_SET[which])]))
        self.p.sleep(2)

    def select_channel(self, x: bool = True, y: bool = False) -> None:
        """'X' (param 1) and/or 'Y' (param 2/4) — FUN_00589f6c."""
        self.p.drain()
        if x:
            self.p.send(bytes([ord(CMD_CH_X)]))
        if y:
            self.p.send(bytes([ord(CMD_CH_Y)]))
        self.p.sleep(2)

    def set_range(self, idx: int) -> bool:
        """'R'+'0'..'2' (FUN_0058a3a8): 0..2, no reply; False if bus dead."""
        self.p.drain()
        self.p.send(bytes([ord(CMD_RANGE), ord("0") + idx]))
        self.p.sleep(2)
        return not self.p.last_sentinel

    # -- reply commands ----------------------------------------------
    def query_status(self) -> int | None:
        """'Q' -> 1 byte (FUN_0058a10c, 101 retries). No echo check RE'd."""
        self.p.drain()
        self.p.send(bytes([ord(CMD_QUERY)]))
        self.p.sleep(2)
        r = self.p.receive(ord(CMD_QUERY), 1, RETRY_SET_REPLY)
        return r[0] if len(r) >= 1 else None

    def set_with_reply(self, which: int) -> int | None:
        """'M'/'B'/'C'/'D'/'E' w/ 1-byte reply (FUN_0058a818)."""
        self.p.drain()
        self.p.send(bytes([ord(CMD_SET_REPLY[which])]))
        self.p.sleep(2)
        r = self.p.receive(ord(CMD_SET_REPLY[which]), 1, RETRY_SET_REPLY)
        return r[0] if len(r) >= 1 else None

    def read_sample(self) -> int | None:
        """'J' 12-bit read (FUN_0058a988): [J,hi,lo]; hi==0xFF -> 0."""
        self.p.drain()
        self.p.send(bytes([ord(CMD_SAMPLE)]))
        self.p.sleep(2)
        r = self.p.receive(ord(CMD_SAMPLE), 3, RETRY_J_READ, echo=True)
        if len(r) < 3:
            return None
        hi, lo = r[1], r[2]
        return 0 if hi == 0xFF else (hi << 8) + lo

    def read_freq(self) -> tuple[int, int] | None:
        """'F' 3-byte echo reply (FUN_0058a6d4): returns (b1, b2-1)."""
        self.p.drain()
        self.p.send(bytes([ord(CMD_F_QUERY)]))
        self.p.sleep(2)
        r = self.p.receive(ord(CMD_F_QUERY), 3, RETRY_F_READ, echo=True)
        if len(r) < 3:
            return None
        return r[1], r[2] - 1

    # -- generator (FUN_0058aadc) ----------------------------------
    def set_generator(self, p2: int, p1: int, div: int, p7: int, p6: int,
                      p5: int, div2: int) -> bool:
        """'H' + 12-byte frame; div bytes use the +/-1, zero->identity
        guard RE'd from the wrapper; then 'I' and a 6-byte reply (101)."""
        def enc(lo: int) -> tuple[int, int]:
            if lo < 0:
                hi, lo2 = -((-lo >> 8) & 0xFF), -((lo) & 0xFF)
                if hi == 0:
                    hi = 0xFF
                return hi, lo2 if lo2 != 0 else 0xFF
            hi, lo2 = (lo >> 8) & 0xFF, lo & 0xFF
            if lo2 == 0:
                lo2 = 1
            if hi == 0:
                hi = 0xFF
            return hi, lo2

        frame = bytes([ord(CMD_GENERATOR), p2 & 0xFF, p1 & 0xFF]) \
            + bytes(enc(div)) + bytes([2, p7 & 0xFF, p6 & 0xFF, p5 & 0xFF]) \
            + bytes(enc(div2))
        self.p.drain()
        self.p.send(frame)
        self.p.sleep(2)
        self.p.send(bytes([ord("I")]))
        r = self.p.receive(ord("I"), 6, RETRY_SET_REPLY)
        return bool(r)

    # -- measurement ----------------------------------------------------
    def measure_bytes(self, wrap: int = 0x10000, idle_limit: int = 100,
                      idle_ms: float = 2.0) -> bytes:
        """FUN_00589aec: 'N' -> capture byte stream until `wrap` samples
        OR `idle_limit` consecutive empty polls; then 'S'."""
        self.p.send(bytes([ord(CMD_MEASURE_START)]))
        acc = bytearray()
        idle = 0
        while len(acc) < wrap and idle < idle_limit:
            chunk = self.p.drain()
            if chunk:
                acc.extend(chunk)
                idle = 0
            else:
                idle += 1
                self.p.sleep(idle_ms)
        self.p.send(bytes([ord(CMD_MEASURE_STOP)]))
        self.p.sleep(2)
        return bytes(acc[:wrap])
