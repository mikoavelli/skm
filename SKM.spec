# -*- mode: python ; coding: utf-8 -*-
"""Build script for SKM.

The app only needs Qt Widgets, so unused Qt modules and plugins are stripped
from the bundled distribution: Qt6Pdf, Qt6OpenGL, Qt6Multimedia, Qt6Qml and
the rest; platform plugins plus styles and input methods are kept. This is
the main source of size reduction.

Platform plugins are OS-dependent: on Windows they are windows, windowsv3,
minimal and offscreen; on Linux — xcb, wayland, minimal and offscreen.
Wayland is kept because in a Wayland session Qt selects it by default (often
via QT_QPA_PLATFORM), and without the plugin the app would not start.
The wayland plugin ships with shell integration (xdg-shell) and window
decorations: without them Qt cannot create an actual window.

numpy is NOT excluded (unlike the tone-player reference): the measurement
engine needs it at runtime for the 65536-point FFT.

For build debugging it is handy to temporarily switch EXE(...) to
exclude_binaries=True and add a COLLECT: that produces a _internal directory
where one can see what got bundled.
"""

import os
import sys
from pathlib import Path

from PyInstaller.building.datastruct import TOC

# SPECPATH — directory of the spec file, set by PyInstaller itself; the build
# does not depend on the launch working directory.
ROOT_DIR = Path(SPECPATH).resolve()
SRC_DIR = ROOT_DIR / "src"

IS_WINDOWS = sys.platform == "win32"
ONEDIR = os.environ.get("SKM_ONEDIR") == "1"

# Qt and Python modules the app does not need.
EXCLUDED_MODULES = [
    "tkinter",
    "unittest",
    # NOTE: pydoc is NOT excluded: pyqtgraph/parametertree/interactive.py
    # imports it, and pyqtgraph is eagerly imported at startup.
    "PIL",
    # NOTE: PySide6.QtOpenGL is NOT excluded: pyqtgraph imports it eagerly
    # (pyqtgraph/Qt/OpenGLHelpers.py via PlotCurveItem), so removing it
    # breaks startup of the bundled app.
    "PySide6.QtPrintSupport",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQuickWidgets",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtSql",
    "PySide6.QtTest",
    "PySide6.QtXml",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtDesigner",
    "PySide6.QtHelp",
    "PySide6.QtUiTools",
    "PySide6.QtWebChannel",
    "PySide6.QtWebSockets",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtBluetooth",
    "PySide6.QtPositioning",
    "PySide6.QtSensors",
    "PySide6.QtSerialPort",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
]

# Qt libraries required by the app.
# Qt6XcbQpa and Qt6WaylandClient are not separate modules but parts of the
# platform plugins: without the former libqxcb.so cannot load (it pulls in the
# system Qt of a different version), without the latter libqwayland.so cannot.
QT_LIB_PREFIXES = (
    "Qt6Core",
    "Qt6Gui",
    "Qt6Widgets",
    "Qt6DBus",
    "Qt6Network",
    "Qt6XcbQpa",
    "Qt6WaylandClient",
)

# Qt6Core is linked against ICU, which sits next to the Qt libraries.
QT_LIB_SUBSTRINGS = ("icu",)

# Platform plugins kept in the build (without lib/q prefixes).
PLATFORM_PLUGINS = {
    "windows": ("windows", "windowsv3", "minimal", "offscreen"),
    "linux": ("xcb", "wayland", "minimal", "offscreen"),
}

# Qt plugin directories kept entirely.
KEPT_PLUGIN_DIRS = ("styles", "platforminputcontexts", "imageformats")

# Wayland plugins: needed only on Linux and not wholesale.
# xdg-shell is the shell integration for regular desktops; bradient and
# adwaita are window titlebar renderers (in niri and other compositors
# without server-side decorations a window would otherwise have no frame),
# qt-plugin-wayland-egl is EGL rendering.
WAYLAND_PLUGIN_FILES = {
    "wayland-shell-integration": ("xdg-shell",),
    "wayland-decoration-client": ("bradient", "adwaita"),
}

