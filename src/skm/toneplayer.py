"""TonePlayer app integration (stub for future in-place functionality).

TonePlayer is the companion tone-generator app (../tone-player). For now
the SKM GUI only launches it and drives its remote-call CLI ("msg" calls);
later the same actions will be implemented natively inside SKM.

Deployed layout assumption: the TonePlayer executable lives in the same
folder as the SKM app, and its `settings.json` MUST sit next to it
(TonePlayer refuses to start without it).

Remote calls: run the TonePlayer binary as
    TonePlayer msg <call> [args...]
The call is delivered over a QLocalSocket to the running instance
(server name "tone-player"); the answer is one JSON line
`{"ok": bool, "message": str}` on stdout, error text on stderr.

Known calls (MainWindow.handle_call): autoplay, first, last, next, pause,
play, prev, resume, select, status, stop.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

#: Environment override: full path to the TonePlayer executable.
ENV_TONE_PLAYER = "SKM_TONE_PLAYER"
#: Seconds before a hung msg call is abandoned.
CALL_TIMEOUT_S = 20.0

_SRV_HINT = "(run TonePlayer first)"


def find_exe() -> Path:
    """Locate the TonePlayer executable; raise FileNotFoundError if absent.

    Order: SKM_TONE_PLAYER env override, then (frozen app) next to the SKM
    executable — the deployed "same folder" layout, then the sibling dev
    repository (../tone-player/dist/TonePlayer).
    """
    override = os.environ.get(ENV_TONE_PLAYER, "").strip()
    if override:
        candidates = [Path(override)]
    elif getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve().parent / "TonePlayer"
        exe = exe.with_suffix(".exe" if os.name == "nt" else "")
        candidates = [exe]
    else:
        # toneplayer.py -> skm/ -> src/ -> <skm repo>/ -> <projects>/
        dev = (Path(__file__).resolve().parents[3] / "tone-player" /
               "dist" / "TonePlayer")
        candidates = [dev]
    for exe in candidates:
        if exe.is_file() and os.access(exe, os.X_OK):
            return exe
    raise FileNotFoundError(
        "TonePlayer executable not found"
        f" (tried: {', '.join(str(c) for c in candidates)})")


def settings_path(exe: Path) -> Path:
    """Mandatory settings.json next to the TonePlayer executable."""
    path = exe.resolve().parent / "settings.json"
    if not path.is_file():
        raise FileNotFoundError(
            f"settings.json is required next to TonePlayer, not found: {path}")
    return path


def launch() -> Path:
    """Start TonePlayer detached; returns the executable path.

    Raises FileNotFoundError if either the executable or the mandatory
    settings.json is missing; OSError if spawning failed.
    """
    exe = find_exe()
    settings_path(exe)                     # license to start
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    subprocess.Popen(                      # noqa: S603 -- fixed argv, no shell
        [str(exe)], cwd=str(exe.parent),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True, creationflags=flags)
    return exe


def call(name: str, *args: str) -> str:
    """Send one 'msg' call to the running TonePlayer; return its message.

    Raises RuntimeError when TonePlayer is not running or the call failed.
    """
    exe = find_exe()
    argv = [str(exe), "msg", name, *map(str, args)]
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        done = subprocess.run(             # noqa: S603 -- fixed argv, no shell
            argv, cwd=str(exe.parent), capture_output=True, text=True,
            timeout=CALL_TIMEOUT_S, creationflags=flags)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"TonePlayer msg {name}: timed out") from exc
    out = (done.stdout or "").strip()
    err = (done.stderr or "").strip()
    if done.returncode != 0:
        raise RuntimeError(f"TonePlayer msg {name}: {err or out or _SRV_HINT}")
    # The running instance answers with one JSON line {"ok", "message"}.
    try:
        data = json.loads(out.splitlines()[-1])
        if isinstance(data, dict) and isinstance(data.get("message"), str):
            if not data.get("ok"):
                raise RuntimeError(f"TonePlayer msg {name}: {data['message']}")
            return str(data["message"])
    except (ValueError, IndexError):
        pass
    return out or "ok"
