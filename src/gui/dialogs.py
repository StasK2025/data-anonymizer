"""Диалоги GUI: пароль проекта, создание проекта, ввод имени папки."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from src.application.project_service import MIN_PASSWORD_LENGTH


class PasswordDialog(QDialog):
    """Запрос пароля проекта (для открытия/действий с проектом)."""

    def __init__(self, project_name: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Пароль проекта «{project_name}»")
        self.setModal(True)

        layout = QVBoxLayout(self)
        info = QLabel(
            f"Проект: <b>{project_name}</b><br>"
            "Пароль хранится только как хеш (PBKDF2, 600 000 итераций).<br>"
            "<b>При утере пароля словарь восстановить невозможно (Г-3).</b>"
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        form = QFormLayout()
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Пароль:", self.password_edit)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.password_edit.setFocus()

    @property
    def password(self) -> str:
        """Введённый пароль."""
        return self.password_edit.text()


class CreateProjectDialog(QDialog):
    """Создание проекта: имя, пароль (>= 8 символов), папка хранения."""

    def __init__(self, projects_dir: Path, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Создание проекта")
        self.setModal(True)
        self._projects_dir = Path(projects_dir)

        layout = QVBoxLayout(self)
        warning = QLabel(
            "<b>Внимание:</b> пароль проекта запомнить невозможно — при утере "
            "словарь соответствий будет утрачен безвозвратно (Г-3)."
        )
        warning.setWordWrap(True)
        layout.addWidget(warning)

        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("например: Клиенты_2026")
        form.addRow("Имя проекта:", self.name_edit)

        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Пароль:", self.password_edit)

        self.confirm_edit = QLineEdit()
        self.confirm_edit.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Повторите пароль:", self.confirm_edit)

        dir_row = QHBoxLayout()
        self.dir_label = QLabel(str(self._projects_dir))
        self.dir_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        dir_button = QPushButton("Изменить…")
        dir_button.clicked.connect(self._choose_dir)
        dir_row.addWidget(self.dir_label, stretch=1)
        dir_row.addWidget(dir_button)
        form.addRow("Папка хранения:", dir_row)
        layout.addLayout(form)

        self.hint_label = QLabel(f"Минимальная длина пароля — {MIN_PASSWORD_LENGTH} символов.")
        layout.addWidget(self.hint_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._validate_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def project_name(self) -> str:
        """Имя нового проекта."""
        return self.name_edit.text().strip()

    @property
    def password(self) -> str:
        """Пароль нового проекта."""
        return self.password_edit.text()

    @property
    def projects_dir(self) -> Path:
        """Выбранная папка хранения проектов."""
        return self._projects_dir

    def _choose_dir(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Папка хранения проектов", str(self._projects_dir))
        if directory:
            self._projects_dir = Path(directory)
            self.dir_label.setText(directory)

    def _validate_accept(self) -> None:
        if not self.project_name:
            QMessageBox.warning(self, "Ошибка", "Введите имя проекта.")
            return
        if len(self.password) < MIN_PASSWORD_LENGTH:
            QMessageBox.warning(
                self, "Слабый пароль",
                f"Пароль должен содержать минимум {MIN_PASSWORD_LENGTH} символов.",
            )
            return
        if self.password != self.confirm_edit.text():
            QMessageBox.warning(self, "Ошибка", "Пароли не совпадают.")
            return
        self.accept()
