"""TonePlayer playback panel: the full app UI rebuilt in PySide6.

Mirrors the tone-player MainWindow (transport, band strip with vertical
level sliders, master column, device and preset selectors, autoplay,
progress and status) on top of the integrated engine (skm.toneplayer) —
the playback mechanism is TonePlayer's own audio_engine.TonePlayer code.

The band strip copies the original layout: a horizontal strip of narrow
(66 px) vertical band columns next to a shared level ruler, master
column outside the scroll area, accent frame on the sounding band,
focus ring on the focused slider, keyboard control (arrows navigate,
Up/Down nudge the focused band, Space play/pause, Enter activate).

Persistence goes into TonePlayer's settings.json through
settings_store.save_settings (debounced), so both apps share the same
configuration file.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QRegion
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
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

# Palette adapted to the light Fusion theme of SKM (original app is dark;
# here only colors differ, layout and behaviour are the same).
COLOR_BORDER = "#c6cfd9"
COLOR_BORDER_HOVER = "#9fb0c0"
COLOR_SURFACE = "#eef2f7"
COLOR_SURFACE_CURRENT = "#dcebfa"
COLOR_ACCENT = "#2f88d6"
COLOR_TEXT = "#20303f"
COLOR_MUTED = "#7b8794"


def _mods() -> tuple[Any, Any, Any, Any]:
    """Return (audio_engine, models, ui_text, settings_store) of TonePlayer.

    The call chain prepares the engine import paths first.
    """
    _ = toneplayer.engine()
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


def _track_y(position: int, maximum: int, height: int) -> float:
    """Track height for a position (maximum at the top), like the original."""
    ratio = position / maximum if maximum > 0 else 0.0
    return height - ratio * height


# ------------------------------------------------------------------ slider

class LevelSlider(QSlider):
    """Vertical slider with the zero line and the focus ring of the original.

    Left/Right emit navigate_requested (band selection), Enter/Return emit
    activate_requested, the wheel asks the panel to scroll the strip;
    double click or the context menu resets the level to 0 dB.
    """

    navigate_requested = Signal(int)
    activate_requested = Signal()
    scroll_requested = Signal(int)

    def __init__(self, scale: Any, position: int | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(Qt.Orientation.Vertical, parent)
        self._scale = scale
        self.setRange(0, scale.position_count)
        if position is not None:
            self.setValue(position)
        self.setSingleStep(1)
        self.setPageStep(max(round(1.0 / max(scale.step_db, 1e-9)), 1))
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Expanding)

    def zero_position(self) -> int:
        """Division for 0 dB."""
        return self._scale.position(0.0)

    def handle_center_y(self, position: int) -> float:
        """Handle center height for a position (style geometry, like original)."""
        option = QStyleOptionSlider()
        self.initStyleOption(option)                     # type: ignore[attr-defined]
        if position is not None:
            option.sliderPosition = position
            option.sliderValue = position
        style = self.style()
        if style is None:
            return _track_y(position, self.maximum(), self.height())
        rect = style.subControlRect(
            QStyle.ComplexControl.CC_Slider, option,
            QStyle.SubControl.SC_SliderHandle, self)
        if rect.isNull():
            return _track_y(position, self.maximum(), self.height())
        return float(rect.center().y())

    def paintEvent(self, ev) -> None:                    # noqa: N802
        super().paintEvent(ev)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        option = QStyleOptionSlider()
        self.initStyleOption(option)                     # type: ignore[attr-defined]
        style = self.style()
        handle = (style.subControlRect(
            QStyle.ComplexControl.CC_Slider, option,
            QStyle.SubControl.SC_SliderHandle, self) if style else None)

        # Dashed zero line, hidden under the handle (as in the original).
        painter.save()
        if handle and not handle.isNull():
            painter.setClipRegion(
                QRegion(self.rect()).subtracted(
                    QRegion(handle.adjusted(-2, -2, 2, 2))))
        y = self.handle_center_y(self.zero_position())
        painter.setPen(QPen(QColor(COLOR_BORDER_HOVER), 1, Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(8.0, y), QPointF(self.width() - 8.0, y))
        painter.restore()

        # Focus ring around the handle (as in the original).
        if self.hasFocus() and handle and not handle.isNull():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(COLOR_ACCENT), 2))
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
        if ev is not None and ev.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.activate_requested.emit()
            ev.accept()
            return
        super().keyPressEvent(ev)

    def wheelEvent(self, ev) -> None:                    # noqa: N802
        if ev is None:
            return
        self.scroll_requested.emit(_wheel_scroll_delta(ev))
        ev.accept()


def _wheel_scroll_delta(ev) -> int:
    """Wheel gesture to a horizontal scroll delta, like the original helper."""
    pixel = ev.pixelDelta()
    if not pixel.isNull():
        return pixel.x() or pixel.y()
    angle = ev.angleDelta()
    return angle.x() or angle.y()


# ------------------------------------------------------------------- ruler

class LevelRuler(QWidget):
    """Shared level scale beside the columns: max, zero and min marks."""

    def __init__(self, scale: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scale = scale
        self._slider: LevelSlider | None = None
        self.setFixedWidth(RULER_WIDTH)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

    def set_scale(self, scale: Any) -> None:
        self._scale = scale
        self.update()

    def set_slider(self, slider: LevelSlider | None) -> None:
        self._slider = slider
        self.update()

    def paintEvent(self, ev) -> None:                    # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = painter.font()
        font.setPixelSize(11)
        painter.setFont(font)

        positions = (
            (self._scale.position(self._scale.max_db),
             _fmt_scale(self._scale.max_db)),
            (self._scale.position(0.0), "0"),
            (self._scale.position(self._scale.min_db),
             _fmt_scale(self._scale.min_db)),
        )
        if self._slider is not None and self._slider.isVisible():
            slider_top = self._slider.mapTo(self.window(), self._slider.rect().topLeft()).y()
            ruler_top = self.mapTo(self.window(), self.rect().topLeft()).y()
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
    painter.setBrush(QColor(COLOR_SURFACE_CURRENT if accent else COLOR_SURFACE))
    painter.setPen(QPen(QColor(COLOR_ACCENT if accent else COLOR_BORDER), 1))
    painter.drawRoundedRect(
        QRectF(widget.rect()).adjusted(1, 1, -1, -1),
        FRAME_RADIUS, FRAME_RADIUS)
    painter.end()


class _BandColumn(QWidget):
    """One band column: value, vertical slider, frequency, play button."""

    def __init__(self, index: int, band: Any, scale: Any, *,
                 on_level, on_play, on_select, on_activate,
                 on_navigate, on_scroll,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.index = index
        self._scale = scale
        self._on_level = on_level
        self._on_play = on_play
        self._on_select = on_select
        self._on_activate = on_activate
        self._current = False
        self._playing = False
        self._hover = False
        self._editing = False

        self.setFixedWidth(COLUMN_WIDTH)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(COLUMN_MARGIN, COLUMN_MARGIN,
                                  COLUMN_MARGIN, COLUMN_MARGIN)
        layout.setSpacing(COLUMN_SPACING)

        self.value_label = QLabel()
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.value_label.setFixedHeight(COLUMN_VALUE_HEIGHT)
        self.value_label.setStyleSheet(f"color: {COLOR_TEXT}; font-weight: 600;")
        layout.addWidget(self.value_label)

        self.slider = LevelSlider(scale, scale.position(band.level_db), self)
        self.slider.setAccessibleName(f"Level {_fmt_frequency(band.frequency_hz)} Hz")
        self.slider.valueChanged.connect(self._on_value_changed)
        self.slider.sliderPressed.connect(self._on_slider_pressed)
        self.slider.sliderReleased.connect(self._on_slider_released)
        self.slider.navigate_requested.connect(on_navigate)
        self.slider.scroll_requested.connect(on_scroll)
        self.slider.activate_requested.connect(
            lambda: self._on_activate(self.index))
        self.slider.installEventFilter(self)   # repaint value label on focus
        layout.addWidget(self.slider, 1)

        self.frequency_label = QLabel(_fmt_frequency(band.frequency_hz))
        self.frequency_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.frequency_label.setFixedHeight(COLUMN_FREQUENCY_HEIGHT)
        self.frequency_label.setStyleSheet(f"color: {COLOR_MUTED};")
        layout.addWidget(self.frequency_label)

        self.play_button = QPushButton()
        self.play_button.setFixedSize(COLUMN_PLAY_SIZE, COLUMN_PLAY_SIZE)
        self.play_button.setText("\u25B6")   # ▶
        self.play_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.play_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.play_button.clicked.connect(lambda: self._on_play(self.index))
        layout.addWidget(self.play_button, 0, Qt.AlignmentFlag.AlignHCenter)

        self.set_current(False, False)

    # --------------------------------------------------------------- sync
    def set_level(self, level_db: float) -> None:
        """Show the level without emitting a change signal (as the original)."""
        self.slider.blockSignals(True)
        self.slider.setValue(self._scale.position(level_db))
        self.slider.blockSignals(False)
        self._update_text()

    def set_current(self, current: bool, playing: bool) -> None:
        """current — this column is the selected tone; playing — it sounds."""
        if (current, playing) == (self._current, self._playing):
            return
        self._current = current
        self._playing = playing
        self.play_button.setText("\u2016" if current and playing else "\u25B6")
        self._update_text()
        self.update()

    def set_scale(self, scale: Any) -> None:
        self._scale = scale

    def _level(self) -> float:
        return self._scale.at_position(self.slider.value())

    def _update_text(self) -> None:
        visible = (self._current or self.slider.hasFocus()
                   or self._hover or self._editing)
        self.value_label.setText(
            _fmt_level(self._level()) if visible else "")

    # ---------------------------------------------------------- user events
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

    def _on_activate(self, index: int) -> None:
        self._on_activate(index)

    def eventFilter(self, obj, event) -> bool:           # noqa: N802
        """Repaint the value label when focus enters or leaves the slider."""
        if obj is self.slider and event.type() in (
                event.Type.FocusIn, event.Type.FocusOut):
            self._update_text()
        return super().eventFilter(obj, event)

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


class _BandStrip(QWidget):
    """Horizontal strip of band columns with the shared ruler (original)."""

    def __init__(self, scale: Any, *, on_level, on_play, on_select,
                 on_activate, on_navigate, on_scroll,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._on_select = on_select
        self._columns: list[_BandColumn] = []
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(4, 0, 8, 0)
        self._layout.setSpacing(RULER_SPACING)
        self.ruler = LevelRuler(scale)
        self._layout.addWidget(self.ruler)
        self._layout.addStretch(1)
        self.setSizePolicy(QSizePolicy.Policy.MinimumExpanding,
                           QSizePolicy.Policy.Expanding)

    @property
    def count(self) -> int:
        return len(self._columns)

    def set_bands(self, bands, scale: Any, *, on_level, on_play,
                  on_activate, on_navigate, on_scroll) -> None:
        """Rebuild the columns for a new band set (like the original)."""
        # clear
        self._columns = []
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._layout.setContentsMargins(4, 0, 8, 0)
        self._layout.setSpacing(RULER_SPACING)
        self.ruler = LevelRuler(scale)
        self._layout.addWidget(self.ruler)
        for index, band in enumerate(bands):
            column = _BandColumn(
                index, band, scale,
                on_level=on_level, on_play=on_play, on_select=self._on_select,
                on_activate=on_activate, on_navigate=on_navigate,
                on_scroll=on_scroll)
            self._columns.append(column)
            self._layout.addWidget(column)
        if self._columns:
            self.ruler.set_slider(self._columns[0].slider)
        self._layout.addStretch(1)

    def set_current(self, index: int, playing: bool) -> None:
        for number, column in enumerate(self._columns):
            column.set_current(number == index, playing and number == index)
        self.update()

    def set_scale(self, scale: Any) -> None:
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
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def wheelEvent(self, ev) -> None:                    # noqa: N802
        if ev is None:
            return
        bar = self.horizontalScrollBar()
        if bar is not None:
            bar.setValue(bar.value() - _wheel_scroll_delta(ev))
        ev.accept()


class _MasterFrame(QWidget):
    """Master gain column: the width of a band column (original MasterFrame)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(COLUMN_WIDTH)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)