# External libraries pulled in only by the removed Qt plugins.
# X11 libraries are needed by the xcb plugin, libwayland-* by the wayland
# plugin, so they are not touched.
EXCLUDED_LIB_SUBSTRINGS = (
    "libglycin",
    "libgtk-3",
    "libgdk-3",
)


def stem_of(filename: str) -> str:
    """File name without lib/q prefixes and without the extension."""
    stem = filename
    for prefix in ("lib", "q"):
        if stem.startswith(prefix):
            stem = stem[len(prefix):]
    return stem.split(".", 1)[0]


def wanted_plugin(path: str) -> bool:
    """Keep only required plugins: platform, wayland, styles and input."""
    normalized = path.replace("\\", "/")
    if "/plugins/" not in normalized:
        return True
    directory, _, filename = normalized.split("/plugins/", 1)[1].partition("/")
    if not filename:
        return True
    if directory == "platforms":
        allowed = PLATFORM_PLUGINS["windows" if IS_WINDOWS else "linux"]
        return stem_of(filename) in allowed
    if directory in KEPT_PLUGIN_DIRS:
        return True
    if IS_WINDOWS:
        return False
    return any(item in filename for item in WAYLAND_PLUGIN_FILES.get(directory, ()))


def wanted_binary(path: str) -> bool:
    """Drop extra Qt libraries and dependencies of unneeded plugins."""
    normalized = path.replace("\\", "/")
    if not wanted_plugin(normalized):
        return False

    filename = normalized.rsplit("/", 1)[-1]
    if "Qt6/lib/" in normalized:
        stem = stem_of(filename)
        return stem.startswith(QT_LIB_PREFIXES) or any(
            item in stem for item in QT_LIB_SUBSTRINGS
        )
    return not any(item in filename for item in EXCLUDED_LIB_SUBSTRINGS)


a = Analysis(
    [str(SRC_DIR / "main.py")],
    # tone-player/src holds the integrated TonePlayer audio engine
    # (top-level modules audio_engine, models, error, settings_store).
    pathex=[str(SRC_DIR), str(ROOT_DIR.parent / "tone-player" / "src")],
    binaries=[],
    datas=[],
    hiddenimports=[
        "skm",
        "skm.constants",
        "skm.transport",
        "skm.simulator",
        "skm.protocol",
        "skm.device",
        "skm.measurement",
        "skm.tp_panel",
        "skm.tp_settings",
        "gui",
        "cli",
        "numpy",
        # TonePlayer engine, imported in-process by skm.toneplayer.
        # `presets` is imported dynamically by the tone panel functions.
        "audio_engine",
        "models",
        "error",
        "settings_store",
        "ui_text",
        "presets",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDED_MODULES,
    noarchive=False,
)

# The in-process TonePlayer engine uses sounddevice/PortAudio: pull in the
# bundled portaudio library (sounddevice ships it in _sounddevice_data).
from PyInstaller.utils.hooks import collect_dynamic_libs  # noqa: E402

_portaudio = collect_dynamic_libs("sounddevice")

dropped = len(a.binaries)
a.binaries = TOC(
    [entry for entry in a.binaries + _portaudio if wanted_binary(str(entry[0]))]
)
print(f"Dropped files: {dropped - len(a.binaries)} of {dropped}")

pyz = PYZ(a.pure)

EXE_OPTIONS = {
    "name": "SKM",
    "debug": False,
    "bootloader_ignore_signals": False,
    "strip": not IS_WINDOWS,
    # UPX disabled: compressing Qt DLLs breaks their loading and increases
    # false-positive antivirus detections; besides, windows-latest runners
    # have no UPX installed.
    "upx": False,
    "upx_exclude": [],
    "runtime_tmpdir": None,
    "console": False,
    "disable_windowed_traceback": False,
    "argv_emulation": False,
    "target_arch": None,
    "codesign_identity": None,
    "entitlements_file": None,
}

if ONEDIR:
    exe = EXE(pyz, a.scripts, exclude_binaries=True, **EXE_OPTIONS)
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=not IS_WINDOWS,
        upx=False,
        upx_exclude=[],
        name="SKM",
    )
else:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], **EXE_OPTIONS)
