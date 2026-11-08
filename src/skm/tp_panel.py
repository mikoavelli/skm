"""TonePlayer playback panel: the original screen ported to PySide6.

A faithful 1:1 port of TonePlayer's main window (main_window.py +
band_widgets.py) on top of the integrated engine (skm.toneplayer):

  - header: settings (gear) button opening the settings dialog, preset
    combo ("По умолчанию" / user presets), preset save (bookmark) and
    delete (trash) buttons, output device combo and the
    "Автовоспроизведение" toggle switch;
  - transport row: the accent play button (icon-only, 38 px) and the
    stop button — exactly the two buttons the original has;
  - playback row: big mono frequency caption + "Тон N из M",
    progress bar and "осталось ..." counter;
  - band area: master volume column (ruler + frame) | divider |
    scrolling strip of narrow (66 px) band columns — value label only
    on the selected/current column (hover/editing/focus as in the
    original), accent frame on the sounding band, painter-drawn
    band play/pause icons, keyboard control (arrows navigate, Up/Down
    nudge the focused band, Space play/pause, Enter activate).

The playback mechanism is TonePlayer's own audio engine, imported
unchanged; persistence is TonePlayer's settings.json (debounced save).

Painting/colors are adapted to the light SKM chrome; layout, geometry,
state logic and wording come from the original app (Russian product
language, English code comments).
"""

from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path
from typing import Any

from PySide6.QtCore import (
    QEvent,
    QFileSystemWatcher,
    QPointF,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QIcon,
    QKeySequence,
    QPainter,
    QPen,
    QPixmap,
    QPolygonF,
    QRegion,
    QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QScrollBar,
    QSizePolicy,
    QSlider,
    QStyle,
    QStyleOptionSlider,
    QVBoxLayout,
    QWidget,
)

from skm import toneplayer
from skm.toneplayer import Engine
from skm.tp_settings import SettingsDialog

REFRESH_MS = 50
SAVE_DELAY_MS = 600
NOTICE_MS = 3500

# Column geometry — the same figures as the original tone-player widgets.
COLUMN_WIDTH = 66
COLUMN_VALUE_HEIGHT = 20
COLUMN_FREQUENCY_HEIGHT = 18
COLUMN_PLAY_SIZE = 28
COLUMN_SPACING = 6
COLUMN_MARGIN = 4
RULER_WIDTH = 40
RULER_SPACING = 4
FRAME_RADIUS = 10

BASE_FONT_PX = 14
FREQUENCY_VALUE_PX = 36
FREQUENCY_UNIT_PX = 16
FREQUENCY_BLOCK_WIDTH = 170

SANS_FAMILIES = ("IBM Plex Sans", "Noto Sans", "Segoe UI", "Ubuntu",
                 "DejaVu Sans")
MONO_FAMILIES = ("IBM Plex Mono", "JetBrains Mono", "Noto Sans Mono",
                 "Consolas", "DejaVu Sans Mono")

# Palette adapted to the light SKM chrome (original app is dark; role for
# role the same colors, layout and behaviour untouched).
COLOR_BG = "#eef1f6"
COLOR_SURFACE = "#f7f9fc"
COLOR_SURFACE_HOVER = "#e3edf8"
COLOR_BORDER = "#c3cdd9"
COLOR_BORDER_HOVER = "#9fb0c0"
COLOR_TEXT = "#20303f"
COLOR_MUTED = "#7b8794"
COLOR_DISABLED = "#a3aeb9"
COLOR_TRACK = "#dee6ef"
COLOR_ACCENT = "#2f88d6"
COLOR_ACCENT_HOVER = "#3f97e4"
COLOR_ON_ACCENT = "#ffffff"
COLOR_ICON = "#4a5764"
COLOR_ICON_DISABLED = "#a7b2bd"
COLOR_SWITCH_OFF = "#c2cdd8"

PLAY_BUTTON_LOOK = {
    "start": ("Запустить", "start"),
    "pause": ("Пауза", "pause"),
    "resume": ("Продолжить", "start"),
}


def _mods() -> tuple[Any, Any, Any, Any]:
    """Return (audio_engine, models, ui_text, settings_store) of TonePlayer.

    The call chain prepares the engine import paths first.
    """
    toneplayer.engine()
    import audio_engine  # type: ignore[import-not-found]
    import models  # type: ignore[import-not-found]
    import settings_store  # type: ignore[import-not-found]
    import ui_text  # type: ignore[import-not-found]

    return audio_engine, models, ui_text, settings_store


def _fmt_level(level_db: float) -> str:
    _, _, ui_text, _ = _mods()
    return ui_text.format_db(level_db, unit=False)


def _fmt_frequency(hz: float) -> str:
    _, _, ui_text, _ = _mods()
    return ui_text.format_frequency_value(hz)


def _fmt_scale(value_db: float) -> str:
    _, _, ui_text, _ = _mods()
    return ui_text.format_scale(value_db)


def _fmt_duration(seconds: float) -> str:
    _, _, ui_text, _ = _mods()
    return ui_text.format_duration(seconds)


def _track_y(position: int, maximum: int, height: int) -> float:
    """Track height for a position (maximum at the top)."""
    ratio = position / maximum if maximum > 0 else 0.0
    return height - ratio * height


def _wheel_scroll_delta(event: QEvent) -> int:
    """Wheel gesture/touchpad to a horizontal scroll delta."""
    pixel = event.pixelDelta()
    if not pixel.isNull():
        return pixel.x() or pixel.y()
    angle = event.angleDelta()
    return angle.x() or angle.y()


# ------------------------------------------------------------------ icons

