"""TonePlayer engine host for SKM.

SKM imports the companion app's Qt-free audio modules directly from
../tone-player/src (put on sys.path here), so tone playback happens in
the SKM process itself using TonePlayer's own engine
(`audio_engine.TonePlayer`: sine table + RawOutputStream). The playback
mechanism of TonePlayer is not altered: the engine, settings model and
validation are the very same code, imported; the full TonePlayer UI is
rebuilt in PySide6 by `tp_panel.py` on top of this module.

Persistent state is TonePlayer's `settings.json` (bands, levels, master
gain, output device, autoplay); it must sit next to the TonePlayer
executable: in dev the sibling repository (../tone-player/dist/), for
the frozen SKM app — next to the SKM executable (the "same folder"
deployment). Overrides: SKM_TONE_PLAYER_SRC (engine source dir),
SKM_TONE_SETTINGS (settings.json path).
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QCoreApplication  # noqa: F401 -- Qt ready check
from PySide6.QtNetwork import QLocalSocket  # noqa: F401 -- reserved: IPC later

#: Engine source directory override (dir containing audio_engine.py).
ENV_TONE_PLAYER_SRC = "SKM_TONE_PLAYER_SRC"
#: TonePlayer settings.json path override.
ENV_TONE_SETTINGS = "SKM_TONE_SETTINGS"


# ------------------------------------------------------------ engine path

def engine_src_dir() -> Path:
    """Directory with TonePlayer's Qt-free audio modules."""
    override = os.environ.get(ENV_TONE_PLAYER_SRC, "").strip()
    if override:
        return Path(override)
    # toneplayer.py -> skm/ -> src/ -> <skm repo>/ -> <projects>/
    return Path(__file__).resolve().parents[3] / "tone-player" / "src"


def _ensure_engine_importable() -> None:
    """Make `audio_engine` and friends importable (dev: sibling repo src).

    In the frozen SKM bundle the engine modules are collected by
    PyInstaller (see SKM.spec) and the FrozenImporter resolves the
    top-level names without any sys.path entry.
    """
    src = engine_src_dir()
    if (src / "audio_engine.py").is_file():
        if str(src) not in sys.path:
            sys.path.insert(0, str(src))     # engine lives there and only there
    elif not getattr(sys, "frozen", False):
        raise FileNotFoundError(
            f"TonePlayer engine sources not found in {src} "
            f"(set {ENV_TONE_PLAYER_SRC})")


# -------------------------------------------------------------- settings

def settings_path() -> Path:
    """TonePlayer's settings.json (bands, levels, master gain, output)."""
    override = os.environ.get(ENV_TONE_SETTINGS, "").strip()
    if override:
        path = Path(override)
    elif getattr(sys, "frozen", False):
        path = Path(sys.executable).resolve().parent / "settings.json"
    else:
        # toneplayer.py -> skm/ -> src/ -> <skm repo>/ -> <projects>/
        path = (Path(__file__).resolve().parents[3] / "tone-player" /
                "dist" / "settings.json")
    if not path.is_file():
        raise FileNotFoundError(
            f"TonePlayer settings.json is required, not found: {path}")
    return path


# ------------------------------------------------------------- integration

@dataclass(slots=True)
class Engine:
    """Shared playback engine: one TonePlayer instance for the whole app."""

    player: object   # audio_engine.TonePlayer
    config: object   # models.ToneConfig
    settings: object # models.Settings (frozen dataclass, replaced on edits)


_engine: Engine | None = None
_engine_error: str | None = None


def _build_engine() -> Engine:
    """Create the engine exactly as TonePlayer's MainWindow does."""
    _ensure_engine_importable()
    # Imports happen here, after sys.path preparation (dev build).
    from audio_engine import (  # type: ignore
        TonePlayer,  # type: ignore[import-not-found]
        find_device,
        list_output_devices,
    )
    from models import MASTER_BASE_DB, ToneConfig  # type: ignore[import-not-found]
    from settings_store import load_settings_at_startup  # type: ignore[import-not-found]

    settings = load_settings_at_startup(settings_path())
    player = TonePlayer(
        ToneConfig.from_settings(settings),
        settings.levels,
        MASTER_BASE_DB + settings.master_gain_db,
        level_scale=settings.level_scale,
    )
    player.set_autoplay(settings.autoplay)
    devices = list_output_devices()
    configured = find_device(devices, settings.device)
    player.set_device(configured.index if configured is not None else None)
    return Engine(player=player,
                  config=ToneConfig.from_settings(settings),
                  settings=settings)


def engine() -> Engine:
    """The shared engine instance, loaded lazily; errors are remembered."""
    global _engine, _engine_error
    if _engine is None:
        try:
            _engine = _build_engine()
            _engine_error = None
        except Exception as exc:                    # noqa: BLE001
            _engine_error = f"{type(exc).__name__}: {exc}"
    if _engine is None and _engine_error is not None:
        raise RuntimeError(_engine_error)
    return _engine  # type: ignore[return-value]


def engine_error() -> str | None:
    """Deferred load error, if any (."" when the engine is fine)."""
    return _engine_error if _engine is not None else _engine_error


def apply_settings(new_settings) -> Engine:
    """Replace the whole settings set, as TonePlayer's _apply_settings."""
    from audio_engine import find_device, list_output_devices  # type: ignore
    from models import MASTER_BASE_DB, ToneConfig  # type: ignore[import-not-found]

    eng = engine()
    eng.player.stop()
    eng.settings = new_settings
    eng.config = ToneConfig.from_settings(new_settings)
    eng.player.reconfigure(eng.config, new_settings.levels,
                           level_scale=new_settings.level_scale)
    eng.player.set_master_db(MASTER_BASE_DB + new_settings.master_gain_db)
    eng.player.set_autoplay(new_settings.autoplay)
    configured = find_device(list_output_devices(), new_settings.device)
    eng.player.set_device(configured.index if configured is not None else None)
    return eng


def save_settings() -> str:
    """Persist the current settings object via TonePlayer's own writer."""
    from settings_store import save_settings  # type: ignore[import-not-found]

    eng = engine()
    save_settings(settings_path(), eng.settings)
    return "saved"


# ------------------------------------------------------------- UI actions

def start_playing() -> str:
    """Play frequencies from the settings (band 0 first)."""
    from models import PlayerState  # type: ignore[import-not-found]

    eng = engine()
    if eng.player.state is PlayerState.PLAYING:
        return f"already playing: {describe()}"
    eng.player.start(0)
    return describe()


def stop_playing() -> str:
    """Stop playback (no-op when the engine never started)."""
    from models import PlayerState  # type: ignore[import-not-found]

    if _engine is None:
        return "stopped"
    if _engine.player.state is PlayerState.IDLE:
        return "stopped"
    _engine.player.stop()
    return describe()


def describe() -> str:
    """One-line status: state, frequency, level."""

    eng = engine()
    return (f"{eng.player.state.name.lower()} "
            f"{eng.player.current_frequency:.0f} Hz "
            f"{eng.player.current_gain_db:+.1f} dB")


def shutdown() -> None:
    """Stop the audio stream at app exit (engine call is synchronous)."""
    from models import PlayerState  # type: ignore[import-not-found]

    if _engine is None:
        return
    if _engine.player.state is not PlayerState.IDLE:
        _engine.player.stop()
