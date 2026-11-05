"""Low-level exchange helpers mirroring the app's TOTAL layer.

Pattern RE'd from FUN_00589xxx wrappers:
  1) drain()            — FT_GetQueueStatus + FT_Read everything (FUN_00589164)
  2) failed() check     — sentinel 0x499602D2 (FUN_0058a258)
  3) build frame in the single TX buffer, FT_Write (FUN_00589144)
  4) pump-sleep (FUN_005891c8/20c)
  5) receive-until: accumulate newly drained bytes; on an empty poll count
     a retry; stop when replies complete OR retries exhausted. Byte 0 must
     echo the command (checked in 0058a988 etc.).
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from .transport import Transport


@dataclass
class Exchange:
    cmd: bytes
    reply: bytes

    def ok(self) -> bool:
        return bool(self.reply)


NO_REPLY = Exchange(b"", b"")


class Protocol:
    """Frame/receive layer on a Transport. One instance per open device."""

    def __init__(self, transport: Transport, poll_ms: int = 2) -> None:
        self.t = transport
        self.poll_ms = poll_ms
        self.last_sentinel = False

    # -- primitives (FUN_00589164 / 00589144 / 0058a258 equivalents) --------
    def drain(self) -> bytes:
        """Read everything currently queued; sentinel on FT error."""
        n = self.t.queue()
        if n is None or n < 0:
            self.last_sentinel = True
            return bytes([0]) * 0
        if n == 0:
            return b""
        return self.t.read(n, timeout=0.05)

    def send(self, frame: bytes) -> None:
        self.t.write(frame)

    def sleep(self, ms: float) -> None:
        time.sleep(ms / 1000.0)

    # -- generic receive-until loop ------------------------------------
    def receive(self, cmd: int, want: int, retries: int,
                echo: bool = False) -> bytes:
        """Collect `want` reply bytes; `retries` empty polls allowed.
        Mirror of 0058a440/0058a988/0058a818 loops. `echo=True` checks
        acc[0]==cmd (RE: only 'F' a6d4 and 'J' a988 verify the echo)."""
        acc = bytearray()
        empty = 0
        while len(acc) < want and empty < retries:
            chunk = self.drain()
            if chunk:
                acc.extend(chunk)
                empty = 0
            else:
                empty += 1
                self.sleep(self.poll_ms)
        if echo and acc and acc[0] != cmd:
            return b""          # echo mismatch -> treat as failure
        return bytes(acc) if len(acc) >= want else b""

    def frame(self, *payload: bytes) -> bytes:
        return b"".join(payload)
