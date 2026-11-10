"""Мастер восстановления (F-4): пароль -> файл -> сопоставление столбцов -> политика.

Сохранение результата main window выполняет как <имя>__restored.<расширение>.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWizard,
    QWizardPage,
)

from src.application.project_service import ProjectWorkspace
from src.application.restore_service import RestorePlanColumn
from src.domain.models import TableData, UnknownPolicy
from src.infrastructure import io_tables

_CODE_PATTERN_TEXT = "коды вида ID-000001 / PH-000001"


class RestoreWizard(QWizard):
    """Мастер деанонимизации (восстановления ПДн)."""

    def __init__(
        self,
        workspace: Optional[ProjectWorkspace],
        project_names: list[str],
        parent=None,
    ) -> None:
        """workspace — уже открытый проект; если None, мастер запросит проект и пароль."""
        super().__init__(parent)
        self.setWindowTitle("Мастер восстановления ПДн")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setButtonText(QWizard.WizardButton.FinishButton, "Восстановить")

        self.workspace = workspace          # открытый проект (или None)
        self.selected_project = project_names[0] if project_names else ""
        self.password = ""
        self.table: Optional[TableData] = None
        self.source_path: Optional[Path] = None
        self.sheet_name: Optional[str] = None
        self.plan: list[RestorePlanColumn] = []
        self.policy: UnknownPolicy = UnknownPolicy.KEEP

        page_index = 0
        if workspace is None:
            self.setPage(page_index, ProjectPage(self, project_names))
            page_index += 1
        self.setPage(page_index, RestoreFilePage(self))
        self.setPage(page_index + 1, MappingPage(self))
        self.setPage(page_index + 2, RestoreSummaryPage(self))


class ProjectPage(QWizardPage):
    """Шаг: выбор проекта и ввода пароля (если проект не открыт)."""

    def __init__(self, wizard: RestoreWizard, project_names: list[str]) -> None:
        super().__init__()
        self._wizard = wizard
        self.setTitle("Шаг 1. Проект и пароль")
        self.setSubTitle("Восстановление возможно только по словарю проекта (Г-3: без пароля — никогда)")

        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(QLabel("Проект:"))
        self.project_combo = QComboBox()
        self.project_combo.addItems(project_names)
        self.project_combo.currentTextChanged.connect(self._on_project)
        row.addWidget(self.project_combo, stretch=1)
        layout.addLayout(row)

        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(QLabel("Пароль:"))
        layout.addWidget(self.password_edit)
        layout.addStretch(1)
        self.registerField("projectPassword*", self.password_edit)

    def _on_project(self, name: str) -> None:
        self._wizard.selected_project = name

    def validatePage(self) -> bool:  # noqa: N802 — имя API Qt
        self._wizard.password = self.password_edit.text()
        if not self._wizard.selected_project:
            QMessageBox.warning(self, "Ошибка", "Выберите проект.")
            return False
        if not self._wizard.password:
            QMessageBox.warning(self, "Ошибка", "Введите пароль проекта.")
            return False
        return True


class RestoreFilePage(QWizardPage):
    """Шаг: выбор переработанного (анонимного) файла."""

    def __init__(self, wizard: RestoreWizard) -> None:
        super().__init__()
        self._wizard = wizard
        self.setTitle("Шаг 2. Файл")
        self.setSubTitle("Выберите анонимную таблицу для восстановления (исходник не изменяется)")

        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("Файл CSV/XLSX/XLS/JSON/SQLite с кодами")
        browse = QPushButton("Обзор…")
        browse.clicked.connect(self._browse)
        row.addWidget(self.path_edit)
        row.addWidget(browse)
        layout.addLayout(row)

        self.sheet_combo = QComboBox()
        self.sheet_combo.currentTextChanged.connect(self._on_sheet)
        sheet_row = QHBoxLayout()
        sheet_row.addWidget(QLabel("Лист/таблица:"))
        sheet_row.addWidget(self.sheet_combo, stretch=1)
        layout.addLayout(sheet_row)

        hint = QLabel(f"Ожидаемый формат значений: {_CODE_PATTERN_TEXT}.")
        layout.addWidget(hint)
        layout.addStretch(1)
        self.registerField("restorePath*", self.path_edit)

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Файл для восстановления", "", io_tables.file_dialog_filter()
        )
        if not path:
            return
        self.path_edit.setText(path)
        self.sheet_combo.blockSignals(True)
        self.sheet_combo.clear()
        try:
            names = [n for n in io_tables.list_table_names(path) if n]
        except Exception:
            names = []
        self.sheet_combo.addItems(names)
        self._wizard.sheet_name = names[0] if names else None
        self.sheet_combo.blockSignals(False)

    def _on_sheet(self, name: str) -> None:
        self._wizard.sheet_name = name or None

    def validatePage(self) -> bool:  # noqa: N802 — имя API Qt
        path = self.path_edit.text().strip()
        if not path:
            QMessageBox.warning(self, "Файл не выбран", "Укажите файл для восстановления.")
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


class MappingPage(QWizardPage):
    """Шаг: сопоставление столбцов + политика неизвестных кодов."""

    def __init__(self, wizard: RestoreWizard) -> None:
        super().__init__()
        self._wizard = wizard
        self.setTitle("Шаг 3. Столбцы и политика")
        self.setSubTitle(
            "Сопоставление автоматическое (по заголовкам); при необходимости снимите отметки. "
            "Столбцы без отметки пройдут без изменений."
        )

        layout = QVBoxLayout(self)
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Восстановить", "Столбец в файле", "Заголовок в результате"])
        layout.addWidget(self.table)

        policy_box = QGroupBox("Политика неизвестных кодов (кода нет в словаре)")
        policy_layout = QVBoxLayout(policy_box)
        self.keep_radio = QRadioButton("Оставить код как есть (по умолчанию) + предупреждение")
        self.blank_radio = QRadioButton("Очистить ячейку (пусто)")
        self.drop_radio = QRadioButton("Исключить строку целиком")
        self.keep_radio.setChecked(True)
        policy_layout.addWidget(self.keep_radio)
        policy_layout.addWidget(self.blank_radio)
        policy_layout.addWidget(self.drop_radio)
        layout.addWidget(policy_box)

        self._checks: list[QCheckBox] = []
        self._edits: list[QLineEdit] = []

    def initializePage(self) -> None:  # noqa: N802 — имя API Qt
        table = self._wizard.table
        if table is None:
            return
        self._checks.clear()
        self._edits.clear()
        self.table.setRowCount(table.n_cols)
        for idx, header in enumerate(table.headers):
            check = QCheckBox()
            # Автосопоставление: восстанавливаем все столбцы; пользователь правит
            check.setChecked(True)
            self.table.setCellWidget(idx, 0, self._wrap_centered(check))
            self._checks.append(check)

            self.table.setItem(idx, 1, QTableWidgetItem(str(header)))
            edit = QLineEdit(str(header))
            self._edits.append(edit)
            self.table.setCellWidget(idx, 2, edit)
        self.table.resizeColumnsToContents()

    @staticmethod
    def _wrap_centered(widget) -> "QWidget":  # noqa: F821 — импорт локальный
        from PyQt6.QtWidgets import QWidget

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(widget)
        return container

    def validatePage(self) -> bool:  # noqa: N802 — имя API Qt
        table = self._wizard.table
        if table is None:
            return False
        plan: list[RestorePlanColumn] = []
        for idx, (check, edit) in enumerate(zip(self._checks, self._edits)):
            header = str(table.headers[idx])
            target = edit.text().strip() if check.isChecked() else ""
            plan.append(RestorePlanColumn(src_index=idx, src_header=header, target_header=target))
        self._wizard.plan = plan
        if self.blank_radio.isChecked():
            self._wizard.policy = UnknownPolicy.BLANK
        elif self.drop_radio.isChecked():
            self._wizard.policy = UnknownPolicy.DROP
        else:
            self._wizard.policy = UnknownPolicy.KEEP
        return True


class RestoreSummaryPage(QWizardPage):
    """Шаг: итоги перед восстановлением."""

    def __init__(self, wizard: RestoreWizard) -> None:
        super().__init__()
        self._wizard = wizard
        self.setTitle("Шаг 4. Итоги")
        self.setSubTitle("Проверьте выбор и нажмите «Восстановить»")
        layout = QVBoxLayout(self)
        self.summary_label = QLabel("")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)
        layout.addStretch(1)

    def initializePage(self) -> None:  # noqa: N802 — имя API Qt
        wizard = self._wizard
        table = wizard.table
        if table is None:
            return
        restore_count = sum(1 for c in wizard.plan if (c.target_header or "").strip())
        lines = [
            f"Проект: <b>{wizard.workspace.name if wizard.workspace else wizard.selected_project}</b>",
            f"Файл: <b>{wizard.source_path}</b>",
            f"Строк: <b>{table.n_rows}</b>, столбцов: <b>{table.n_cols}</b>",
            f"Столбцов к восстановлению: <b>{restore_count}</b>",
            f"Политика неизвестных кодов: <b>{wizard.policy.title}</b>",
            "Результат будет сохранён в НОВЫЙ файл <имя>__restored.<расширение>.",
        ]
        self.summary_label.setText("<br>".join(lines))
