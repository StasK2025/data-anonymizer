"""Мастер импорта (F-1): файл -> предпросмотр 50 строк -> столбцы ПДн -> итоги.

Кнопка завершения мастера — «Анонимизировать»; сохранение результата main window
выполняет как <имя>__anon.<расширение>.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QWizard,
    QWizardPage,
)

from src.domain.models import ColumnSuggestion, PiiType, TableData
from src.infrastructure import io_tables

_PREVIEW_ROWS = 50  # F-1: предпросмотр 50 строк


def _pii_combo_items() -> list[tuple[str, Optional[PiiType]]]:
    """Пункты выпадающего списка типов ПДн: (заголовок, тип или None)."""
    items: list[tuple[str, Optional[PiiType]]] = [("Нет", None)]
    for pii in PiiType:
        items.append((pii.title, pii))
    return items


class ImportWizard(QWizard):
    """Пошаговый мастер импорта и анонимизации."""

    def __init__(self, project_name: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Мастер импорта и анонимизации")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setButtonText(QWizard.WizardButton.FinishButton, "Анонимизировать")

        self.table: Optional[TableData] = None        # прочитанная таблица
        self.source_path: Optional[Path] = None       # путь исходного файла
        self.sheet_name: Optional[str] = None         # лист/таблица внутри файла
        self.columns: dict[int, PiiType] = {}         # выбранные столбцы и типы

        self.setPage(0, FilePage(self, project_name))
        self.setPage(1, PreviewPage(self))
        self.setPage(2, ColumnsPage(self))
        self.setPage(3, SummaryPage(self))


class FilePage(QWizardPage):
    """Шаг 1: выбор файла (CSV/XLSX/XLS/JSON/SQLite) и листа/таблицы."""

    def __init__(self, wizard: ImportWizard, project_name: str) -> None:
        super().__init__()
        self._wizard = wizard
        self.setTitle("Шаг 1. Файл")
        self.setSubTitle(f"Проект «{project_name}»: выберите исходную таблицу (исходник не изменяется)")

        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("Путь к файлу: CSV, XLSX, XLS, JSON, SQLite")
        browse = QPushButton("Обзор…")
        browse.clicked.connect(self._browse)
        row.addWidget(self.path_edit)
        row.addWidget(browse)
        layout.addLayout(row)

        form = QFormLayout()
        self.sheet_combo = QComboBox()
        self.sheet_combo.currentTextChanged.connect(self._on_sheet_changed)
        self.sheet_row_label = QLabel("Лист/таблица:")
        form.addRow(self.sheet_row_label, self.sheet_combo)
        layout.addLayout(form)

        self.format_label = QLabel("")
        layout.addWidget(self.format_label)
        layout.addStretch(1)

        self.registerField("path*", self.path_edit)

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Выберите таблицу", "", io_tables.file_dialog_filter()
        )
        if not path:
            return
        self.path_edit.setText(path)
        self._reload_sheets()

    def _reload_sheets(self) -> None:
        path = self.path_edit.text().strip()
        self._wizard.sheet_name = None
        self.sheet_combo.blockSignals(True)
        self.sheet_combo.clear()
        if not path:
            self.sheet_row_label.hide()
            self.sheet_combo.hide()
            self.format_label.setText("")
            self.sheet_combo.blockSignals(False)
            return
        try:
            names = io_tables.list_table_names(path)
        except Exception:
            names = [None]
        multi = [n for n in names if n is not None]
        if multi:
            self.sheet_row_label.show()
            self.sheet_combo.show()
            self.sheet_combo.addItems(multi)
            self._wizard.sheet_name = multi[0]
        else:
            self.sheet_row_label.hide()
            self.sheet_combo.hide()
            self._wizard.sheet_name = None
        ext = Path(path).suffix.lower()
        self.format_label.setText(f"Определённый формат: <b>{ext}</b>")
        self.sheet_combo.blockSignals(False)
        self.completeChanged.emit()

    def _on_sheet_changed(self, name: str) -> None:
        self._wizard.sheet_name = name or None

    def validatePage(self) -> bool:  # noqa: N802 — имя API Qt
        """Прочитать таблицу при переходе дальше; при ошибке — понятное сообщение."""
        path = self.path_edit.text().strip()
        if not path:
            QMessageBox.warning(self, "Файл не выбран", "Укажите файл таблицы.")
            return False
        from PyQt6.QtGui import QGuiApplication

        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            table = io_tables.read_table(path, self._wizard.sheet_name)
        except Exception as exc:
            QMessageBox.warning(self, "Ошибка чтения", str(exc))
            return False
        finally:
            QGuiApplication.restoreOverrideCursor()
        self._wizard.table = table
        self._wizard.source_path = Path(path)
        return True


class PreviewPage(QWizardPage):
    """Шаг 2: предпросмотр первых 50 строк."""

    def __init__(self, wizard: ImportWizard) -> None:
        super().__init__()
        self._wizard = wizard
        self.setTitle("Шаг 2. Предпросмотр")
        self.setSubTitle("Первые 50 строк (типичный режим предпросмотра по ТЗ)")

        layout = QVBoxLayout(self)
        self.info_label = QLabel("")
        layout.addWidget(self.info_label)
        self.preview = QTableWidget()
        self.preview.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.preview)

    def initializePage(self) -> None:  # noqa: N802 — имя API Qt
        table = self._wizard.table
        if table is None:
            return
        self.info_label.setText(
            f"Всего строк: <b>{table.n_rows}</b>, столбцов: <b>{table.n_cols}</b>"
            + (f", лист/таблица: <b>{table.name}</b>" if table.name else "")
        )
        rows = min(_PREVIEW_ROWS, table.n_rows)
        self.preview.setRowCount(rows)
        self.preview.setColumnCount(table.n_cols)
        self.preview.setHorizontalHeaderLabels([str(h) for h in table.headers])
        for r in range(rows):
            row = table.rows[r]
            for c in range(table.n_cols):
                value = row[c] if c < len(row) else None
                self.preview.setItem(r, c, QTableWidgetItem("" if value is None else str(value)))
        self.preview.resizeColumnsToContents()


class ColumnsPage(QWizardPage):
    """Шаг 3: выбор столбцов с типами ПДн с учётом предложений ColumnDetector."""

    def __init__(self, wizard: ImportWizard) -> None:
        super().__init__()
        self._wizard = wizard
        self.setTitle("Шаг 3. Столбцы и типы ПДн")
        self.setSubTitle(
            "Авто-детект (заголовки -> regex -> статистика) — рекомендация; решение за вами. "
            "Подозрительные столбцы помечены «⚠», но не меняются автоматически."
        )

        layout = QVBoxLayout(self)
        buttons = QHBoxLayout()
        mark_button = QPushButton("Отметить предложенные")
        mark_button.clicked.connect(self._mark_suggested)
        clear_button = QPushButton("Снять все отметки")
        clear_button.clicked.connect(self._clear_marks)
        buttons.addWidget(mark_button)
        buttons.addWidget(clear_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(
            ["Аноним.", "Столбец", "Тип ПДн", "Уверенность", "Уровень", "Комментарий детектора"]
        )
        layout.addWidget(self.table)

        self._combos: list[QComboBox] = []
        self._checks: list[QCheckBox] = []
        self._suggestions: list[ColumnSuggestion] = []

    def initializePage(self) -> None:  # noqa: N802 — имя API Qt
        table = self._wizard.table
        if table is None:
            return
        from src.domain.column_detector import ColumnDetector

        suggestions = ColumnDetector().detect(table)
        self._suggestions = suggestions
        self._combos.clear()
        self._checks.clear()
        self.table.setRowCount(len(suggestions))

        for row_index, suggestion in enumerate(suggestions):
            check = QCheckBox()
            check.setChecked(bool(suggestion.pii_type is not None and suggestion.level <= 2))
            holder = QWidget()
            holder_layout = QVBoxLayout(holder)
            holder_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            holder_layout.setContentsMargins(0, 0, 0, 0)
            holder_layout.addWidget(check)
            self.table.setCellWidget(row_index, 0, holder)
            self._checks.append(check)

            self.table.setItem(row_index, 1, QTableWidgetItem(suggestion.header or f"Столбец {row_index + 1}"))

            combo = QComboBox()
            for title, pii in _pii_combo_items():
                combo.addItem(title, pii)
            if suggestion.pii_type is not None:
                for i, (_title, pii) in enumerate(_pii_combo_items()):
                    if pii == suggestion.pii_type:
                        combo.setCurrentIndex(i)
                        break
            else:
                # Подозрительные столбцы автоматически НЕ выбираются (F-2)
                combo.setCurrentIndex(0)
            self.table.setCellWidget(row_index, 2, combo)
            self._combos.append(combo)

            self.table.setItem(row_index, 3, QTableWidgetItem(f"{suggestion.confidence:.0%}"))
            self.table.setItem(row_index, 4, QTableWidgetItem(str(suggestion.level) if suggestion.level else "—"))
            reason = suggestion.reason
            if suggestion.suspicious:
                reason = "⚠ " + reason + " — автоматически не отмечен"
            self.table.setItem(row_index, 5, QTableWidgetItem(reason))

        self.table.resizeColumnsToContents()

    def _mark_suggested(self) -> None:
        for check, suggestion in zip(self._checks, self._suggestions):
            if suggestion.pii_type is not None and suggestion.level <= 2:
                check.setChecked(True)

    def _clear_marks(self) -> None:
        for check in self._checks:
            check.setChecked(False)

    def validatePage(self) -> bool:  # noqa: N802 — имя API Qt
        """Собрать выбранные столбцы и типы."""
        columns: dict[int, PiiType] = {}
        for idx, (check, combo) in enumerate(zip(self._checks, self._combos)):
            if not check.isChecked():
                continue
            pii = combo.currentData()
            if pii is None:
                QMessageBox.warning(
                    self, "Не выбран тип",
                    f"Для столбца «{self._suggestions[idx].header}» выберите тип ПДн "
                    "или снимите отметку.",
                )
                return False
            columns[idx] = pii
        if not columns:
            answer = QMessageBox.question(
                self, "Нет столбцов ПДн",
                "Не отмечено ни одного столбца с ПДн — таблица будет скопирована без изменений. Продолжить?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return False
        self._wizard.columns = columns
        return True


class SummaryPage(QWizardPage):
    """Шаг 4: итоги перед анонимизацией."""

    def __init__(self, wizard: ImportWizard) -> None:
        super().__init__()
        self._wizard = wizard
        self.setTitle("Шаг 4. Итоги")
        self.setSubTitle("Проверьте выбор и нажмите «Анонимизировать»")
        layout = QVBoxLayout(self)
        self.summary_label = QLabel("")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)
        layout.addStretch(1)

    def initializePage(self) -> None:  # noqa: N802 — имя API Qt
        table = self._wizard.table
        columns = self._wizard.columns
        if table is None:
            return
        lines = [
            f"Файл: <b>{self._wizard.source_path}</b>",
            f"Строк: <b>{table.n_rows}</b>, столбцов: <b>{table.n_cols}</b>",
            f"Столбцов с ПДн: <b>{len(columns)}</b>",
        ]
        by_type: dict[str, int] = {}
        for pii in columns.values():
            by_type[pii.title] = by_type.get(pii.title, 0) + 1
        if by_type:
            lines.append("Распределение по типам: " + ", ".join(f"{k} — {v}" for k, v in sorted(by_type.items())))
        suspicious_total = sum(
            1 for s in self._suggestions_all() if s.suspicious and s.index not in columns
        )
        if suspicious_total:
            lines.append(f"Подозрительных неотмеченных столбцов: <b>{suspicious_total}</b> (останутся без изменений)")
        lines.append("Результат будет сохранён в НОВЫЙ файл <имя>__anon.<расширение>; исходник не изменяется (Г-6).")
        self.summary_label.setText("<br>".join(lines))

    def _suggestions_all(self) -> list[ColumnSuggestion]:
        columns_page: ColumnsPage = self.wizard().page(2)  # type: ignore[assignment]
        return columns_page._suggestions
