"""Settings dialog for the tone generator mode.

Faithful PySide6 port of TonePlayer's settings_dialog.SettingsDialog:
equalizer scale (min/max/step), tone timing (seconds per tone, fade,
sample rate) and the band frequencies of an active preset. The
validation and the model stay TonePlayer's own code (models,
settings_store.validate_settings) — nothing added or removed, only the
Qt widgets are rebuilt on PySide6.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from skm import toneplayer

LABEL_WIDTH = 190
BUTTON_HEIGHT = 34


def _engine_modules() -> tuple[Any, Any]:
    """Return (models, settings_store) of TonePlayer (engine paths ready)."""
    toneplayer.engine()
    import models  # type: ignore[import-not-found]
    import settings_store  # type: ignore[import-not-found]

    return models, settings_store


def _section(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("sectionLabel")
    return label


def _form() -> QFormLayout:
    form = QFormLayout()
    form.setSpacing(8)
    form.setContentsMargins(0, 0, 0, 0)
    form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft
                           | Qt.AlignmentFlag.AlignVCenter)
    form.setFieldGrowthPolicy(
        QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    return form


def _row(form: QFormLayout, text: str, field: QWidget) -> None:
    label = QLabel(text)
    label.setObjectName("fieldLabel")
    label.setFixedWidth(LABEL_WIDTH)
    field.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    form.addRow(label, field)


def _double(value: float, minimum: float, maximum: float, *,
            suffix: str = "", decimals: int = 1,
            step: float = 0.5) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(minimum, maximum)
    box.setDecimals(decimals)
    box.setSingleStep(step)
    box.setSuffix(suffix)
    box.setValue(value)
    box.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
    _fix_spinbox_editor(box)
    return box


def _fix_spinbox_editor(box: QDoubleSpinBox | QSpinBox) -> None:
    """Keep the internal editor of a QSS-styled spin box visible.

    Qt 6.12 regression: a stylesheet with box-model declarations (border,
    padding, ...) on a QSpinBox/QDoubleSpinBox collapses the internal
    QLineEdit to a 1 px wide rect, so the value paints nothing. Give the
    editor an explicit sane minimum width.
    """
    box.lineEdit().setMinimumWidth(72)


def _frequencies_text(bands) -> str:
    return ", ".join(f"{band.frequency_hz:g}" for band in bands)


def _parse_frequencies(text: str) -> tuple[float, ...] | None:
    """Sort the frequencies and drop duplicates (as in the original)."""
    parts = [part for part in re.split(r"[\s,;]+", text.strip()) if part]
    if not parts:
        return None
    unique: set[float] = set()
    try:
        for part in parts:
            unique.add(round(float(part.replace(",", ".")), 3))
    except ValueError:
        return None
    if not unique:
        return None
    return tuple(sorted(unique))


def _reset_button(text: str, tooltip: str) -> QPushButton:
    button = QPushButton(text)
    button.setToolTip(tooltip)
    button.setFixedHeight(BUTTON_HEIGHT)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


class SettingsDialog(QDialog):
    """Same structure as the original dialog, PySide6 widgets."""

    def __init__(self, settings, parent=None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._bands = list(settings.bands)
        self._result = None

        is_default = settings.active_preset is None

        self.setWindowTitle(
            f"Настройки пресета «{settings.active_preset}»"
            if settings.active_preset else "Настройки")
        self.setMinimumWidth(480)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(10)

        root.addWidget(_section("Эквалайзер"))
        models, _ = _engine_modules()
        scale_form = _form()
        scale = settings.level_scale
        self.min_spin = _double(scale.min_db, models.MIN_LEVEL_SCALE_DB,
                                0.0, suffix=" дБ")
        self.max_spin = _double(scale.max_db, 0.0, models.MAX_LEVEL_SCALE_DB,
                                suffix=" дБ")
        self.step_spin = _double(
            scale.step_db,
            models.MIN_LEVEL_STEP_DB,
            models.MAX_LEVEL_STEP_DB,
            suffix=" дБ",
            decimals=2,
            step=0.1)
        _row(scale_form, "Нижняя граница", self.min_spin)
        _row(scale_form, "Верхняя граница", self.max_spin)
        _row(scale_form, "Шаг", self.step_spin)
        root.addLayout(scale_form)

        scale_buttons = QHBoxLayout()
        scale_buttons.addStretch(1)
        reset_scale = _reset_button(
            "Сбросить шкалу", "Вернуть диапазон ±10 дБ и шаг 0,5 дБ")
        reset_scale.clicked.connect(self._reset_scale)
        scale_buttons.addWidget(reset_scale)
        root.addLayout(scale_buttons)

        root.addWidget(_section("Тон"))
        tone_form = _form()
        self.seconds_spin = _double(settings.seconds_per_tone,
                                    models.MIN_SECONDS_PER_TONE,
                                    models.MAX_SECONDS_PER_TONE,
                                    suffix=" с", step=1.0)
        self.fade_spin = _double(settings.fade_ms,
                                 models.MIN_FADE_MS,
                                 models.MAX_FADE_MS,
                                 suffix=" мс", decimals=0, step=10.0)
        self.rate_spin = QSpinBox()
        self.rate_spin.setRange(models.MIN_SAMPLE_RATE, models.MAX_SAMPLE_RATE)
        self.rate_spin.setSingleStep(100)
        self.rate_spin.setSuffix(" Гц")
        self.rate_spin.setValue(settings.sample_rate)
        self.rate_spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        _fix_spinbox_editor(self.rate_spin)
        _row(tone_form, "Время на тон", self.seconds_spin)
        _row(tone_form, "Нарастание и затухание", self.fade_spin)
        _row(tone_form, "Частота дискретизации", self.rate_spin)
        root.addLayout(tone_form)

        frequencies_section_title = ("Частоты" if is_default
                                     else "Частоты пресета")
        root.addWidget(_section(frequencies_section_title))
        self.frequencies_edit = QPlainTextEdit(
            _frequencies_text(settings.bands))
        self.frequencies_edit.setFixedHeight(92)
        self.frequencies_edit.setFont(
            QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))

        if is_default:
            self.frequencies_edit.setReadOnly(True)
            self.frequencies_edit.setToolTip(
                "Частоты пресета «По умолчанию» неизменяемы.")
            hint_text = ("Частоты пресета «По умолчанию» неизменяемы. "
                         "Создайте пресет, чтобы настроить свой набор частот.")
        else:
            self.frequencies_edit.setToolTip(
                "Частоты через запятую, пробел или с новой строки.")
            hint_text = ("Через запятую, пробел или с новой строки. "
                         "Сортируются и очищаются от повторов автоматически.")

        root.addWidget(self.frequencies_edit)
        hint = QLabel(hint_text)
        hint.setObjectName("subtitleLabel")
        hint.setWordWrap(True)
        root.addWidget(hint)

        levels_row = QHBoxLayout()
        levels_row.addStretch(1)
        reset_levels = _reset_button("Сбросить уровни",
                                     "Обнулить поправки всех полос")
        if is_default:
            reset_levels.setEnabled(False)
            reset_levels.setToolTip("Уровни пресета «По умолчанию» всегда 0 дБ.")
        reset_levels.clicked.connect(self._reset_levels)
        levels_row.addWidget(reset_levels)
        root.addLayout(levels_row)

        root.addSpacing(6)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addStretch(1)
        cancel = QPushButton("Отмена")
        cancel.setFixedHeight(38)
        cancel.clicked.connect(self.reject)
        save = QPushButton("Сохранить")
        save.setObjectName("playButton")
        save.setFixedHeight(38)
        save.setDefault(True)
        save.clicked.connect(self._on_accept)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        root.addLayout(buttons)

    def settings(self):
        if self._result is None:
            raise RuntimeError("Настройки ещё не подтверждены.")
        return self._result

    def _reset_scale(self) -> None:
        self.min_spin.setValue(-10.0)
        self.max_spin.setValue(10.0)
        self.step_spin.setValue(0.5)

    def _reset_levels(self) -> None:
        models, _ = _engine_modules()
        self._bands = [models.Band(band.frequency_hz, 0.0)
                       for band in self._bands]

    def _scale(self):
        models, _ = _engine_modules()
        return models.LevelScale(
            min_db=self.min_spin.value(),
            max_db=self.max_spin.value(),
            step_db=self.step_spin.value())

    def _on_accept(self) -> None:
        models, settings_store = _engine_modules()
        import error as error_module  # type: ignore[import-not-found]

        scale = self._scale()
        if self._settings.active_preset is None:
            # Default preset: frequencies unchanged, levels stay 0.0
            bands = tuple(models.Band(b.frequency_hz, 0.0)
                          for b in self._settings.bands)
        else:
            frequencies = _parse_frequencies(
                self.frequencies_edit.toPlainText())
            if frequencies is None:
                QMessageBox.warning(
                    self, "Проверьте частоты",
                    "Введите частоты числами через запятую.")
                return
            old_levels = {round(band.frequency_hz, 3): band.level_db
                          for band in self._bands}
            bands = tuple(
                models.Band(frequency,
                            scale.clamp(old_levels.get(frequency, 0.0)))
                for frequency in frequencies)

        candidate = replace(
            self._settings,
            seconds_per_tone=self.seconds_spin.value(),
            sample_rate=self.rate_spin.value(),
            fade_ms=float(self.fade_spin.value()),
            level_scale=scale,
            bands=bands)
        try:
            settings_store.validate_settings(candidate)
        except error_module.SettingsError as exc:
            QMessageBox.warning(self, "Проверьте настройки", str(exc))
            return
        self._result = candidate
        self.accept()