# -------------------------------------------------------------------- panel

class TonePlayerPanel(QWidget):
    """The TonePlayer screen as a tab page of the SKM window."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._eng: Engine | None = None
        self._engine_error = ""
        try:
            self._eng = toneplayer.engine()
        except Exception as exc:                    # noqa: BLE001
            self._engine_error = str(exc)

        self._strip: _BandStrip | None = None
        self._band_scroll: BandScrollArea | None = None
        self._finishing_handled = False
        self._notice = ""
        self._save_error = ""
        self._focused = 0
        self._play_mode = ""

        self._build_ui()
        self._sync_all()
        self._rebuild_bands()

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(REFRESH_MS)
        self._refresh_timer.timeout.connect(self._refresh)
        self._refresh_timer.start()
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(SAVE_DELAY_MS)
        self._save_timer.timeout.connect(self._flush_save)
        self._notice_timer = QTimer(self)
        self._notice_timer.setSingleShot(True)
        self._notice_timer.setInterval(NOTICE_MS)
        self._notice_timer.timeout.connect(lambda: self._show_notice(""))

        self._refresh()

    # ----------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(10)
        # Mixer-style sliders (thin track + accent handle) for this tab only.
        self.setStyleSheet(
            "QSlider::groove:vertical { width: 6px; background: #dfe5ec;"
            " border-radius: 3px; }"
            "QSlider::sub-page:vertical, QSlider::add-page:vertical"
            " { background: transparent; }"
            "QSlider::handle:vertical { background: #2f88d6; height: 16px;"
            " margin: 0 -6px; border-radius: 8px; min-width: 16px; }"
            "QSlider::handle:vertical:hover { background: #3f97e4; }")
        self.status_label = QLabel("")
        root.addWidget(self.status_label)
        if self._eng is None:
            # Degraded mode: show what is wrong, keep the app usable.
            self.status_label.setWordWrap(True)
            self.status_label.setText(
                f"engine unavailable: {self._engine_error}\n"
                "TonePlayer settings.json must sit next to the TonePlayer"
                " executable; the engine sources (audio_engine.py, ...) must"
                f" be at {toneplayer.engine_src_dir()}")
            return

        audio, _, _, _ = _mods()                   # noqa: F841 -- engine ready check

        # --- transport row -------------------------------------------------
        transport = QHBoxLayout()
        transport.setSpacing(8)
        self.btn_first = QPushButton("|<")
        self.btn_first.setFixedWidth(48)
        self.btn_first.clicked.connect(lambda: self.activate(0))
        self.btn_prev = QPushButton("<")
        self.btn_prev.setFixedWidth(48)
        self.btn_prev.clicked.connect(self._on_prev)
        self.play_button = QPushButton("Play")
        self.play_button.setFixedHeight(32)
        self.play_button.setMinimumWidth(96)
        self.play_button.setStyleSheet(
            f"QPushButton {{ background-color: {COLOR_ACCENT};"
            f" color: #ffffff; border: 1px solid {COLOR_ACCENT};"
            "border-radius: 6px; padding: 0 16px; font-weight: 600; }"
            f"QPushButton:hover {{ background-color: #3f97e4;"
            f" border-color: #3f97e4; }}")
        self.play_button.clicked.connect(self.play_pause)
        self.stop_button = QPushButton("Stop")
        self.stop_button.setFixedHeight(32)
        self.stop_button.setMinimumWidth(80)
        self.stop_button.clicked.connect(self.stop)
        self.btn_next = QPushButton(">")
        self.btn_next.setFixedWidth(48)
        self.btn_next.clicked.connect(self._on_next)
        self.btn_last = QPushButton(">|")
        self.btn_last.setFixedWidth(48)
        self.btn_last.clicked.connect(self._on_last)
        for widget in (self.btn_first, self.btn_prev, self.play_button,
                       self.stop_button, self.btn_next, self.btn_last):
            widget.setFixedHeight(32)
            transport.addWidget(widget)
        self.autoplay_button = QPushButton("Autoplay: on")
        self.autoplay_button.setFixedHeight(32)
        self.autoplay_button.setCheckable(True)
        self.autoplay_button.toggled.connect(self._on_autoplay)
        transport.addWidget(self.autoplay_button)
        transport.addStretch(1)
        root.addLayout(transport)

        # --- selectors row: preset on the left, device on the right -------
        selectors = QHBoxLayout()
        selectors.setSpacing(8)
        selectors.addWidget(QLabel("Preset"))
        self.preset_combo = QComboBox()
        self.preset_combo.setFixedWidth(200)
        self.preset_combo.addItem("Default", None)
        for preset in self._presets():
            self.preset_combo.addItem(preset.name, preset.name)
        self.preset_combo.currentIndexChanged.connect(self._on_preset)
        selectors.addWidget(self.preset_combo)
        selectors.addStretch(1)
        selectors.addWidget(QLabel("Output device"))
        self.device_combo = QComboBox()
        self.device_combo.setFixedWidth(260)
        for dev in audio.list_output_devices():
            self.device_combo.addItem(dev.label, dev.index)
        self.device_combo.addItem("Default", None)
        self.device_combo.currentIndexChanged.connect(self._on_device)
        selectors.addWidget(self.device_combo)
        root.addLayout(selectors)

        # --- readouts ------------------------------------------------------
        info = QHBoxLayout()
        self.freq_label = QLabel("-")
        font = self.freq_label.font()
        font.setPointSize(18)
        font.setBold(True)
        self.freq_label.setFont(font)
        info.addWidget(self.freq_label)
        self.counter_label = QLabel("")
        info.addWidget(self.counter_label)
        self.remaining_label = QLabel("")
        info.addWidget(self.remaining_label)
        info.addStretch(1)
        root.addLayout(info)

        self.tone_bar = QProgressBar()
        self.tone_bar.setTextVisible(False)
        self.tone_bar.setFixedHeight(8)
        root.addWidget(self.tone_bar)

        # --- bands: master column | divider | scrolling band strip ---------
        bands_grid = QHBoxLayout()
        bands_grid.setSpacing(10)
        bands_grid.addWidget(self._build_master())
        divider_bands = QFrame()
        divider_bands.setFrameShape(QFrame.Shape.VLine)
        divider_bands.setFixedWidth(1)
        bands_grid.addWidget(divider_bands)
        self._band_scroll = BandScrollArea()
        bands_grid.addWidget(self._band_scroll, 1)
        root.addLayout(bands_grid, 1)

        # explicit horizontal bar under the strip (as in the original)
        self._band_bar = QScrollBar(Qt.Orientation.Horizontal)
        self._band_bar.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        inner = self._band_scroll.horizontalScrollBar()
        if inner is not None:
            inner.rangeChanged.connect(self._sync_band_bar)
            inner.valueChanged.connect(self._band_bar.setValue)
            self._band_bar.valueChanged.connect(inner.setValue)
        root.addWidget(self._band_bar)

        self.status_label.setText("")

    def _build_master(self) -> QWidget:
        """Master column: ruler + frame (value, vertical slider, caption)."""
        _, models, _, _ = _mods()
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(4, 0, 0, 0)
        row.setSpacing(RULER_SPACING)

        self.master_ruler = LevelRuler(models.MASTER_GAIN_SCALE)
        row.addWidget(self.master_ruler)

        frame = _MasterFrame()
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(COLUMN_MARGIN, COLUMN_MARGIN,
                                  COLUMN_MARGIN, COLUMN_MARGIN)
        layout.setSpacing(COLUMN_SPACING)

        self.master_label = QLabel()
        self.master_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.master_label.setFixedHeight(COLUMN_VALUE_HEIGHT)
        self.master_label.setStyleSheet(f"color: {COLOR_TEXT}; font-weight: 600;")
        layout.addWidget(self.master_label)

        self.master_slider = LevelSlider(models.MASTER_GAIN_SCALE)
        self.master_slider.setAccessibleName("Master gain")
        self.master_slider.setToolTip(
            "Master gain\nUp/Down — change; Right — go to the bands")
        self.master_slider.valueChanged.connect(self._on_master)
        self.master_slider.navigate_requested.connect(self._navigate)
        layout.addWidget(self.master_slider, 1)
        self.master_ruler.set_slider(self.master_slider)

        caption = QLabel("Master")
        caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        caption.setFixedHeight(COLUMN_FREQUENCY_HEIGHT)
        caption.setStyleSheet(f"color: {COLOR_MUTED};")
        layout.addWidget(caption)

        placeholder = QWidget()
        placeholder.setFixedHeight(COLUMN_PLAY_SIZE)
        layout.addWidget(placeholder)
        row.addWidget(frame)
        return box

    # ------------------------------------------------------------ helpers
    def _presets(self):
        """Preset tuple from the engine settings (empty when it failed)."""
        return (self._eng.settings.presets
                if self._eng is not None else ())

    def _current_index(self) -> int:
        return self._eng.player.tone_index if self._eng is not None else 0

    def _show_notice(self, text: str) -> None:
        self._notice = text
        if text:
            self._notice_timer.start()

    def _store(self, settings) -> None:
        """Record the changed settings object and schedule persistence."""
        self._eng.settings = settings
        self._save_timer.start()

    def _flush_save(self) -> None:
        if self._eng is None:
            return
        import error  # type: ignore[import-not-found]

        try:
            toneplayer.save_settings()
        except error.SettingsError as exc:
            self._save_error = str(exc)
        except Exception as exc:                    # noqa: BLE001
            self._save_error = str(exc)
        else:
            self._save_error = ""

    def _sync_band_bar(self, minimum: int, maximum: int) -> None:
        inner = self._band_scroll.horizontalScrollBar()
        if inner is None:
            return
        self._band_bar.setRange(minimum, maximum)
        self._band_bar.setPageStep(inner.pageStep())
        self._band_bar.setSingleStep(inner.singleStep())
        self._band_bar.setValue(inner.value())

    # ------------------------------------------------------------ actions
    def play_pause(self) -> None:
        _, models, _, _ = _mods()
        if self._eng is None:
            return
        player = self._eng.player
        state = player.state
        if state is models.PlayerState.PLAYING:
            player.pause()
        elif state is models.PlayerState.PAUSED:
            player.resume()
        else:
            index = 0 if state is models.PlayerState.FINISHED else self._focused
            self._start(index)
        self._refresh()

    def stop(self) -> None:
        if self._eng is None:
            return
        self._eng.player.stop()
        self._finishing_handled = False
        self._refresh()

    def _start(self, index: int) -> None:
        if self._eng is None:
            return
        try:
            self._eng.player.start(index)
        except Exception as exc:                    # noqa: BLE001
            self._show_notice(str(exc))
            return
        self._finishing_handled = False
        self._refresh()

    def activate(self, index: int) -> None:
        """Select the band; while playing it starts sounding right away."""
        if self._eng is None:
            return
        _, models, _, _ = _mods()
        if self._eng.player.state is models.PlayerState.PLAYING:
            self._start(index)
            return
        self._eng.player.select(index)
        self._finishing_handled = False
        self._refresh()

    def band_play(self, index: int) -> None:
        """Per-band play button: focuses the band and plays (initial) state."""
        if self._eng is None:
            return
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
        self._start(index)

    def _on_prev(self) -> None:
        self.activate(max(self._current_index() - 1, 0))

    def _on_next(self) -> None:
        count = self._eng.config.tone_count if self._eng is not None else 1
        self.activate(min(self._current_index() + 1, count - 1))

    def _on_last(self) -> None:
        count = self._eng.config.tone_count if self._eng is not None else 1
        self.activate(count - 1)

    def _on_autoplay(self, enabled: bool) -> None:
        if self._eng is None:
            return
        self._eng.player.set_autoplay(enabled)
        self.autoplay_button.setText("Autoplay: on" if enabled
                                     else "Autoplay: off")
        self._store(replace(self._eng.settings, autoplay=enabled))

    def _on_device(self, index: int) -> None:
        audio, _, _, _ = _mods()
        if self._eng is None:
            return
        data = self.device_combo.itemData(index)
        device = next((d for d in audio.list_output_devices()
                       if d.index == data), None)
        try:
            self._eng.player.set_device(
                device.index if device is not None else None)
        except Exception:                           # noqa: BLE001 -- playing: no-op
            return
        self._show_notice("")
        label = device.label if device is not None else None
        self._store(replace(self._eng.settings, device=label))

    def _on_preset(self, index: int) -> None:
        if self._eng is None:
            return
        data = self.preset_combo.itemData(index)
        if data is None:
            default_bands = (
                self._eng.settings.default_bands
                if self._eng.settings.default_bands
                else tuple(replace(b, level_db=0.0)
                           for b in self._eng.settings.bands))
            new_settings = replace(self._eng.settings,
                                   bands=default_bands, active_preset=None)
        else:
            preset = next(p for p in self._eng.settings.presets
                          if p.name == data)
            new_settings = replace(self._eng.settings, bands=preset.bands,
                                   active_preset=preset.name)
        toneplayer.apply_settings(new_settings)
        self._sync_all()
        self._rebuild_bands()
        self._refresh()

    def _on_band_level(self, index: int, level_db: float) -> None:
        """Runtime level edit like TonePlayer's _on_band_level: engine only."""
        if self._eng is None:
            return
        self._eng.player.set_level_at(index, level_db)

    def _on_band_select(self, index: int) -> None:
        self._focus_band(index)

    def _on_master(self, position: int) -> None:
        _, models, _, _ = _mods()
        if self._eng is None:
            return
        gain_db = models.MASTER_GAIN_SCALE.at_position(position)
        self._eng.player.set_master_db(models.MASTER_BASE_DB + gain_db)
        self._store(replace(self._eng.settings, master_gain_db=gain_db))
        self._refresh()

    # -------------------------------------------------------------- sync
    def _sync_all(self) -> None:
        if self._eng is None:
            return
        # device selector
        self.device_combo.blockSignals(True)
        target = self._eng.player.device
        pos = 0 if target is None else self.device_combo.findData(target)
        self.device_combo.setCurrentIndex(max(pos, 0))
        self.device_combo.blockSignals(False)
        # presets
        preset_combo_pos = 0
        if self._eng.settings.active_preset is not None:
            preset_combo_pos = max(
                self.preset_combo.findData(self._eng.settings.active_preset),
                0)
        self.preset_combo.blockSignals(True)
        self.preset_combo.setCurrentIndex(preset_combo_pos)
        self.preset_combo.blockSignals(False)
        # autoplay
        enabled = self._eng.player.generator.advance_allowed()
        self.autoplay_button.blockSignals(True)
        self.autoplay_button.setChecked(enabled)
        self.autoplay_button.blockSignals(False)
        self.autoplay_button.setText("Autoplay: on" if enabled
                                     else "Autoplay: off")
        # master
        _, models, _, _ = _mods()
        self.master_slider.blockSignals(True)
        self.master_slider.setValue(
            models.MASTER_GAIN_SCALE.position(
                self._eng.settings.master_gain_db))
        self.master_slider.blockSignals(False)
        self.master_label.setText(_fmt_level(
            self._eng.settings.master_gain_db))

    def _rebuild_bands(self) -> None:
        if self._eng is None:
            return
        _, models, ui_text, _ = _mods()
        _ = (models, ui_text)
        # keep the focused slider across the rebuild (as the original does)
        focused_index = None
        focus = QApplication.focusWidget()
        old_strip = self._strip
        if focus is not None and old_strip is not None:
            for i in range(old_strip.count):
                if focus is old_strip.column(i).slider:
                    focused_index = i
                    break
        strip = _BandStrip(self._eng.settings.level_scale,
                           on_level=self._on_band_level,
                           on_play=self.band_play,
                           on_select=self._on_band_select,
                           on_activate=self.activate,
                           on_navigate=self._navigate,
                           on_scroll=self._scroll_bands)
        strip.set_bands(
            self._eng.settings.bands, self._eng.settings.level_scale,
            on_level=self._on_band_level, on_play=self.band_play,
            on_activate=self.activate, on_navigate=self._navigate,
            on_scroll=self._scroll_bands)
        self._strip = strip
        if self._band_scroll is not None:
            self._band_scroll.setWidget(strip)
        self._columns = strip._columns
        if old_strip is not None:
            old_strip.deleteLater()
        self._last_band_index = -1
        if focused_index is not None:
            index = min(focused_index, len(self._eng.settings.bands) - 1)
        else:
            index = min(self._focused, len(self._eng.settings.bands) - 1)
        self._focused = index
        strip.column(index).slider.setFocus()

    def _scroll_bands(self, delta: int) -> None:
        """Wheel on a slider: scroll the strip horizontally (original)."""
        if self._band_scroll is None:
            return
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
        count = (len(self._eng.settings.bands)
                 if self._eng is not None else 1)
        return min(max(self._focused, 0), max(count - 1, 0))

    def _focus_band(self, index: int) -> None:
        if self._strip is None:
            self._focused = index
            return
        if index < self._strip.count:
            self._focused = index
            self._strip.column(index).slider.setFocus()
            if self._band_scroll is not None:
                self._band_scroll.ensureWidgetVisible(
                    self._strip.column(index), 48, 0)

    # ------------------------------------------------------ keyboard (original
    def keyPressEvent(self, ev) -> None:                 # noqa: N802
        """Original MainWindow keys: arrows navigate, Space plays/pauses."""
        if self._eng is None:
            super().keyPressEvent(ev)
            return
        if ev is not None and ev.modifiers() == Qt.KeyboardModifier.NoModifier:
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
                self._activate_current()
                ev.accept()
                return
        super().keyPressEvent(ev)

    def _navigate(self, offset: int) -> None:
        """Move the slider focus (from master Right = to the bands)."""
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
        count = (len(self._eng.settings.bands)
                 if self._eng is not None else 1)
        new_index = min(max(current + offset, 0), count - 1)
        self._focus_band(new_index)

    def _nudge_active_band(self, direction: int) -> None:
        """Up/Down: nudge the focused band level by one step (original)."""
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

    def _activate_current(self) -> None:
        if self.master_slider.hasFocus():
            return
        self.activate(self._get_focused_band_index())

    def _show_shortcut_hint(self) -> None:
        pass

    # ------------------------------------------------------------ refresh
    def _refresh(self) -> None:
        try:
            _, models, ui_text, _ = _mods()
        except Exception as exc:                    # noqa: BLE001
            self._engine_error = str(exc)
            self.status_label.setText(f"engine unavailable: {self._engine_error}")
            return
        if self._eng is None:
            self.status_label.setText(
                f"engine unavailable: {self._engine_error}")
            return
        player = self._eng.player
        progress = player.progress()
        state = player.state
        if state is models.PlayerState.FINISHED and not self._finishing_handled:
            self._finishing_handled = True
            player.finish()
            state = player.state
            progress = player.progress()
        self.freq_label.setText(
            f"{ui_text.format_frequency_value(player.current_frequency)} Hz")
        self.counter_label.setText(
            f"Tone {progress.tone_index + 1} of {self._eng.config.tone_count}")
        self.remaining_label.setText(
            f"left {ui_text.format_duration(progress.tone_remaining)}")
        self.tone_bar.setValue(int(round(progress.tone_fraction * 100)))
        self.stop_button.setEnabled(
            state in (models.PlayerState.PLAYING, models.PlayerState.PAUSED))
        mode = ("pause" if state is models.PlayerState.PLAYING else
                "resume" if state is models.PlayerState.PAUSED else "start")
        if mode != self._play_mode:
            self._play_mode = mode
            self.play_button.setText(
                {"start": "Play", "pause": "Pause", "resume": "Resume"}[mode])
        playing = state is models.PlayerState.PLAYING
        if self._strip is not None:
            self._strip.set_current(progress.tone_index, playing)
        self.master_label.setText(_fmt_level(
            self._eng.settings.master_gain_db))
        status = player.last_status or self._save_error or self._notice
        self.status_label.setText(status)

    # -------------------------------------------------------------- close
    def flush_save(self) -> None:
        """Persist pending edits at app exit."""
        if self._eng is not None and self._save_timer.isActive():
            self._flush_save()
