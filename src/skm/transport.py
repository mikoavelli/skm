"""Byte transports for the SKM link.

Transport is deliberately the thinnest possible interface (the app's TOTAL
layer is only FT_Open/description-discovery + generic D2XX read/write):
  open() / close() / write(data) / read(max, timeout) / queue() / baud setter.
"""

from __future__ import annotations

import ctypes
import time
from typing import Protocol

from .constants import BAUD


class Transport(Protocol):
    def open(self) -> None: ...
    def close(self) -> None: ...
    def write(self, data: bytes) -> None: ...
    def read(self, want: int, timeout: float = 1.0) -> bytes: ...
    def queue(self) -> int: ...
    def set_baud(self, baud: int) -> None: ...


class LoopbackTransport:
    """Pair with SimulatorTransport not needed: `SimulatedTransport`
    talks to the in-process simulator directly. This class is for tests."""

    def __init__(self) -> None:
        self._rx = bytearray()

    def inject(self, data: bytes) -> None:
        self._rx.extend(data)

    def open(self) -> None:
        pass

    def close(self) -> None:
        pass

    def write(self, data: bytes) -> None:
        pass

    def read(self, want: int, timeout: float = 1.0) -> bytes:
        out = bytes(self._rx[:want])
        del self._rx[:want]
        return out

    def queue(self) -> int:
        return len(self._rx)

    def set_baud(self, baud: int) -> None:
        pass


class D2XXTransport:
    """FTDI D2XX via ctypes (ftd2xx.dll), matching the app's imports
    (FT_Open is by device *number*; discovery uses FT_ListDevices with
    descriptions — see FUN_00570b84). Windows-only."""

    FT_OK = 0
    FT_LIST_BY_INDEX = 0x80000000
    FT_LIST_ALL = 0x80000001
    OPEN_BY_DESCRIPTION = 2
    OPEN_BY_SERIAL = 3

    def __init__(self, description: str = "", serial: str = "12345678") -> None:
        self.description = description
        self.serial = serial
        self.baud = BAUD
        self._h = None
        self._dll = None

    def _ft(self):
        if self._dll is None:
            loader = getattr(ctypes, "WinDLL", None)
            if loader is None:
                # The ftd2xx driver shipped with the product is Windows-only;
                # fail with a clear wording instead of an attribute crash.
                raise OSError("D2XX-транспорт доступен только в Windows "
                              "(ftd2xx.dll); используйте источник "
                              "«СИМУЛЯТОР СКМ-23» или «ФАЙЛЫ (ТЕСТ-ДАННЫЕ)»")
            self._dll = loader("ftd2xx.dll")
        return self._dll

    def list_devices(self) -> list[tuple[str, str, str]]:
        """Returns [(desc, serial, port)] — approximates FT_ListDevices."""
        d = self._ft()
        n = ctypes.c_ulong()
        st = d.FT_CreateDeviceInfoList(ctypes.byref(n))
        if st != self.FT_OK:
            raise OSError(f"FT_CreateDeviceInfoList {st}")
        flagged = ctypes.c_ulong(self.FT_LIST_ALL)
        locid = (ctypes.c_ulong * 256)()
        devtype = (ctypes.c_ulong * 256)()
        devids = (ctypes.c_ulong * 256)()
        desc = (ctypes.c_wchar_p * 256)()
        serials = (ctypes.c_wchar_p * 256)()
        ret = []
        if d.FT_GetDeviceInfoList(flagged, ctypes.byref(n), locid, devtype,
                                  devids, desc, serials) == self.FT_OK:
            for i in range(n.value):
                ret.append((desc[i], serials[i], str(locid[i])))
        return ret

    def open(self) -> None:
        d = self._ft()
        h = ctypes.c_void_p()
        code = None
        if self.description:
            code = d.FT_OpenEx(self.description.encode("utf-16-le") or
                               self.description, self.OPEN_BY_DESCRIPTION,
                               ctypes.byref(h))
        if code != self.FT_OK and self.serial:
            code = d.FT_OpenEx(self.serial.encode(), self.OPEN_BY_SERIAL,
                               ctypes.byref(h))
        if code != self.FT_OK:
            raise OSError(f"FT_OpenEx failed {code}")
        self._h = h
        d.FT_SetBaudRate(h, self.baud)
        # 8N1 like the app's FT_SetDataCharacteristics(8,0,0)
        d.FT_SetDataCharacteristics(h, 8, 0, 0)
        d.FT_SetFlowControl(h, 0, 0, 0)  # none

    def close(self) -> None:
        if self._h is not None:
            self._ft().FT_Close(self._h)
            self._h = None

    def write(self, data: bytes) -> None:
        got = ctypes.c_ulong()
        if self._h is None:
            raise OSError("write on closed transport")
        d = self._ft()
        st = d.FT_Write(self._h, data, len(data), ctypes.byref(got))
        if st != self.FT_OK:
            raise OSError(f"FT_Write {st}")
        if got.value != len(data):
            raise OSError("short write")

    def queue(self) -> int:
        rx = ctypes.c_ulong()
        if self._h is None:
            return -1
        if self._ft().FT_GetQueueStatus(self._h, ctypes.byref(rx)) != self.FT_OK:
            return -1
        return rx.value

    def read(self, want: int, timeout: float = 1.0) -> bytes:
        if self._h is None:
            raise OSError("read on closed transport")
        d = self._ft()
        got = ctypes.c_ulong()
        out = bytearray()
        deadline = time.monotonic() + timeout
        while len(out) < want and time.monotonic() < deadline:
            rx = self.queue()
            if rx <= 0:
                time.sleep(0.001)
                continue
            buf = (ctypes.c_ubyte * min(rx, want - len(out)))()
            st = d.FT_Read(self._h, buf, len(buf), ctypes.byref(got))
            if st != self.FT_OK:
                raise OSError(f"FT_Read {st}")
            out.extend(buf[:got.value])
        return bytes(out)

    def set_baud(self, baud: int) -> None:
        self.baud = baud
        if self._h is not None:
            self._ft().FT_SetBaudRate(self._h, baud)
