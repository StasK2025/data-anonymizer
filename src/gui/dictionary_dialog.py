"""Окно словаря соответствий (F-5): просмотр после пароля, значения скрыты по умолчанию.

- Экспорт словаря по умолчанию — зашифрованный.
- Открытый CSV — только после диалога предупреждения «ПДн в открытом виде».
"""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from src.application.errors import AppError, ConfirmationRequired
from src.application.mapping_service import MappingService
from src.application.project_service import ProjectWorkspace


class MappingDialog(QDialog):
    """Диалог просмотра/экспорта/импорта словаря соответствий."""

    def __init__(self, workspace: ProjectWorkspace, parent=None) -> None:
        super().__init__(parent)
        self._ws = workspace
        self._service = MappingService()
        self.setWindowTitle(f"Словарь соответствий — проект «{workspace.name}»")
        self.resize(720, 480)

        layout = QVBoxLayout(self)
        info = QLabel(
            "Словарь расшифровывается ключом проекта (из пароля). "
            "Значения скрыты по умолчанию — раскрывайте осознанно."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        top = QHBoxLayout()
        self.reveal_check = QCheckBox("Показать значения (ПДн в открытом виде!)")
        self.reveal_check.toggled.connect(self._reload)
        self.count_label = QLabel("")
        top.addWidget(self.reveal_check)
        top.addStretch(1)
        top.addWidget(self.count_label)
        layout.addLayout(top)

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Код", "Тип ПДн", "Значение", "Создан"])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table)

        buttons = QHBoxLayout()
        export_enc = QPushButton("Экспорт (зашифрованный)…")
        export_enc.clicked.connect(self._export_encrypted)
        export_open = QPushButton("Экспорт CSV (открытым текстом)…")
        export_open.clicked.connect(self._export_open)
        import_enc = QPushButton("Импорт словаря…")
        import_enc.clicked.connect(self._import_mapping)
        close_button = QPushButton("Закрыть")
        close_button.clicked.connect(self.accept)
        for b in (export_enc, export_open, import_enc, close_button):
            buttons.addWidget(b)
        layout.addLayout(buttons)

        self._reload()

    def _reload(self) -> None:
        try:
            entries = self._service.entries(self._ws, reveal=self.reveal_check.isChecked())
        except Exception as exc:
            QMessageBox.warning(self, "Ошибка", str(exc))
            return
        self.count_label.setText(f"Записей: <b>{len(entries)}</b>")
        self.table.setRowCount(len(entries))
        for row_index, entry in enumerate(entries):
            self.table.setItem(row_index, 0, QTableWidgetItem(entry.code))
            self.table.setItem(row_index, 1, QTableWidgetItem(entry.column_type))
            self.table.setItem(row_index, 2, QTableWidgetItem(entry.masked))
            self.table.setItem(row_index, 3, QTableWidgetItem(entry.created_at))
        self.table.resizeColumnsToContents()

    def _export_encrypted(self) -> None:
        default_name = f"{self._ws.name}__словарь.map.json"
        path, _ = QFileDialog.getSaveFileName(
            self, "Экспорт словаря (зашифрованный)", default_name,
            "Зашифрованный словарь (*.map.json);;Все файлы (*)",
        )
        if not path:
            return
        try:
            count = self._service.export_encrypted(self._ws, path)
        except Exception as exc:
            QMessageBox.warning(self, "Ошибка", str(exc))
            return
        QMessageBox.information(self, "Готово", f"Словарь зашифрован и сохранён.\nЗаписей: {count}")

    def _export_open(self) -> None:
        answer = QMessageBox.warning(
            self,
            "Открытый экспорт словаря",
            "ВНИМАНИЕ: файл будет содержать персональные данные в ОТКРЫТОМ ВИДЕ\n"
            "без шифрования. Продолжить?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        default_name = f"{self._ws.name}__словарь.csv"
        path, _ = QFileDialog.getSaveFileName(
            self, "Экспорт словаря (открытый CSV)", default_name, "CSV (*.csv)"
        )
        if not path:
            return
        try:
            count = self._service.export_open_csv(self._ws, path, confirm=True)
        except ConfirmationRequired as exc:
            QMessageBox.warning(self, "Требуется подтверждение", str(exc))
            return
        except Exception as exc:
            QMessageBox.warning(self, "Ошибка", str(exc))
            return
        QMessageBox.information(self, "Готово", f"Словарь сохранён открытым текстом.\nЗаписей: {count}")

    def _import_mapping(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Импорт словаря", "",
            "Словарь (*.map.json *.json *.csv);;Все файлы (*)",
        )
        if not path:
            return
        try:
            if path.lower().endswith(".csv"):
                answer = QMessageBox.question(
                    self, "Импорт открытого CSV",
                    "Файл содержит персональные данные в открытом виде. Импортировать?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return
                count = self._service.import_open_csv(self._ws, path, confirm=True)
            else:
                count = self._service.import_encrypted(self._ws, path)
        except (AppError, ConfirmationRequired) as exc:
            QMessageBox.warning(self, "Ошибка импорта", str(exc))
            return
        except Exception as exc:
            QMessageBox.warning(self, "Ошибка импорта", str(exc))
            return
        QMessageBox.information(self, "Готово", f"Импортировано записей: {count}")
        self._reload()
