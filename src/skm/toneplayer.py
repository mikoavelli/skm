"""TonePlayer playback, integrated in-process — no TonePlayer instance.

SKM imports the companion app's audio modules directly from
../tone-player/src (put on sys.path here), so tone playback happens in
the SKM process itself using TonePlayer's own engine
(`audio_engine.TonePlayer`: sine table + RawOutputStream). The playback
mechanism of TonePlayer is not altered: the engine, settings model and
validation are the very same code, imported; only the UI glue lives in
`gui.py` (a "TonePlayer" tab with play/stop and a status readout).

Integrated code (imported from the tone-player repository, kept verbatim):
  audio_engine.py, models.py, error.py, settings_store.py

The tone bands come from TonePlayer's `settings.json`, which must sit
next to the TonePlayer executable: in dev the sibling repository
(../tone-player/dist/settings.json), for the frozen SKM app — next to
the SKM executable (the "same folder" deployment). Overrides:
SKM_TONE_PLAYER_SRC (engine source dir), SKM_TONE_SETTINGS
(settings.json path).
"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

#: Engine source directory override (dir containing audio_engine.py).
ENV_TONE_PLAYER_SRC = "SKM_TONE_PLAYER_SRC"
#: TonePlayer settings.json path override.
ENV_TONE_SETTINGS = "SKM_TONE_SETTINGS"

#: Modules imported verbatim from the tone-player repository.
_ENGINE_MODULES = ("audio_engine", "models", "error", "settings_store")

_lock = threading.Lock()
_player: object | None = None
_player_error: str | None = None


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
    PyInstaller (see SKM.spec), and FrozenImporter resolves top-level
    names even when this directory does not exist.
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


# ----------------------------------------------------------------- player

def _make_player():
    """Create the engine player exactly as TonePlayer's MainWindow does.

    MainWindow.__init__: ToneConfig.from_settings + TonePlayer(config,
    settings.levels, MASTER_BASE_DB + master_gain_db, level_scale) +
    set_autoplay(autoplay). No stream_factory — real RawOutputStream.
    """
    _ensure_engine_importable()
    # Imports happen here, after sys.path preparation (dev build).
    from audio_engine import TonePlayer  # type: ignore[import-not-found]
    from models import (  # type: ignore[import-not-found]
        MASTER_BASE_DB,
        ToneConfig,
    )
    from settings_store import load_settings_at_startup  # type: ignore

    settings = load_settings_at_startup(settings_path())
    player = TonePlayer(
        ToneConfig.from_settings(settings),
        settings.levels,
        MASTER_BASE_DB + settings.master_gain_db,
        level_scale=settings.level_scale,
    )
    player.set_autoplay(settings.autoplay)
    return player


def _player_instance():
    """The shared engine player, loaded lazily; errors are remembered."""
    global _player, _player_error
    with _lock:
        if _player is None:
            try:
                _player = _make_player()
                _player_error = None
            except Exception as exc:             # noqa: BLE001
                _player_error = str(exc)
        return _player, _player_error


# ------------------------------------------------------------- UI actions

def start_playing() -> str:
    """Play frequencies from the settings (band 0 first)."""
    player, error = _player_instance()
    if error is not None:
        raise RuntimeError(f"TonePlayer engine unavailable: {error}")
    from models import PlayerState  # type: ignore[import-not-found]

    if player.state is PlayerState.PLAYING:
        return f"already playing: {describe()}"
    player.start(0)
    return describe()


def stop_playing() -> str:
    """Stop playback (no-op when the engine never started)."""
    player, _ = _player_instance()
    if player is None:
        return "stopped"
    from models import PlayerState  # type: ignore[import-not-found]

    if player.state is PlayerState.IDLE:
        return "stopped"
    player.stop()
    return describe()


def describe() -> str:
    """One-line status for the UI label: state, frequency, level."""
    player, error = _player_instance()
    if error is not None and player is None:
        return f"engine unavailable: {error}"
    if player is None:
        return "idle"

    return (f"{player.state.name.lower()} "
            f"{player.current_frequency:.0f} Hz "
            f"{player.current_gain_db:+.1f} dB")


def shutdown() -> None:
    """Stop the audio stream at app exit (engine call is synchronous)."""
    player, _ = _player_instance()
    if player is None:
        return
    from models import PlayerState  # type: ignore[import-not-found]

    if player.state is not PlayerState.IDLE:
        player.stop()
