"""TonePlayer playback panel: the full app UI rebuilt in PySide6.

Mirrors the tone-player MainWindow (transport, band strips with level
sliders, master gain, device and preset selectors, autoplay, progress
and status) on top of the integrated engine (skm.toneplayer) — the
playback mechanism is TonePlayer's own audio_engine.TonePlayer code.

Persistence goes into TonePlayer's settings.json through
settings_store.save_settings (debounced), so both apps share the same
configuration file.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from skm import toneplayer
from skm.toneplayer import Engine

REFRESH_MS = 50
SAVE_DELAY_MS = 600
NOTICE_MS = 3500


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


# ------------------------------------------------------------------ band row

class _BandRow(QWidget):
    """One equalizer band: frequency, level slider, value, per-band play."""

    activated = Signal(int)
    level_changed = Signal(int, float)

    def __init__(self, index: int, frequency_hz: float, scale: Any,
                 parent=None) -> None:
        super().__init__(parent)
        self.index = index
        self.scale = scale

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.freq_label = QLabel(f"{frequency_hz:g} Hz")
        font = self.freq_label.font()
        font.setBold(True)
        font.setPointSize(12)
        self.freq_label.setFont(font)
        row.addWidget(self.freq_label, 0)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, scale.position_count)
        row.addWidget(self.slider, 1)

        self.value_label = QLabel("")
        self.value_label.setMinimumWidth(56)
        row.addWidget(self.value_label, 0)

        self.play_button = QPushButton("Play")
        self.play_button.setFixedWidth(56)
        row.addWidget(self.play_button, 0)

    # ---------------------------------------------------------------- sync
    def set_level(self, level_db: float) -> None:
        self.slider.blockSignals(True)
        self.slider.setValue(self.scale.position(level_db))
        self.slider.blockSignals(False)
        self.value_label.setText(_fmt_level(level_db))

    def set_current(self, current: bool, playing: bool) -> None:
        self.freq_label.setStyleSheet(
            "color: #3da6e6;" if current and playing else "")

    # --------------------------------------------------------- user events
    def _on_slider(self, position: int) -> None:
        level_db = self.scale.at_position(position)
        self.value_label.setText(_fmt_level(level_db))
        self.level_changed.emit(self.index, level_db)


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

        self._band_rows: list[_BandRow] = []
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
        self.btn_first = QPushButton("|<")
        self.btn_first.clicked.connect(lambda: self.activate(0))
        self.btn_prev = QPushButton("<")
        self.btn_prev.clicked.connect(self._on_prev)
        self.play_button = QPushButton("Play")
        self.play_button.clicked.connect(self.play_pause)
        self.stop_button = QPushButton("Stop")
        self.stop_button.clicked.connect(self.stop)
        self.btn_next = QPushButton(">")
        self.btn_next.clicked.connect(self._on_next)
        self.btn_last = QPushButton(">|")
        self.btn_last.clicked.connect(self._on_last)
        for widget in (self.btn_first, self.btn_prev, self.play_button,
                       self.stop_button, self.btn_next, self.btn_last):
            transport.addWidget(widget)
        self.autoplay_button = QPushButton("Autoplay: on")
        self.autoplay_button.setCheckable(True)
        self.autoplay_button.toggled.connect(self._on_autoplay)
        transport.addWidget(self.autoplay_button)
        root.addLayout(transport)

        # --- selectors -----------------------------------------------------
        form_box = QWidget()
        form = QFormLayout(form_box)
        form.setContentsMargins(0, 0, 0, 0)
        self.device_combo = QComboBox()
        for dev in audio.list_output_devices():
            self.device_combo.addItem(dev.label, dev.index)
        self.device_combo.addItem("Default", None)
        self.device_combo.currentIndexChanged.connect(self._on_device)
        form.addRow("Output device", self.device_combo)
        self.preset_combo = QComboBox()
        self.preset_combo.addItem("Default", None)
        presets = self._presets()
        for preset in presets:
            self.preset_combo.addItem(preset.name, preset.name)
        self.preset_combo.currentIndexChanged.connect(self._on_preset)
        form.addRow("Preset", self.preset_combo)
        root.addWidget(form_box)

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
        root.addWidget(self.tone_bar)

        # --- bands ---------------------------------------------------------
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        bands_host = QWidget()
        self._bands_layout = QVBoxLayout(bands_host)
        self._bands_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll.setWidget(bands_host)
        root.addWidget(self.scroll, 1)

        # --- master --------------------------------------------------------
        master_box = QGroupBox("Master gain")
        master_lay = QHBoxLayout(master_box)
        master_lay.addWidget(QLabel("Level, dB"))
        self.master_slider = QSlider(Qt.Orientation.Horizontal)
        _, models, _, _ = _mods()
        self.master_slider.setRange(0, models.MASTER_GAIN_SCALE.position_count)
        self.master_slider.valueChanged.connect(self._on_master)
        master_lay.addWidget(self.master_slider, 1)
        self.master_label = QLabel("")
        master_lay.addWidget(self.master_label)
        root.addWidget(master_box)

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
        self._focused = index
        _, models, _, _ = _mods()
        if self._eng.player.state is models.PlayerState.PLAYING:
            self._start(index)
            return
        self._eng.player.select(index)
        self._finishing_handled = False
        self._refresh()

    def _on_prev(self) -> None:
        self.activate(max(self._current_index() - 1, 0))

    def _on_next(self) -> None:
        _, models, _, _ = _mods()
        count = self._eng.config.tone_count if self._eng is not None else 1
        _ = models
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

    def _rebuild_bands(self) -> None:
        if self._eng is None:
            return
        self._band_rows = []
        while self._bands_layout.count():
            item = self._bands_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for i, band in enumerate(self._eng.settings.bands):
            row = _BandRow(i, band.frequency_hz,
                           self._eng.settings.level_scale)
            row.slider.valueChanged.connect(row._on_slider)
            row.level_changed.connect(self._on_band_level)
            row.play_button.clicked.connect(
                lambda _=False, k=i: self.activate(k))
            row.set_level(band.level_db)
            self._bands_layout.addWidget(row)
            self._band_rows.append(row)
        self._bands_layout.addStretch(1)

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
        for i, row in enumerate(self._band_rows):
            row.set_current(i == progress.tone_index, playing)
        self.master_label.setText(
            ui_text.format_db(player.master_db - models.MASTER_BASE_DB,
                              unit=False))
        status = player.last_status or self._save_error or self._notice
        self.status_label.setText(status)

    # -------------------------------------------------------------- close
    def flush_save(self) -> None:
        """Persist pending edits at app exit."""
        if self._eng is not None and self._save_timer.isActive():
            self._flush_save()