def _draw_glyph(kind: str, size: int, color: str) -> QPixmap:
    """Painter-drawn glyphs of the original app (same shapes)."""
    ratio = 2
    pixmap = QPixmap(size * ratio, size * ratio)
    pixmap.setDevicePixelRatio(float(ratio))
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(size / 24, size / 24)
    qcolor = QColor(color)

    if kind == "settings":
        painter.setPen(QPen(qcolor, 2.0, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap,
                            Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(12.0, 12.0), 4.0, 4.0)
        for angle in range(0, 360, 45):
            radians = math.radians(angle)
            painter.drawLine(
                QPointF(12.0 + 6.5 * math.cos(radians),
                        12.0 + 6.5 * math.sin(radians)),
                QPointF(12.0 + 9.5 * math.cos(radians),
                        12.0 + 9.5 * math.sin(radians)))
    elif kind == "presetSave":
        painter.setPen(QPen(qcolor, 1.9, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap,
                            Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPolygon(QPolygonF([
            QPointF(7.0, 4.0), QPointF(17.0, 4.0), QPointF(17.0, 20.0),
            QPointF(12.0, 15.5), QPointF(7.0, 20.0)]))
    elif kind == "delete":
        painter.setPen(QPen(qcolor, 1.8, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap,
                            Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawLine(QPointF(5.0, 7.0), QPointF(19.0, 7.0))
        painter.drawLine(QPointF(9.0, 4.0), QPointF(15.0, 4.0))
        painter.drawRoundedRect(QRectF(7.0, 7.0, 10.0, 13.0), 2.0, 2.0)
        painter.drawLine(QPointF(10.0, 10.0), QPointF(10.0, 17.0))
        painter.drawLine(QPointF(14.0, 10.0), QPointF(14.0, 17.0))
    else:
        glyph = ("start" if kind == "bandStart" else
                 "pause" if kind == "bandPause" else kind)
        painter.setBrush(qcolor)
        if glyph == "start":
            painter.setPen(QPen(qcolor, 1.5, Qt.PenStyle.SolidLine,
                                Qt.PenCapStyle.RoundCap,
                                Qt.PenJoinStyle.RoundJoin))
            painter.drawPolygon(QPolygonF(
                [QPointF(7.5, 5), QPointF(7.5, 19), QPointF(19.5, 12)]))
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            if glyph == "pause":
                painter.drawRoundedRect(QRectF(6, 4, 4, 16), 1, 1)
                painter.drawRoundedRect(QRectF(14, 4, 4, 16), 1, 1)
            elif glyph == "stop":
                painter.drawRoundedRect(QRectF(5, 5, 14, 14), 2, 2)
    painter.end()
    return pixmap


def _make_icon(kind: str, size: int, normal: str, disabled: str) -> QIcon:
    icon = QIcon()
    icon.addPixmap(_draw_glyph(kind, size, normal), QIcon.Mode.Normal)
    icon.addPixmap(_draw_glyph(kind, size, disabled), QIcon.Mode.Disabled)
    return icon


def make_icons() -> dict[str, QIcon]:
    """The icon set of the original app."""
    return {
        "start": _make_icon("start", 18, COLOR_ON_ACCENT, COLOR_DISABLED),
        "pause": _make_icon("pause", 18, COLOR_ON_ACCENT, COLOR_DISABLED),
        "stop": _make_icon("stop", 18, COLOR_TEXT, COLOR_DISABLED),
        "settings": _make_icon("settings", 20, COLOR_ICON,
                               COLOR_ICON_DISABLED),
        "presetSave": _make_icon("presetSave", 18, COLOR_ICON,
                                 COLOR_ICON_DISABLED),
        "delete": _make_icon("delete", 18, COLOR_ICON, COLOR_ICON_DISABLED),
        "bandStart": _make_icon("bandStart", 14, COLOR_ICON,
                                COLOR_ICON_DISABLED),
        "bandPause": _make_icon("bandPause", 14, COLOR_ICON,
                                COLOR_ICON_DISABLED),
    }


def _pick_font_family(candidates: tuple[str, ...], fallback: str) -> str:
    available = set(QFontDatabase.families())
    for name in candidates:
        if name in available:
            return name
    return fallback


# ------------------------------------------------------------- stylesheet

_STYLESHEET = f"""
QDialog {{
    background-color: {COLOR_BG};
}}
TonePlayerPanel {{
    background: {COLOR_BG};
}}
QWidget {{
    color: {COLOR_TEXT};
}}
QToolTip {{
    background-color: {COLOR_SURFACE};
    color: {COLOR_TEXT};
    border: 1px solid {COLOR_BORDER};
    padding: 4px 6px;
}}
QLabel {{
    background: transparent;
}}
QLabel#captionLabel, QLabel#subtitleLabel,
QLabel#statusLabel, QLabel#bandValue, QLabel#bandFrequency,
QLabel#fieldLabel {{
    color: {COLOR_MUTED};
}}
QLabel#subtitleLabel, QLabel#statusLabel {{ font-size: 13px; }}
QLabel#captionLabel, QLabel#fieldLabel {{ font-size: 13px; }}
QLabel#sectionLabel {{
    color: {COLOR_TEXT};
    font-size: 16px;
    font-weight: 600;
    padding-top: 6px;
}}
QLabel#bandValue {{ font-size: 12px; }}
QLabel#bandFrequency {{ font-size: 11px; }}

QFrame#divider {{ background-color: {COLOR_BORDER}; }}
QScrollArea {{ background: transparent; border: none; }}
BandStrip {{ background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}

QPushButton {{
    background-color: transparent;
    border: 1px solid {COLOR_BORDER};
    border-radius: 12px;
    padding: 0 12px;
    font-size: 16px;
    font-weight: 500;
}}
QPushButton:hover:enabled {{
    background-color: {COLOR_SURFACE};
    border-color: {COLOR_BORDER_HOVER};
}}
QPushButton:pressed:enabled {{ background-color: {COLOR_TRACK}; }}
QPushButton:focus {{ border-color: {COLOR_ACCENT}; }}
QPushButton:disabled {{ color: {COLOR_DISABLED}; }}
QPushButton#navButton {{
    background-color: {COLOR_SURFACE};
    padding: 0;
}}
QPushButton#navButton:hover:enabled {{
    background-color: {COLOR_SURFACE_HOVER};
}}
QPushButton#navButton:pressed:enabled {{ background-color: {COLOR_TRACK}; }}
QPushButton#navButton:disabled {{ background-color: transparent; }}
QPushButton#bandPlay {{
    background-color: transparent;
    border: none;
    border-radius: 14px;
    padding: 0;
}}
QPushButton#bandPlay:hover:enabled {{
    background-color: {COLOR_TRACK};
}}
QPushButton#playButton {{
    background-color: {COLOR_ACCENT};
    color: {COLOR_ON_ACCENT};
    border: 1px solid {COLOR_ACCENT};
    font-size: 17px;
    font-weight: 600;
}}
QPushButton#playButton:hover:enabled {{
    background-color: {COLOR_ACCENT_HOVER};
    border-color: {COLOR_ACCENT_HOVER};
}}
QPushButton#playButton:pressed:enabled {{
    background-color: {COLOR_ACCENT};
}}
QPushButton#playButton:focus {{ border: 2px solid {COLOR_TEXT}; }}
QPushButton#playButton:disabled {{
    background-color: {COLOR_SURFACE};
    color: {COLOR_DISABLED};
    border: 1px solid {COLOR_BORDER};
}}

QProgressBar {{
    border: none;
    border-radius: 3px;
    background-color: {COLOR_TRACK};
}}
QProgressBar::chunk {{
    background-color: {COLOR_ACCENT};
    border-radius: 3px;
}}

QSlider::groove:vertical {{
    width: 6px;
    background-color: {COLOR_TRACK};
    border-radius: 3px;
}}
QSlider::handle:vertical {{
    background-color: {COLOR_ACCENT};
    height: 16px;
    margin: 0 -6px;
    border-radius: 8px;
}}
QSlider::handle:vertical:hover {{ background-color: {COLOR_ACCENT_HOVER}; }}

QComboBox {{
    background-color: {COLOR_SURFACE};
    border: 1px solid {COLOR_BORDER};
    border-radius: 10px;
    padding: 0 12px;
    font-size: 14px;
}}
QComboBox:hover:enabled {{ border-color: {COLOR_BORDER_HOVER}; }}
QComboBox:focus {{ border-color: {COLOR_ACCENT}; }}
QComboBox:disabled {{ color: {COLOR_DISABLED}; }}
QComboBox::drop-down {{ border: none; width: 30px; }}
QComboBox::down-arrow {{ image: none; }}
QComboBox QAbstractItemView {{
    background-color: {COLOR_SURFACE};
    border: 1px solid {COLOR_BORDER};
    selection-background-color: {COLOR_BORDER_HOVER};
    selection-color: {COLOR_TEXT};
    outline: 0;
    padding: 4px;
}}

QDoubleSpinBox, QSpinBox {{
    background-color: {COLOR_SURFACE};
    border: 1px solid {COLOR_BORDER};
    border-radius: 8px;
    padding: 5px 8px;
    min-height: 24px;
}}
QDoubleSpinBox:focus, QSpinBox:focus {{ border-color: {COLOR_ACCENT}; }}
QPlainTextEdit {{
    background-color: {COLOR_SURFACE};
    border: 1px solid {COLOR_BORDER};
    border-radius: 8px;
    padding: 6px;
}}
QLineEdit {{
    background-color: {COLOR_SURFACE};
    color: {COLOR_TEXT};
    border: 1px solid {COLOR_BORDER};
    border-radius: 8px;
    padding: 7px 10px;
    min-height: 22px;
    selection-background-color: {COLOR_ACCENT};
    selection-color: {COLOR_ON_ACCENT};
}}
QLineEdit:focus {{ border-color: {COLOR_ACCENT}; }}

QScrollBar:horizontal {{
    background: transparent;
    height: 8px;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: {COLOR_BORDER_HOVER};
    border-radius: 4px;
    min-width: 40px;
}}
QScrollBar::handle:horizontal:hover {{ background: {COLOR_MUTED}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background: transparent;
}}
"""


# ------------------------------------------------------------------ slider

class LevelSlider(QSlider):
    """Vertical slider with the zero line and the focus ring (original)."""

    navigate_requested = Signal(int)
    activate_requested = Signal()
    scroll_requested = Signal(int)
    focus_changed = Signal(bool)

    def __init__(self, scale: Any, parent: QWidget | None = None) -> None:
        super().__init__(Qt.Orientation.Vertical, parent)
        self._scale = scale
        self.setRange(0, scale.position_count)
        self._apply_steps()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Expanding)

    def _apply_steps(self) -> None:
        self.setSingleStep(1)
        self.setPageStep(max(round(1.0 / self._scale.step_db), 1))

    def set_scale(self, scale: Any) -> None:
        """Change range/step keeping the position when it fits."""
        self._scale = scale
        self.setRange(0, scale.position_count)
        self._apply_steps()
        self.update()

    def zero_position(self) -> int:
        """Position for 0 dB."""
        return self._scale.position(0.0)

    def handle_rect(self, position: int | None = None) -> QRectF:
        """Handle rect from the style geometry for position."""
        option = QStyleOptionSlider()
        self.initStyleOption(option)                     # type: ignore[attr-defined]
        if position is not None:
            option.sliderPosition = position
            option.sliderValue = position
        style = self.style()
        if style is None:
            return QRectF()
        rect = style.subControlRect(
            QStyle.ComplexControl.CC_Slider, option,
            QStyle.SubControl.SC_SliderHandle, self)
        return QRectF(rect)

    def handle_center_y(self, position: int) -> float:
        """Handle center height for position (style geometry)."""
        rect = self.handle_rect(position)
        if rect.isNull():
            return _track_y(position, self.maximum(), self.height())
        return rect.center().y()

    def paintEvent(self, ev) -> None:                    # noqa: N802
        super().paintEvent(ev)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        handle = self.handle_rect()

        # Dashed zero line, hidden under the handle (as in the original).
        painter.save()
        if not handle.isNull():
            painter.setClipRegion(QRegion(
                self.rect()).subtracted(
                QRegion(handle.toRect().adjusted(-2, -2, 2, 2))))
        y = self.handle_center_y(self.zero_position())
        painter.setPen(QPen(QColor(COLOR_BORDER_HOVER), 1,
                            Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(8.0, y), QPointF(self.width() - 8.0, y))
        painter.restore()

        # Focus ring around the handle (as in the original).
        if self.hasFocus() and not handle.isNull():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(COLOR_TEXT), 2))
            ring = QRectF(handle).adjusted(1.5, 1.5, -1.5, -1.5)
            painter.drawRoundedRect(ring, ring.height() / 2,
                                    ring.height() / 2)

    def mouseDoubleClickEvent(self, ev) -> None:         # noqa: N802
        self.setValue(self.zero_position())
        if ev is not None:
            ev.accept()

    def contextMenuEvent(self, ev) -> None:              # noqa: N802
        self.setValue(self.zero_position())
        if ev is not None:
            ev.accept()

    def keyPressEvent(self, ev) -> None:                 # noqa: N802
        if ev is not None and ev.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            self.navigate_requested.emit(
                -1 if ev.key() == Qt.Key.Key_Left else 1)
            ev.accept()
            return
        if ev is not None and ev.key() in (Qt.Key.Key_Return,
                                           Qt.Key.Key_Enter):
            self.activate_requested.emit()
            ev.accept()
            return
        super().keyPressEvent(ev)

    def wheelEvent(self, ev) -> None:                    # noqa: N802
        if ev is None:
            return
        self.scroll_requested.emit(_wheel_scroll_delta(ev))
        ev.accept()

    def focusInEvent(self, ev) -> None:                  # noqa: N802
        super().focusInEvent(ev)
        self.focus_changed.emit(True)

    def focusOutEvent(self, ev) -> None:                 # noqa: N802
        super().focusOutEvent(ev)
        self.focus_changed.emit(False)


# ------------------------------------------------------------------- ruler

class LevelRuler(QWidget):
    """Shared level scale beside the columns: max, zero and min marks."""

    def __init__(self, scale: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scale = scale
        self._slider: LevelSlider | None = None
        self.setFixedWidth(RULER_WIDTH)
        self.setSizePolicy(QSizePolicy.Policy.Fixed,
                           QSizePolicy.Policy.Expanding)

    def set_scale(self, scale: Any) -> None:
        self._scale = scale
        self.update()

    def set_slider(self, slider: LevelSlider | None) -> None:
        self._slider = slider
        self.update()

    def paintEvent(self, ev) -> None:                    # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = QFont(self.font())
        font.setPixelSize(11)
        painter.setFont(font)

        positions = (
            (self._scale.position(self._scale.max_db),
             _fmt_scale(self._scale.max_db)),
            (self._scale.position(0.0), "0"),
            (self._scale.position(self._scale.min_db),
             _fmt_scale(self._scale.min_db)),
        )
        if self._slider is not None:
            slider_top = self._slider.mapToGlobal(
                self._slider.rect().topLeft()).y()
            ruler_top = self.mapToGlobal(self.rect().topLeft()).y()
            top = float(slider_top - ruler_top)
            y_positions = [top + self._slider.handle_center_y(position)
                           for position, _ in positions]
        else:
            y_positions = [
                _track_y(position, self._scale.position_count, self.height())
                for position, _ in positions]
        for (_, text), y in zip(positions, y_positions, strict=True):
            painter.setPen(QPen(QColor(COLOR_BORDER_HOVER), 1))
            painter.drawLine(QPointF(self.width() - 12.0, y),
                             QPointF(self.width() - 5.0, y))
            painter.setPen(QColor(COLOR_MUTED))
            label_y = min(max(y - 8.0, 0.0), max(0.0, self.height() - 16.0))
            painter.drawText(QRectF(0.0, label_y, self.width() - 15.0, 16.0),
                             int(Qt.AlignmentFlag.AlignRight
                                 | Qt.AlignmentFlag.AlignVCenter), text)


# ---------------------------------------------------------------- band strip

def _paint_column_frame(widget: QWidget, *, accent: bool) -> None:
    """Column border; accent = the sounding band (as in the original)."""
    painter = QPainter(widget)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(COLOR_SURFACE_HOVER if accent
                            else COLOR_SURFACE))
    painter.setPen(QPen(QColor(COLOR_ACCENT if accent else COLOR_BORDER), 1))
    painter.drawRoundedRect(
        QRectF(widget.rect()).adjusted(1, 1, -1, -1),
        FRAME_RADIUS, FRAME_RADIUS)
    painter.end()


class MasterFrame(QWidget):
    """Master column: the same width as a band column (original)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(COLUMN_WIDTH)
        self.setSizePolicy(QSizePolicy.Policy.Fixed,
                           QSizePolicy.Policy.Expanding)


class _BandColumn(QWidget):
    """One band column: value, vertical slider, frequency, play button."""

    def __init__(self, index: int, band: Any, scale: Any,
                 icons: dict[str, QIcon], *,
                 on_level, on_play, on_select, on_activate,
                 on_navigate, on_scroll,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.index = index
        self._scale = scale
        self._on_level = on_level
        self._on_play = on_play
        self._on_select = on_select
        self._current = False
        self._playing = False
        self._hover = False
        self._editing = False
        self._icons = icons

        self.setFixedWidth(COLUMN_WIDTH)
        self.setSizePolicy(QSizePolicy.Policy.Fixed,
                           QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(COLUMN_MARGIN, COLUMN_MARGIN,
                                  COLUMN_MARGIN, COLUMN_MARGIN)
        layout.setSpacing(COLUMN_SPACING)

        self.value_label = QLabel()
        self.value_label.setObjectName("bandValue")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.value_label.setFixedHeight(COLUMN_VALUE_HEIGHT)
        layout.addWidget(self.value_label)

        self.slider = LevelSlider(scale, self)
        self.slider.setAccessibleName(
            f"Уровень {_fmt_frequency(band.frequency_hz)} Гц")
        self.slider.setValue(scale.position(band.level_db))
        self.slider.valueChanged.connect(self._on_value_changed)
        self.slider.sliderPressed.connect(self._on_slider_pressed)
        self.slider.sliderReleased.connect(self._on_slider_released)
        self.slider.navigate_requested.connect(on_navigate)
        self.slider.scroll_requested.connect(on_scroll)
        self.slider.activate_requested.connect(
            lambda: on_activate(self.index))
        self.slider.focus_changed.connect(self._on_slider_focus_changed)
        layout.addWidget(self.slider, 1)

        self.frequency_label = QLabel(_fmt_frequency(band.frequency_hz))
        self.frequency_label.setObjectName("bandFrequency")
        self.frequency_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.frequency_label.setFixedHeight(COLUMN_FREQUENCY_HEIGHT)
        layout.addWidget(self.frequency_label)

        self.play_button = QPushButton()
        self.play_button.setObjectName("bandPlay")
        self.play_button.setFixedSize(COLUMN_PLAY_SIZE, COLUMN_PLAY_SIZE)
        self.play_button.setIcon(icons["bandStart"])
        self.play_button.setIconSize(QSize(14, 14))
        self.play_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.play_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.play_button.clicked.connect(lambda: on_play(self.index))
        layout.addWidget(self.play_button, 0, Qt.AlignmentFlag.AlignHCenter)

        self.set_level(band.level_db)
        self._update_tooltip()
        self.set_current(False, False)

    def set_level(self, level_db: float) -> None:
        """Show the level without emitting a change signal."""
        self.slider.blockSignals(True)
        self.slider.setValue(self._scale.position(level_db))
        self.slider.blockSignals(False)
        self._update_text()

    def set_current(self, current: bool, playing: bool) -> None:
        """current — selected tone column; playing — it sounds now."""
        if (current, playing) == (self._current, self._playing):
            return
        self._current = current
        self._playing = playing
        icon = (self._icons["bandPause"] if current and playing
                else self._icons["bandStart"])
        self.play_button.setIcon(icon)
        self._update_text()
        self.update()

    def set_scale(self, scale: Any) -> None:
        self._scale = scale
        self.slider.set_scale(scale)
        self._update_tooltip()

    def _level(self) -> float:
        return self._scale.at_position(self.slider.value())

    def _update_text(self) -> None:
        # Same visibility rule as the original: only the selected column
        # (or the hovered/edited/focused one) shows its value label; the
        # others stay empty so no stale numbers survive a click.
        visible = (self._current or self.slider.hasFocus()
                   or self._hover or self._editing)
        self.value_label.setText(
            _fmt_level(self._level()) if visible else "")
        self._update_tooltip()

    def _update_tooltip(self) -> None:
        text = (
            f"{self.frequency_label.text()} Гц\n"
            f"Уровень: {_fmt_level(self._level())}\n"
            "↑ ↓ — изменить, ← → — выбор ползунка\n"
            "Enter — включить воспроизведение, Пробел — пауза\n"
            "Двойной щелчок или правая кнопка — сбросить в 0 дБ"
        )
        self.setToolTip(text)
        self.slider.setToolTip(text)
        self.frequency_label.setToolTip(text)

    def _on_value_changed(self, _position: int) -> None:
        self._update_text()
        self._on_level(self.index, self._level())

    def _on_slider_pressed(self) -> None:
        self._editing = True
        self._on_select(self.index)
        self._update_text()

    def _on_slider_released(self) -> None:
        self._editing = False
        self._update_text()

    def _on_slider_focus_changed(self, _focused: bool) -> None:
        self._update_text()

    def mousePressEvent(self, ev) -> None:               # noqa: N802
        self._on_select(self.index)
        self.slider.setFocus()
        super().mousePressEvent(ev)

    def contextMenuEvent(self, ev) -> None:              # noqa: N802
        self.set_level(0.0)
        self._on_level(self.index, 0.0)
        if ev is not None:
            ev.accept()

    def enterEvent(self, ev) -> None:                    # noqa: N802
        self._hover = True
        self._update_text()
        super().enterEvent(ev)

    def leaveEvent(self, ev) -> None:                    # noqa: N802
        self._hover = False
        self._editing = False
        self._update_text()
        super().leaveEvent(ev)

    def paintEvent(self, ev) -> None:                    # noqa: N802
        if self._current:
            _paint_column_frame(self, accent=self._playing)
        super().paintEvent(ev)


class BandStrip(QWidget):
    """Strip of band columns with the shared ruler (original BandStrip)."""

    def __init__(self, scale: Any, icons: dict[str, QIcon], *,
                 on_level, on_play, on_select, on_activate,
                 on_navigate, on_scroll,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scale = scale
        self._icons = icons
        self._on_level = on_level
        self._on_play = on_play
        self._on_select = on_select
        self._on_activate = on_activate
        self._on_navigate = on_navigate
        self._on_scroll = on_scroll
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(4, 0, 8, 0)
        self._layout.setSpacing(RULER_SPACING)
        self._columns: list[_BandColumn] = []
        self.setSizePolicy(QSizePolicy.Policy.Minimum,
                           QSizePolicy.Policy.Expanding)

    @property
    def count(self) -> int:
        """Number of columns in the strip."""
        return len(self._columns)

    def set_bands(self, bands, scale: Any) -> None:
        """Rebuild the columns for a new band set."""
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # Detach fully: deleteLater alone can leave the old widget
                # alive as a stray child drawn over the fresh strip.
                widget.setParent(None)
                widget.hide()
                widget.deleteLater()
        self._columns = []
        self._scale = scale
        self.ruler = LevelRuler(scale)
        self._layout.addWidget(self.ruler)
        for index, band in enumerate(bands):
            column = _BandColumn(
                index, band, scale, self._icons,
                on_level=self._on_level, on_play=self._on_play,
                on_select=self._on_select, on_activate=self._on_activate,
                on_navigate=self._on_navigate, on_scroll=self._on_scroll)
            self._columns.append(column)
            self._layout.addWidget(column)
        if self._columns:
            self.ruler.set_slider(self._columns[0].slider)
        self._layout.addStretch(1)

    def set_current(self, index: int, playing: bool) -> None:
        for number, column in enumerate(self._columns):
            column.set_current(number == index, playing and number == index)

    def set_scale(self, scale: Any) -> None:
        self._scale = scale
        self.ruler.set_scale(scale)
        for column in self._columns:
            column.set_scale(scale)

    def column(self, index: int) -> _BandColumn:
        return self._columns[index]


class BandScrollArea(QScrollArea):
    """Scroll area of the original: wheel scrolls the strip horizontally."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def wheelEvent(self, ev) -> None:                    # noqa: N802
        if ev is None:
            return
        bar = self.horizontalScrollBar()
        if bar is not None:
            bar.setValue(bar.value() - _wheel_scroll_delta(ev))
        ev.accept()


# -------------------------------------------------------------------- switch

class ToggleSwitch(QAbstractButton):
    """The original autoplay toggle switch."""

    _TRACK_WIDTH = 48
    _TRACK_HEIGHT = 26
    _KNOB = 20
    _PAD = 3
    _RING = 2

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(self._TRACK_WIDTH + 2 * self._RING,
                          self._TRACK_HEIGHT + 2 * self._RING)

    def paintEvent(self, ev) -> None:                    # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():
            painter.setOpacity(0.5)

        checked = self.isChecked()
        track = QRectF(self._RING, self._RING, self._TRACK_WIDTH,
                       self._TRACK_HEIGHT)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(COLOR_ACCENT if checked
                                else COLOR_SWITCH_OFF))
        painter.drawRoundedRect(track, self._TRACK_HEIGHT / 2,
                                self._TRACK_HEIGHT / 2)

        knob_x = (track.right() - self._PAD - self._KNOB if checked
                  else track.left() + self._PAD)
        painter.setBrush(QColor(COLOR_ON_ACCENT if checked
                                else COLOR_MUTED))
        painter.drawEllipse(QRectF(knob_x, track.top() + self._PAD,
                                   self._KNOB, self._KNOB))

        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(COLOR_TEXT), 2))
            radius = self.height() / 2 - 1
            painter.drawRoundedRect(
                QRectF(1, 1, self.width() - 2, self.height() - 2),
                radius, radius)


class ChevronComboBox(QComboBox):
    """Combo with the hand-painted chevron of the original."""

    def paintEvent(self, ev) -> None:                    # noqa: N802
        super().paintEvent(ev)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = (COLOR_MUTED if self.isEnabled() else COLOR_ICON_DISABLED)
        painter.setPen(QPen(QColor(color), 1.8, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap,
                            Qt.PenJoinStyle.RoundJoin))
        center_x = self.width() - 20.0
        center_y = self.height() / 2
        painter.drawPolyline(QPolygonF([
            QPointF(center_x - 4, center_y - 2),
            QPointF(center_x, center_y + 2),
            QPointF(center_x + 4, center_y - 2)]))


# -------------------------------------------------------------------- panel

class TonePlayerPanel(QWidget):
    """The TonePlayer screen (original port) as a mode page."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._eng: Engine | None = None
        self._engine_error = ""
        try:
            self._eng = toneplayer.engine()
        except Exception as exc:                    # noqa: BLE001
            self._engine_error = str(exc)

        self._strip: BandStrip | None = None
        self._finishing_handled = False
        self._notice = ""
        self._save_error = ""
        self._focused = 0
        self._play_button_mode = ""
        self._last_band_index = -1
        self._devices: list[Any] = []
        self._icons = make_icons()

        self._sans_family = _pick_font_family(
            SANS_FAMILIES,
            QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont)
            .family())
        self._mono_family = _pick_font_family(
            MONO_FAMILIES,
            QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
            .family())
        base_font = QFont(self._sans_family)
        base_font.setPixelSize(BASE_FONT_PX)
        self.setFont(base_font)
        self.setStyleSheet(_STYLESHEET)

        if self._eng is not None:
            audio, _, _, _ = _mods()
            self._devices = list(audio.list_output_devices())

        self._build_ui()
        self._settings_watcher = QFileSystemWatcher(self)
        self._reload_timer = QTimer(self)
        self._reload_timer.setSingleShot(True)
        self._reload_timer.setInterval(250)
        self._reload_timer.timeout.connect(self._reload_settings)

        if self._eng is not None:
            self._refresh_presets()
            self._rebuild_bands()
            try:
                self._settings_path = toneplayer.settings_path()
                self._settings_file_bytes = self._read_settings_file()
                self._settings_watcher.addPath(str(self._settings_path))
                self._settings_watcher.fileChanged.connect(
                    self._on_settings_file_changed)
            except Exception:                       # noqa: BLE001
                self._settings_file_bytes = b""
                self._settings_path = None

            self._space_shortcut = QShortcut(
                QKeySequence(Qt.Key.Key_Space), self)
            self._space_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
            self._space_shortcut.setAutoRepeat(False)
            self._space_shortcut.activated.connect(self.play_pause)

            self._settings_shortcut = QShortcut(
                QKeySequence("Ctrl+,"), self)
            self._settings_shortcut.setContext(
                Qt.ShortcutContext.WindowShortcut)
            self._settings_shortcut.activated.connect(self._open_settings)

            self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            self.setFocus()

            self._refresh_timer = QTimer(self)
            self._refresh_timer.setInterval(REFRESH_MS)
            self._refresh_timer.timeout.connect(self._refresh)
            self._refresh_timer.start()

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(SAVE_DELAY_MS)
        self._save_timer.timeout.connect(self._save_settings)

        self._notice_timer = QTimer(self)
        self._notice_timer.setSingleShot(True)
        self._notice_timer.setInterval(NOTICE_MS)
        self._notice_timer.timeout.connect(self._clear_notice)

        if self._eng is not None:
            self._refresh()

    # ----------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        if self._eng is None:
            # Degraded mode: show what is wrong, keep the app usable.
            self.status_label = QLabel(
                f"engine unavailable: {self._engine_error}")
            self.status_label.setWordWrap(True)
            root.addWidget(self.status_label)
            return

        root.addLayout(self._build_header())
        root.addLayout(self._build_playback())
        root.addLayout(self._build_bands(), 1)

        self.status_label = QLabel()
        self.status_label.setObjectName("statusLabel")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.status_label)

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)

        self.settings_button = self._icon_button("settings", "Настройки")
        self.settings_button.clicked.connect(self._open_settings)
        row.addWidget(self.settings_button)

        self.preset_selector = ChevronComboBox()
        self.preset_selector.setFixedHeight(38)
        self.preset_selector.setMinimumWidth(150)
        self.preset_selector.setMaximumWidth(210)
        self.preset_selector.setToolTip(
            "Пресет: полосы эквалайзера и устройство вывода")
        self.preset_selector.currentIndexChanged.connect(
            self._on_preset_changed)
        row.addWidget(self.preset_selector)

        self.preset_save_button = self._icon_button("presetSave",
                                                   "Сохранить пресет")
        self.preset_save_button.clicked.connect(self._on_save_preset)
        row.addWidget(self.preset_save_button)

        self.preset_delete_button = self._icon_button("delete",
                                                     "Удалить пресет")
        self.preset_delete_button.clicked.connect(self._on_delete_preset)
        row.addWidget(self.preset_delete_button)

        row.addStretch(1)

        audio, _, _, _ = _mods()
        device_label = QLabel("Устройство:")
        device_label.setObjectName("fieldLabel")
        row.addWidget(device_label)

        self.device_selector = ChevronComboBox()
        self.device_selector.setFixedHeight(38)
        self.device_selector.setMinimumWidth(150)
        self.device_selector.setMaximumWidth(270)
        self.device_selector.setToolTip("Устройство вывода")
        self.device_selector.addItem(audio.DEFAULT_DEVICE_LABEL, None)
        for device in self._devices:
            self.device_selector.addItem(device.label, device.index)
        configured = audio.find_device(self._devices, self._eng.settings.device)
        self.device_selector.setCurrentIndex(
            0 if configured is None
            else self.device_selector.findData(configured.index))
        if configured is None and self._eng.settings.device is not None:
            self._show_notice(
                f"Устройство «{self._eng.settings.device}» не найдено,"
                " выбрано устройство по умолчанию.")
        self.device_selector.currentIndexChanged.connect(
            self._on_device_changed)
        row.addWidget(self.device_selector)

        self.autoplay_label = QLabel("Автовоспроизведение")
        self.autoplay_label.setObjectName("captionLabel")
        row.addWidget(self.autoplay_label)

        self.autoplay_button = ToggleSwitch()
        self.autoplay_button.setChecked(self._eng.settings.autoplay)
        self.autoplay_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.autoplay_button.setAccessibleName(
            self.autoplay_text(self._eng.settings.autoplay))
        self.autoplay_button.setToolTip(
            "Включено: во время воспроизведения новая частота звучит сразу.\n"
            "Выключено: частота переключается без звука.")
        self.autoplay_button.toggled.connect(self._on_autoplay_toggled)
        row.addWidget(self.autoplay_button)
        return row

    def _icon_button(self, icon_kind: str, tooltip: str) -> QPushButton:
        button = QPushButton()
        button.setObjectName("navButton")
        button.setFixedSize(38, 38)
        button.setIcon(self._icons[icon_kind])
        button.setIconSize(QSize(19, 19))
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    def _build_playback(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)

        self.play_button = QPushButton()
        self.play_button.setObjectName("playButton")
        self.play_button.setIcon(self._icons["start"])
        self.play_button.setIconSize(QSize(18, 18))
        self.play_button.setFixedSize(38, 38)
        self.play_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.play_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.play_button.setToolTip("Запустить (Пробел)")
        self.play_button.setAccessibleName("Запустить")
        self.play_button.clicked.connect(self.play_pause)
        row.addWidget(self.play_button)

        self.stop_button = self._icon_button("stop", "Остановить")
        self.stop_button.clicked.connect(self.stop)
        row.addWidget(self.stop_button)

        frequency_box = QVBoxLayout()
        frequency_box.setSpacing(0)
        self.frequency_label = QLabel()
        self.frequency_label.setTextFormat(Qt.TextFormat.RichText)
        self.frequency_label.setFixedWidth(FREQUENCY_BLOCK_WIDTH)
        self.frequency_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        frequency_box.addWidget(self.frequency_label)

        self.tone_counter_label = QLabel()
        self.tone_counter_label.setObjectName("captionLabel")
        self.tone_counter_label.setFixedWidth(FREQUENCY_BLOCK_WIDTH)
        self.tone_counter_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        frequency_box.addWidget(self.tone_counter_label)
        row.addLayout(frequency_box)

        row.addSpacing(8)
        self.tone_progress = QProgressBar()
        self.tone_progress.setRange(0, 100)
        self.tone_progress.setTextVisible(False)
        self.tone_progress.setFixedHeight(8)
        self.tone_progress.setSizePolicy(QSizePolicy.Policy.Expanding,
                                         QSizePolicy.Policy.Fixed)
        row.addWidget(self.tone_progress, 1)

        self.remaining_label = QLabel()
        mono_font = QFont(self._mono_family)
        mono_font.setPixelSize(14)
        mono_font.setWeight(QFont.Weight.DemiBold)
        self.remaining_label.setFont(mono_font)
        self.remaining_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.remaining_label.setMinimumWidth(116)
        row.addWidget(self.remaining_label)
        return row

    def _frequency_html(self, value: str, unit: str = "Гц") -> str:
        html = (
            f"<span style=\"font-family:'{self._mono_family}'; "
            f"font-size:{FREQUENCY_VALUE_PX}px; font-weight:600; "
            f"color:{COLOR_ACCENT};\">{value}</span>"
        )
        if unit:
            html += (
                f"<span style=\"font-family:'{self._sans_family}'; "
                f"font-size:{FREQUENCY_UNIT_PX}px; font-weight:500; "
                f"color:{COLOR_MUTED};\">&nbsp;{unit}</span>"
            )
        return html

    def _build_bands(self) -> QGridLayout:
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(4)

        grid.addWidget(self._build_master(), 0, 0)

        divider = QFrame()
        divider.setObjectName("divider")
        divider.setFixedWidth(1)
        grid.addWidget(divider, 0, 1, 2, 1)

        self._band_scroll = BandScrollArea()
        grid.addWidget(self._band_scroll, 0, 2)

        self._band_bar = QScrollBar(Qt.Orientation.Horizontal)
        self._band_bar.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        inner = self._band_scroll.horizontalScrollBar()
        if inner is not None:
            inner.rangeChanged.connect(self._sync_band_bar)
            inner.valueChanged.connect(self._band_bar.setValue)
            self._band_bar.valueChanged.connect(inner.setValue)
        grid.addWidget(self._band_bar, 1, 2)

        grid.setRowStretch(0, 1)
        grid.setColumnStretch(2, 1)
        return grid

    def _sync_band_bar(self) -> None:
        inner = self._band_scroll.horizontalScrollBar()
        if inner is None:
            return
        self._band_bar.setRange(inner.minimum(), inner.maximum())
        self._band_bar.setPageStep(inner.pageStep())
        self._band_bar.setSingleStep(inner.singleStep())
        self._band_bar.setValue(inner.value())

    def _build_master(self) -> QWidget:
        _, models, _, _ = _mods()
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(4, 0, 0, 0)
        row.setSpacing(RULER_SPACING)

        self.master_ruler = LevelRuler(models.MASTER_GAIN_SCALE)
        row.addWidget(self.master_ruler)

        frame = MasterFrame()
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(COLUMN_MARGIN, COLUMN_MARGIN,
                                  COLUMN_MARGIN, COLUMN_MARGIN)
        layout.setSpacing(COLUMN_SPACING)

        self.master_value_label = QLabel()
        self.master_value_label.setObjectName("bandValue")
        self.master_value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.master_value_label.setFixedHeight(COLUMN_VALUE_HEIGHT)
        layout.addWidget(self.master_value_label)

        self.master_slider = LevelSlider(models.MASTER_GAIN_SCALE)
        self.master_slider.setAccessibleName("Общая громкость")
        self.master_slider.setToolTip(
            "Общая громкость\n↑ ↓ — изменить; → — перейти к полосам")
        self.master_slider.valueChanged.connect(self._on_master_changed)
        self.master_slider.navigate_requested.connect(self._navigate)
        layout.addWidget(self.master_slider, 1)
        self.master_ruler.set_slider(self.master_slider)

        caption = QLabel("Громкость")
        caption.setObjectName("bandFrequency")
        caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        caption.setFixedHeight(COLUMN_FREQUENCY_HEIGHT)
        caption.setToolTip("Общая громкость")
        layout.addWidget(caption)

        placeholder = QWidget()
        placeholder.setFixedHeight(COLUMN_PLAY_SIZE)
        layout.addWidget(placeholder)

        row.addWidget(frame)
        self._master_frame = frame
        self._sync_master()
        return box

    # ------------------------------------------------------------ helpers
    @staticmethod
    def autoplay_text(enabled: bool) -> str:
        return ("Автовоспроизведение: "
                + ("включено" if enabled else "выключено"))

    def _current_index(self) -> int:
        return self._eng.player.tone_index if self._eng is not None else 0

    def _show_notice(self, text: str) -> None:
        self._notice = text
        if text:
            self._notice_timer.start()
        else:
            self._notice_timer.stop()

    def _clear_notice(self) -> None:
        if not self._notice:
            return
        self._notice = ""
        self._refresh()

    def _store(self, settings) -> None:
        """Record the changed settings object and schedule persistence."""
        self._eng.settings = settings
        self._save_timer.start()

    def _save_settings(self) -> None:
        if self._eng is None:
            return
        self._save_timer.stop()
        # A foreign edit wins: reload it instead of overwriting (original).
        content = self._read_settings_file()
        if content and content != self._settings_file_bytes:
            self._reload_settings()
            return
        try:
            from settings_store import save_settings  # type: ignore

            save_settings(self._settings_path, self._eng.settings)
        except Exception as exc:                    # noqa: BLE001
            self._save_error = str(exc)
        else:
            self._save_error = ""
            self._settings_file_bytes = self._read_settings_file()
            if (self._settings_path is not None
                    and self._settings_path not in
                    self._settings_watcher.files()):
                self._settings_watcher.addPath(str(self._settings_path))

    def _read_settings_file(self) -> bytes:
        try:
            return self._settings_path.read_bytes()
        except OSError:
            return b""

    def _on_settings_file_changed(self, path: str) -> None:
        if self._settings_path is None or Path(path) != self._settings_path:
            return
        files = self._settings_watcher.files()
        if Path(path) not in files:
            self._settings_watcher.addPath(str(self._settings_path))
        self._reload_timer.start()

    def _reload_settings(self) -> None:
        if self._eng is None or self._settings_path is None:
            return
        if self._settings_path not in self._settings_watcher.files():
            self._settings_watcher.addPath(str(self._settings_path))
        content = self._read_settings_file()
        if not content or content == self._settings_file_bytes:
            return
        self._save_timer.stop()
        _, _, _, settings_store = _mods()
        try:
            settings = settings_store.load_settings(self._settings_path)
        except Exception as exc:                    # noqa: BLE001
            self._show_notice(f"Не удалось перечитать настройки: {exc}")
            self._refresh()
            return
        self._settings_file_bytes = content
        if settings == self._eng.settings:
            return
        self._apply_settings(
            settings,
            notice="Настройки перечитаны из файла.",
            persist=False)

    def flush_save(self) -> None:
        """Persist pending edits at app exit."""
        if self._eng is not None and self._save_timer.isActive():
            self._save_settings()

    # ------------------------------------------------------------ actions
    def play_pause(self) -> None:
        if self._eng is None:
            return
        _, models, _, _ = _mods()
        state = self._eng.player.state
        if state is models.PlayerState.PLAYING:
            self._eng.player.pause()
            self._refresh()
        elif state is models.PlayerState.PAUSED:
            self._eng.player.resume()
            self._refresh()
        else:
            index = (0 if state is models.PlayerState.FINISHED
                     else self._get_focused_band_index())
            self._start_playback(index)

    def stop(self) -> None:
        if self._eng is None:
            return
        self._eng.player.stop()
        self._finishing_handled = False
        self._refresh()

    def _start_playback(self, index: int) -> None:
        try:
            self._eng.player.start(index)
        except Exception as exc:                    # noqa: BLE001
            QMessageBox.critical(self, "Ошибка воспроизведения", str(exc))
            return
        self._finishing_handled = False
        self._refresh()

    def _on_activate_band(self, index: int) -> None:
        _, models, _, _ = _mods()
        state = self._eng.player.state
        if state is models.PlayerState.PLAYING:
            self._start_playback(index)
            return
        self._eng.player.select(index)
        self._finishing_handled = False
        self._refresh()

    def _on_band_level(self, index: int, level_db: float) -> None:
        if self._eng is None:
            return
        self._eng.player.set_level_at(index, level_db)

    def _on_band_select(self, index: int) -> None:
        self._focused = index
        self._focus_band(index)

    def _focus_band(self, index: int) -> None:
        if self._strip is not None and index < self._strip.count:
            self._focused = index
            self._strip.column(index).slider.setFocus()
            if self._band_scroll is not None:
                self._band_scroll.ensureWidgetVisible(
                    self._strip.column(index), 48, 0)

    def _on_band_play(self, index: int) -> None:
        self._focus_band(index)
        _, models, _, _ = _mods()
        state = self._eng.player.state
        if index == self._eng.player.tone_index:
            if state is models.PlayerState.PLAYING:
                self._eng.player.pause()
                self._refresh()
                return
            if state is models.PlayerState.PAUSED:
                self._eng.player.resume()
                self._refresh()
                return
        self._start_playback(index)

    def _on_master_changed(self, position: int) -> None:
        _, models, _, _ = _mods()
        gain_db = models.MASTER_GAIN_SCALE.at_position(position)
        self._eng.player.set_master_db(models.MASTER_BASE_DB + gain_db)
        self._store(replace(self._eng.settings, master_gain_db=gain_db))
        self._refresh()

    def _on_device_changed(self, index: int) -> None:
        audio, _, _, _ = _mods()
        data = self.device_selector.itemData(index)
        device = next((item for item in self._devices
                       if item.index == data), None)
        try:
            self._eng.player.set_device(
                device.index if device is not None else None)
        except Exception:                           # noqa: BLE001 -- playing
            return
        self._show_notice("")
        self._store(replace(
            self._eng.settings,
            device=device.label if device is not None else None))
        self._refresh()

    def _on_autoplay_toggled(self, enabled: bool) -> None:
        if self._eng is None:
            return
        self._eng.player.set_autoplay(enabled)
        self.autoplay_button.setAccessibleName(self.autoplay_text(enabled))
        self._store(replace(self._eng.settings, autoplay=enabled))

    def _open_settings(self) -> None:
        if self._eng is None:
            return
        dialog = SettingsDialog(self._eng.settings, self)
        dialog.setStyleSheet(self.styleSheet())
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_settings = dialog.settings()
            active_name = self._eng.settings.active_preset
            if active_name is not None:
                new_presets = tuple(
                    replace(p, bands=new_settings.bands)
                    if p.name.casefold() == active_name.casefold() else p
                    for p in new_settings.presets)
                new_settings = replace(new_settings, presets=new_presets)
            else:
                new_settings = replace(new_settings,
                                       default_bands=new_settings.bands)
            self._apply_settings(new_settings)

    def _apply_settings(self, settings, *, notice: str = "",
                        persist: bool = True) -> None:
        """Replace the settings like the original _apply_settings."""
        toneplayer.apply_settings(settings)
        self._eng.settings = settings
        audio, _, _, _ = _mods()
        configured = audio.find_device(self._devices, settings.device)
        self._eng.player.set_device(
            configured.index if configured is not None else None)
        text = notice
        if configured is None and settings.device is not None:
            text = (f"Устройство «{settings.device}» не найдено, "
                    "выбрано устройство по умолчанию.")
        self._show_notice(text)
        self._sync_device_selector()
        self._sync_autoplay()
        self._sync_master()
        self._rebuild_bands()
        self._refresh_presets()
        if persist:
            self._store(settings)
        self._refresh()

    def _sync_device_selector(self) -> None:
        target = self._eng.player.device
        self.device_selector.blockSignals(True)
        index = (0 if target is None
                 else self.device_selector.findData(target))
        self.device_selector.setCurrentIndex(max(index, 0))
        self.device_selector.blockSignals(False)

    def _sync_autoplay(self) -> None:
        self.autoplay_button.blockSignals(True)
        self.autoplay_button.setChecked(self._eng.settings.autoplay)
        self.autoplay_button.blockSignals(False)
        self.autoplay_button.setAccessibleName(
            self.autoplay_text(self._eng.settings.autoplay))

    def _sync_master(self) -> None:
        _, models, _, _ = _mods()
        position = models.MASTER_GAIN_SCALE.position(
            self._eng.settings.master_gain_db)
        self.master_slider.blockSignals(True)
        self.master_slider.setValue(position)
        self.master_slider.blockSignals(False)
        self.master_value_label.setText(_fmt_level(
            self._eng.settings.master_gain_db))

    # ------------------------------------------------------------- presets
    def _refresh_presets(self) -> None:
        self.preset_selector.blockSignals(True)
        self.preset_selector.clear()
        self.preset_selector.addItem("По умолчанию", None)
        for preset in self._eng.settings.presets:
            self.preset_selector.addItem(preset.name, preset.name)
        if self._eng.settings.active_preset is not None:
            index = self.preset_selector.findData(
                self._eng.settings.active_preset)
            if index >= 0:
                self.preset_selector.setCurrentIndex(index)
        self.preset_selector.blockSignals(False)
        is_user_preset = self._eng.settings.active_preset is not None
        self.preset_delete_button.setEnabled(is_user_preset)
        self.settings_button.setEnabled(True)
        self.settings_button.setToolTip("Настройки")

    def _on_preset_changed(self, index: int) -> None:
        if self._eng is None:
            return
        _, models, _, _ = _mods()
        import presets  # type: ignore[import-not-found]

        data = self.preset_selector.itemData(index)
        if data is None:
            self._eng.player.stop()
            default_bands = (
                self._eng.settings.default_bands
                if self._eng.settings.default_bands
                else tuple(models.Band(b.frequency_hz, 0.0)
                           for b in self._eng.settings.bands))
            settings = replace(self._eng.settings, bands=default_bands,
                               active_preset=None)
            self._eng.settings = settings
            self._finishing_handled = False
            toneplayer.apply_settings(settings)
            self._focused = 0
            self._rebuild_bands()
            self._sync_device_selector()
            self._refresh_presets()
            self._store(settings)
            self._refresh()
            return

        name = str(data)
        available = {device.label for device in self._devices}
        try:
            application = presets.apply_preset(self._eng.settings, name,
                                               available)
        except presets.PresetError as error:
            QMessageBox.warning(self, "Пресет не применён", str(error))
            self._refresh_presets()
            return
        notice = ""
        if application.missing_device is not None:
            notice = (f"Устройство «{application.missing_device}» из пресета "
                      "не найдено, выбрано устройство по умолчанию.")
        self._apply_settings(application.settings, notice=notice)

    def _ask_preset_name(self, default: str) -> str | None:
        """The original preset-name dialog (QDialog + QLineEdit)."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Сохранить пресет")
        dialog.setMinimumWidth(400)
        dialog.setStyleSheet(self.styleSheet())

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        layout.addWidget(QLabel("Имя пресета:"))

        edit = QLineEdit(default)
        edit.setFixedHeight(38)
        edit.selectAll()
        layout.addWidget(edit)

        buttons = QDialogButtonBox()
        save = buttons.addButton("Сохранить",
                                 QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton("Отмена", QDialogButtonBox.ButtonRole.RejectRole)
        if save is not None:
            save.setDefault(True)
            save.setObjectName("playButton")
        buttons.setFixedHeight(38)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        edit.returnPressed.connect(dialog.accept)
        layout.addWidget(buttons)

        edit.setFocus()
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return edit.text()

    def _on_save_preset(self) -> None:
        if self._eng is None:
            return
        import presets  # type: ignore[import-not-found]

        default = self._eng.settings.active_preset or "Пресет"
        name = self._ask_preset_name(default)
        if name is None:
            return
        try:
            existing = presets.find_preset(self._eng.settings, name.strip())
            overwrite = False
            if existing is not None:
                answer = QMessageBox.question(
                    self, "Пресет уже существует",
                    f"Заменить пресет «{existing.name}»?",
                    QMessageBox.StandardButton.Yes
                    | QMessageBox.StandardButton.No)
                if answer != QMessageBox.StandardButton.Yes:
                    return
                overwrite = True
            current_bands = tuple(
                type(band)(band.frequency_hz, self._eng.player.level_at(i))
                for i, band in enumerate(self._eng.settings.bands))
            settings = presets.save_preset(
                self._eng.settings, name, bands=current_bands,
                overwrite=overwrite)
        except presets.PresetError as error:
            QMessageBox.warning(self, "Пресет не сохранён", str(error))
            return
        self._eng.settings = settings
        self._show_notice(f"Пресет «{settings.active_preset}» сохранён.")
        self._store(settings)
        self._refresh_presets()
        self._refresh()

    def _on_delete_preset(self) -> None:
        if self._eng is None:
            return
        import presets  # type: ignore[import-not-found]

        name = self._eng.settings.active_preset
        if name is None:
            return
        answer = QMessageBox.question(
            self, "Удалить пресет", f"Удалить пресет «{name}»?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            settings = presets.delete_preset(self._eng.settings, name)
        except presets.PresetError as error:
            QMessageBox.warning(self, "Пресет не удалён", str(error))
            return
        self._apply_settings(settings)

    # ------------------------------------------------------------- bands
    def _rebuild_bands(self) -> None:
        if self._eng is None:
            return
        focused_index: int | None = None
        focus = QApplication.focusWidget()
        if focus is not None and self._strip is not None:
            for index in range(self._strip.count):
                if focus is self._strip.column(index).slider:
                    focused_index = index
                    break
        if self._strip is not None:
            self._strip.deleteLater()
        strip = BandStrip(
            self._eng.settings.level_scale,
            self._icons,
            on_level=self._on_band_level,
            on_play=self._on_band_play,
            on_select=self._on_band_select,
            on_activate=self._on_activate_band,
            on_navigate=self._navigate,
            on_scroll=self._scroll_bands)
        strip.set_bands(self._eng.settings.bands,
                        self._eng.settings.level_scale)
        self._strip = strip
        if self._band_scroll is not None:
            self._band_scroll.setWidget(strip)
        self._columns = strip._columns          # alias for tests/tooling
        self._last_band_index = -1
        tail = len(self._eng.settings.bands) - 1
        if focused_index is not None:
            index = min(focused_index, tail)
        else:
            index = min(self._focused, tail)
        self._focused = index
        strip.column(index).slider.setFocus()
        self._sync_band_bar()

    def _scroll_bands(self, delta: int) -> None:
        bar = self._band_scroll.horizontalScrollBar()
        if bar is not None:
            bar.setValue(bar.value() - delta)

    def _get_focused_band_index(self) -> int:
        if self._strip is not None:
            focus = QApplication.focusWidget()
            for i in range(self._strip.count):
                if focus is self._strip.column(i).slider:
                    self._focused = i
                    return i
        tail = (len(self._eng.settings.bands) - 1
                if self._eng is not None else 0)
        return min(max(self._focused, 0), max(tail, 0))

    def _is_any_band_slider_focused(self) -> bool:
        if self._strip is not None:
            focus = QApplication.focusWidget()
            for i in range(self._strip.count):
                if focus is self._strip.column(i).slider:
                    return True
        return False

    # ------------------------------------------------------ keyboard
    def keyPressEvent(self, ev) -> None:                 # noqa: N802
        """Original keys: arrows navigate, Space plays/pauses."""
        if (ev is not None and self._eng is not None
                and ev.modifiers() == Qt.KeyboardModifier.NoModifier):
            key = ev.key()
            if key == Qt.Key.Key_Left:
                self._navigate(-1)
                ev.accept()
                return
            if key == Qt.Key.Key_Right:
                self._navigate(1)
                ev.accept()
                return
            if key == Qt.Key.Key_Up:
                self._nudge_active_band(1)
                ev.accept()
                return
            if key == Qt.Key.Key_Down:
                self._nudge_active_band(-1)
                ev.accept()
                return
            if key == Qt.Key.Key_Space:
                self.play_pause()
                ev.accept()
                return
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._on_activate_current()
                ev.accept()
                return
        super().keyPressEvent(ev)

    def _navigate(self, offset: int) -> None:
        """Move the slider focus (from master Right = to the bands)."""
        if self._eng is None:
            return
        if self.master_slider.hasFocus():
            if offset > 0:
                self._focus_band(self._focused)
            return
        current = self._get_focused_band_index()
        if offset < 0 and current == 0:
            focus = QApplication.focusWidget()
            first_slider = (self._strip.column(0).slider
                            if self._strip is not None and self._strip.count
                            else None)
            if focus is self or focus is first_slider:
                self.master_slider.setFocus()
                return
        tail = len(self._eng.settings.bands) - 1
        new_index = min(max(current + offset, 0), tail)
        self._focused = new_index
        self._focus_band(new_index)

    def _nudge_active_band(self, direction: int) -> None:
        """Up/Down: nudge the focused band level by one step."""
        if self._eng is None:
            return
        index = self._get_focused_band_index()
        scale = self._eng.settings.level_scale
        current = self._eng.player.level_at(index)
        level = scale.clamp(current + direction * scale.step_db)
        if level != current:
            self._on_band_level(index, level)
            if self._strip is not None and index < self._strip.count:
                self._strip.column(index).set_level(level)

    def _on_activate_current(self) -> None:
        if self._eng is None or self.master_slider.hasFocus():
            return
        self._on_activate_band(self._get_focused_band_index())

    # ------------------------------------------------------------ refresh
    def _refresh(self) -> None:
        if self._eng is None:
            self.status_label.setText(
                f"engine unavailable: {self._engine_error}")
            return
        _, models, ui_text, _ = _mods()
        player = self._eng.player
        state = player.state
        progress = player.progress()

        if state is models.PlayerState.FINISHED and not self._finishing_handled:
            self._finishing_handled = True
            player.finish()
            state = player.state
            progress = player.progress()

        self.frequency_label.setText(self._frequency_html(
            ui_text.format_frequency_value(player.current_frequency)))
        self.tone_counter_label.setText(
            f"Тон {progress.tone_index + 1} из {self._eng.config.tone_count}")
        self.remaining_label.setText(
            f"осталось {ui_text.format_duration(progress.tone_remaining)}")
        self.tone_progress.setValue(
            int(round(progress.tone_fraction * 100)))

        busy = state in (models.PlayerState.PLAYING,
                         models.PlayerState.PAUSED)
        self.stop_button.setEnabled(busy)
        self.device_selector.setEnabled(not busy)

        mode = ("pause" if state is models.PlayerState.PLAYING else
                "resume" if state is models.PlayerState.PAUSED else "start")
        if mode != self._play_button_mode:
            self._play_button_mode = mode
            label, icon_kind = PLAY_BUTTON_LOOK[mode]
            self.play_button.setIcon(self._icons[icon_kind])
            self.play_button.setToolTip(f"{label} (Пробел)")
            self.play_button.setAccessibleName(label)

        playing = state is models.PlayerState.PLAYING
        if self._strip is not None:
            self._strip.set_current(progress.tone_index, playing)
            if progress.tone_index != self._last_band_index:
                self._last_band_index = progress.tone_index
                focused_idx = self._get_focused_band_index()
                if (focused_idx == progress.tone_index
                        or not self._is_any_band_slider_focused()):
                    if progress.tone_index < self._strip.count:
                        self._band_scroll.ensureWidgetVisible(
                            self._strip.column(progress.tone_index), 48, 0)

        self.master_value_label.setText(_fmt_level(
            player.master_db - models.MASTER_BASE_DB))

        # Rulers track slider geometry live: repaint them every tick so a
        # just-settled layout never leaves a stale mark (stale-label class).
        if self._strip is not None:
            self._strip.ruler.update()
        self.master_ruler.update()

        status = player.last_status or self._save_error or self._notice
        self.status_label.setText(status)
        self.status_label.setVisible(bool(status))
