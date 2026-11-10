"""Главное окно приложения: проекты, вкладки, мастера, авто-закрытие (F-3…F-7)."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, QSettings
from PyQt6.QtGui import QAction, QCloseEvent, QColor, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressDialog,
    QPushButton,
    QSplitter,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.application.anonymize_service import AnonymizeResult, AnonymizeService
from src.application.autolock import AutoLockManager
from src.application.errors import (
    ProjectNotFoundError,
    WrongPasswordError,
)
from src.application.project_service import ProjectManager, ProjectWorkspace
from src.application.restore_service import RestoreResult, RestoreService
from src.domain.models import PiiType, TableData
from src.gui.dialogs import CreateProjectDialog, PasswordDialog
from src.gui.dictionary_dialog import MappingDialog
from src.gui.import_wizard import ImportWizard
from src.gui.restore_wizard import RestoreWizard
from src.gui.workers import FunctionWorker

_MAX_TABLE_ROWS = 5000  # ограничение предпросмотра в таблицах GUI
_AUTOLOCK_CHECK_MS = 60_000

_SETTINGS_ORG = "LocalTableAnonymizer"
_SETTINGS_APP = "App"
_SETTINGS_DIR_KEY = "projects_dir"


def _offline_pixmap() -> QPixmap:
    """Нарисовать иконку «офлайн»: перечёркнутый круг."""
    pix = QPixmap(14, 14)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor("#c62828"), 2))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(1, 1, 12, 12)
    painter.drawLine(3, 11, 11, 3)
    painter.end()
    return pix


def _fill_table(widget: QTableWidget, table: TableData, max_rows: int = _MAX_TABLE_ROWS) -> None:
    """Заполнить QTableWidget данными (с ограничением строк для скорости)."""
    widget.setRowCount(0)
    widget.setColumnCount(table.n_cols)
    widget.setHorizontalHeaderLabels([str(h) for h in table.headers])
    rows = min(table.n_rows, max_rows)
    widget.setRowCount(rows)
    for r in range(rows):
        row = table.rows[r]
        for c in range(table.n_cols):
            value = row[c] if c < len(row) else None
            widget.setItem(r, c, QTableWidgetItem("" if value is None else str(value)))
    widget.resizeColumnsToContents()


class MainWindow(QMainWindow):
    """Главное окно «Локальный анонимизатор таблиц данных»."""

    def __init__(self, manager: ProjectManager, autolock: Optional[AutoLockManager] = None) -> None:
        super().__init__()
        self.manager = manager
        self.autolock = autolock or AutoLockManager()
        self.ws: Optional[ProjectWorkspace] = None
        self.worker: Optional[FunctionWorker] = None
        self.progress_dialog: Optional[QProgressDialog] = None
        self._last_table: Optional[TableData] = None
        self._last_columns: dict[int, PiiType] = {}

        self.setWindowTitle("Локальный анонимизатор таблиц данных")
        self.resize(1100, 700)
        self._build_ui()
        self._refresh_projects()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._sweep_autolock)
        self._timer.start(_AUTOLOCK_CHECK_MS)

    # --- Построение интерфейса ----------------------------------------------

    def _build_ui(self) -> None:
        self._build_menu()

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Левая панель: список проектов
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("Проекты:"))
        self.project_list = QListWidget()
        self.project_list.itemDoubleClicked.connect(lambda _item: self._open_project())
        left_layout.addWidget(self.project_list, stretch=1)
        for text, slot in (
            ("Создать проект…", self._create_project),
            ("Открыть проект…", self._open_project),
            ("Удалить проект…", self._delete_project),
            ("Обновить список", self._refresh_projects),
        ):
            button = QPushButton(text)
            button.clicked.connect(slot)
            left_layout.addWidget(button)
        splitter.addWidget(left)

        # Правая часть: вкладки
        self.tabs = QTabWidget()
        self.table_tab = QTableWidget()
        self.table_tab.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tabs.addTab(self.table_tab, "Таблица (анонимная)")

        stats_widget = QWidget()
        stats_layout = QVBoxLayout(stats_widget)
        self.stats_label = QLabel("Статистика появится после анонимизации.")
        self.stats_label.setWordWrap(True)
        stats_layout.addWidget(self.stats_label)
        self.stats_table = QTableWidget()
        self.stats_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        stats_layout.addWidget(self.stats_table, stretch=1)
        self.tabs.addTab(stats_widget, "Статистика")

        journal_widget = QWidget()
        journal_layout = QVBoxLayout(journal_widget)
        journal_top = QHBoxLayout()
        refresh_journal = QPushButton("Обновить журнал")
        refresh_journal.clicked.connect(self._refresh_journal)
        journal_top.addWidget(refresh_journal)
        journal_top.addStretch(1)
        journal_layout.addLayout(journal_top)
        self.journal_view = QPlainTextEdit()
        self.journal_view.setReadOnly(True)
        journal_layout.addWidget(self.journal_view, stretch=1)
        self.tabs.addTab(journal_widget, "Журнал")

        splitter.addWidget(self.tabs)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        self.setCentralWidget(splitter)

        # Статусная строка с иконкой «офлайн» (Г-1)
        status = QStatusBar()
        self.setStatusBar(status)
        offline_label = QLabel()
        offline_label.setPixmap(_offline_pixmap())
        status.addPermanentWidget(offline_label)
        status.addPermanentWidget(QLabel(" ОФЛАЙН: сеть не используется (Г-1) "))
        self.project_status_label = QLabel("Проект не открыт")
        status.addWidget(self.project_status_label)

        self._update_actions_state()

    def _build_menu(self) -> None:
        menu_file = self.menuBar().addMenu("Файл")
        self._add_action(menu_file, "Создать проект…", self._create_project, "Ctrl+N")
        self._add_action(menu_file, "Открыть проект…", self._open_project, "Ctrl+O")
        self._add_action(menu_file, "Удалить проект…", self._delete_project)
        menu_file.addSeparator()
        self._add_action(menu_file, "Папка проектов…", self._choose_projects_dir)
        menu_file.addSeparator()
        self._add_action(menu_file, "Выход", self.close)

        menu_tools = self.menuBar().addMenu("Инструменты")
        self.action_import = self._add_action(
            menu_tools, "Импорт таблицы (анонимизация)…", self._start_import, "Ctrl+I"
        )
        self.action_restore = self._add_action(
            menu_tools, "Восстановить из файла…", self._start_restore, "Ctrl+R"
        )
        self.action_dictionary = self._add_action(
            menu_tools, "Словарь соответствий…", self._show_dictionary
        )
        menu_tools.addSeparator()
        self._add_action(menu_tools, "Обновить статистику", self._refresh_stats)
        self._add_action(menu_tools, "Обновить журнал", self._refresh_journal)

        menu_help = self.menuBar().addMenu("Справка")
        self._add_action(menu_help, "О программе", self._show_about)

    @staticmethod
    def _add_action(menu, text: str, slot, shortcut: str = "") -> QAction:
        action = QAction(text)
        if shortcut:
            action.setShortcut(shortcut)
        action.triggered.connect(slot)
        menu.addAction(action)
        return action

    # --- Список проектов -----------------------------------------------------

    def _refresh_projects(self) -> None:
        self.project_list.clear()
        try:
            projects = self.manager.list_projects()
        except Exception as exc:
            QMessageBox.warning(self, "Ошибка", f"Не удалось получить список проектов: {exc}")
            return
        for project in projects:
            item = QListWidgetItem(f"{project.name}")
            tooltip = f"Путь: {project.path}"
            if project.created_at:
                tooltip += f"\nСоздан: {project.created_at}"
            item.setToolTip(tooltip)
            self.project_list.addItem(item)
        self._update_actions_state()

    def _selected_project_name(self) -> Optional[str]:
        item = self.project_list.currentItem()
        return item.text() if item else None

    # --- Проекты: создание/открытие/удаление ---------------------------------

    def _create_project(self) -> None:
        dialog = CreateProjectDialog(self.manager.projects_dir, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        name, password = dialog.project_name, dialog.password
        if dialog.projects_dir != self.manager.projects_dir:
            self.manager = ProjectManager(dialog.projects_dir)
            QSettings(_SETTINGS_ORG, _SETTINGS_APP).setValue(_SETTINGS_DIR_KEY, str(dialog.projects_dir))

        def job() -> ProjectWorkspace:
            return self.manager.create_project(name, password)

        self._run_worker(job, self._on_project_opened, "Создание проекта…")

    def _open_project(self) -> None:
        name = self._selected_project_name()
        if not name:
            QMessageBox.information(self, "Проект не выбран", "Выберите проект в списке слева.")
            return
        dialog = PasswordDialog(name, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        password = dialog.password

        def job() -> ProjectWorkspace:
            return self.manager.open_project(name, password)

        self._run_worker(job, self._on_project_opened, "Открытие проекта…")

    def _on_project_opened(self, workspace: ProjectWorkspace) -> None:
        self._close_current_workspace(log=True)
        self.ws = workspace
        self.autolock.register(workspace)
        self.project_status_label.setText(f"Проект: {workspace.name} (словарь записей: {workspace.engine.count()})")
        self.setWindowTitle(f"Локальный анонимизатор — проект «{workspace.name}»")
        self._refresh_journal()
        self._update_actions_state()

    def _delete_project(self) -> None:
        name = self._selected_project_name()
        if not name:
            QMessageBox.information(self, "Проект не выбран", "Выберите проект в списке слева.")
            return
        answer = QMessageBox.question(
            self, "Удаление проекта",
            f"Проект «{name}» будет удалён БЕЗВОЗВРАТНО:\nфайлы словаря перезаписываются "
            "нулями и удаляются (Т-7). Продолжить?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            if self.ws is not None and self.ws.name == name:
                self._close_current_workspace(log=False)
            self.manager.delete_project(name)
        except ProjectNotFoundError as exc:
            QMessageBox.warning(self, "Ошибка", str(exc))
            return
        except Exception as exc:
            QMessageBox.warning(self, "Ошибка", f"Не удалось удалить проект: {exc}")
            return
        self._refresh_projects()
        QMessageBox.information(self, "Готово", f"Проект «{name}» удалён, файлы словаря уничтожены.")

    def _close_current_workspace(self, log: bool = True) -> None:
        if self.ws is not None:
            self.autolock.unregister(self.ws)
            self.manager.close_workspace(self.ws, log=log)
            self.ws = None
        self.project_status_label.setText("Проект не открыт")
        self.setWindowTitle("Локальный анонимизатор таблиц данных")
        self._update_actions_state()

    def _choose_projects_dir(self) -> None:
        if self.ws is not None:
            QMessageBox.information(self, "Закройте проект", "Сначала закройте текущий проект.")
            return
        directory = QFileDialog.getExistingDirectory(
            self, "Папка хранения проектов", str(self.manager.projects_dir)
        )
        if not directory:
            return
        self.manager = ProjectManager(directory)
        QSettings(_SETTINGS_ORG, _SETTINGS_APP).setValue(_SETTINGS_DIR_KEY, directory)
        self._refresh_projects()

    def _require_project(self) -> bool:
        if self.ws is None:
            QMessageBox.information(
                self, "Проект не открыт",
                "Откройте или создайте проект: словарь соответствий хранится в проекте.",
            )
            return False
        if self.ws.locked:
            QMessageBox.information(
                self, "Проект закрыт",
                "Проект автоматически закрыт (30 мин бездействия). Откройте его заново.",
            )
            return False
        self.autolock.touch(self.ws)
        return True

    # --- Импорт (мастер анонимизации) ---------------------------------------

    def _start_import(self) -> None:
        if not self._require_project():
            return
        wizard = ImportWizard(self.ws.name, self)  # type: ignore[union-attr]
        if wizard.exec() != wizard.DialogCode.Accepted:
            return
        table, columns, source = wizard.table, wizard.columns, wizard.source_path
        if table is None or source is None:
            return
        self._last_columns = dict(columns)

        suffix = source.suffix.lower()
        note = None
        if suffix == ".xls":
            suffix = ".xlsx"  # XLS не поддерживает запись — сохраняем как XLSX
        default_name = f"{source.stem}__anon{suffix}"
        path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить анонимную копию", str(source.parent / default_name),
            "Таблицы (*.csv *.xlsx *.json);;Все файлы (*)",
        )
        if not path:
            return

        service = AnonymizeService()

        def job() -> AnonymizeResult:
            return service.anonymize(self.ws, table, columns, path, progress=self._emit_progress)  # type: ignore[arg-type]

        self._run_worker(job, self._on_anonymized, "Анонимизация…", with_progress=True)

    def _on_anonymized(self, result: AnonymizeResult) -> None:
        self._last_table = result.table
        self._fill_result_table(result.table)
        self.tabs.setCurrentIndex(0)
        self._refresh_stats()
        message = (
            f"Анонимизация завершена.\n\nФайл: {result.output_path}\n"
            f"Заменено ячеек: {result.stats.replaced_cells}\n"
            f"Пропусков (не тронуто): {result.stats.missing_cells}"
        )
        if result.note:
            message += f"\n\nПометка: {result.note}"
        QMessageBox.information(self, "Готово", message)

    # --- Восстановление ------------------------------------------------------

    def _start_restore(self) -> None:
        project_names = [p.name for p in self.manager.list_projects()]
        if not project_names:
            QMessageBox.information(self, "Нет проектов", "Сначала создайте проект со словарём.")
            return
        wizard = RestoreWizard(self.ws if (self.ws and not self.ws.locked) else None, project_names, self)
        if wizard.exec() != wizard.DialogCode.Accepted:
            return
        table, plan, policy, source = wizard.table, wizard.plan, wizard.policy, wizard.source_path
        if table is None or source is None:
            return

        # Если проект в мастере не был открыт — откроем по паролю
        workspace = self.ws
        if workspace is None or workspace.locked:
            try:
                workspace = self.manager.open_project(wizard.selected_project, wizard.password)
            except WrongPasswordError as exc:
                QMessageBox.warning(self, "Неверный пароль", str(exc))
                return
            except Exception as exc:
                QMessageBox.warning(self, "Ошибка", str(exc))
                return
            self._on_project_opened(workspace)

        suffix = source.suffix.lower()
        if suffix == ".xls":
            suffix = ".xlsx"
        default_name = f"{source.stem}__restored{suffix}"
        path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить восстановленную копию", str(source.parent / default_name),
            "Таблицы (*.csv *.xlsx *.json);;Все файлы (*)",
        )
        if not path:
            return

        service = RestoreService()

        def job() -> RestoreResult:
            return service.restore(
                workspace, table, plan, policy=policy, output_path=path, progress=self._emit_progress
            )

        self._run_worker(job, self._on_restored, "Восстановление…", with_progress=True)

    def _on_restored(self, result: RestoreResult) -> None:
        self._fill_result_table(result.table)
        self.tabs.setCurrentIndex(0)
        self._refresh_journal()
        message = (
            f"Восстановление завершено.\n\nФайл: {result.output_path}\n"
            f"Восстановлено ячеек: {result.stats.restored_cells}\n"
            f"Неизвестных кодов: {result.stats.unknown_cells}"
        )
        if result.stats.dropped_rows:
            message += f"\nИсключено строк: {result.stats.dropped_rows}"
        if result.note:
            message += f"\n\nПометка: {result.note}"
        if result.stats.warnings:
            message += "\n\nПредупреждения:\n" + "\n".join(result.stats.warnings)
        QMessageBox.information(self, "Готово", message)

    # --- Словарь / статистика / журнал ---------------------------------------

    def _show_dictionary(self) -> None:
        if not self._require_project():
            return
        dialog = MappingDialog(self.ws, self)  # type: ignore[arg-type]
        dialog.exec()

    def _fill_result_table(self, table: TableData) -> None:
        _fill_table(self.table_tab, table)

    def _refresh_stats(self) -> None:
        if self._last_table is None:
            self.stats_label.setText("Статистика появится после анонимизации.")
            self.stats_table.setRowCount(0)
            return
        service = AnonymizeService()
        report = service.compute_stats(self._last_table, self._last_columns)
        self.stats_label.setText(
            f"Строк: <b>{report.rows}</b>, столбцов: <b>{report.columns}</b>, "
            f"столбцов ПДн: <b>{report.pii_columns}</b>, пропусков всего: <b>{report.missing_total}</b>"
        )
        self.stats_table.setColumnCount(1)
        self.stats_table.setHorizontalHeaderLabels(["Столбец: непустых / уникальных / пропусков"])
        self.stats_table.setRowCount(len(report.column_lines))
        for i, line in enumerate(report.column_lines):
            self.stats_table.setItem(i, 0, QTableWidgetItem(line))
        self.stats_table.resizeColumnsToContents()

    def _refresh_journal(self) -> None:
        if self.ws is None:
            self.journal_view.setPlainText("Проект не открыт — журнал недоступен.")
            return
        try:
            lines = self.ws.journal.read(limit=500)
        except Exception as exc:
            self.journal_view.setPlainText(f"Ошибка чтения журнала: {exc}")
            return
        self.journal_view.setPlainText("\n".join(lines) if lines else "Журнал пуст.")

    # --- Фоновые операции ----------------------------------------------------

    def _run_worker(self, fn, on_ok, busy_text: str, with_progress: bool = False) -> None:
        if self.worker is not None:
            QMessageBox.information(self, "Занято", "Дождитесь завершения текущей операции.")
            return
        self.progress_dialog = QProgressDialog(busy_text, None, 0, 0 if not with_progress else 100, self)
        self.progress_dialog.setWindowTitle("Пожалуйста, подождите")
        self.progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.progress_dialog.setMinimumDuration(0)
        self.progress_dialog.setAutoClose(False)
        self.progress_dialog.show()

        worker = FunctionWorker(fn)
        self.worker = worker
        if with_progress:
            worker.progress.connect(self._on_progress)
        worker.finished_ok.connect(on_ok)
        worker.failed.connect(self._on_worker_failed)
        worker.finished.connect(self._on_worker_finished)
        worker.start()

    def _emit_progress(self, current: int, total: int) -> None:
        """Колбэк прогресса из сервиса (вызывается в рабочем потоке)."""
        if self.worker is not None:
            self.worker.emit_progress(current, total)

    def _on_progress(self, current: int, total: int) -> None:
        if self.progress_dialog is not None and total > 0:
            self.progress_dialog.setMaximum(total)
            self.progress_dialog.setValue(min(current, total))

    def _on_worker_failed(self, message: str) -> None:
        if isinstance(message, str) and "неверный пароль" in message.lower():
            QMessageBox.warning(self, "Неверный пароль", message)
        else:
            QMessageBox.warning(self, "Ошибка", message)

    def _on_worker_finished(self) -> None:
        if self.progress_dialog is not None:
            self.progress_dialog.close()
            self.progress_dialog = None
        self.worker = None

    # --- Авто-закрытие (F-7) -------------------------------------------------

    def _sweep_autolock(self) -> None:
        locked = self.autolock.sweep()
        if self.ws is not None and self.ws.locked:
            self._close_current_workspace(log=False)
            QMessageBox.information(
                self, "Проект закрыт",
                "Проект автоматически закрыт (30 минут бездействия).\n"
                "Память очищена — откройте проект заново с паролем.",
            )
        if locked:
            self._update_actions_state()

    # --- Прочее --------------------------------------------------------------

    def _update_actions_state(self) -> None:
        opened = self.ws is not None and not self.ws.locked
        for action in (self.action_import, self.action_restore, self.action_dictionary):
            action.setEnabled(opened)

    def _show_about(self) -> None:
        QMessageBox.about(
            self, "О программе",
            "<h3>Локальный анонимизатор таблиц данных</h3>"
            "<p>Версия 1.0 (по ТЗ 2.1). Работа ТИМ: только детерминированные правила, "
            "без нейросетей (Г-5).</p>"
            "<p>Гарантии:<br>"
            "• Г-1: ноль сетевых вызовов — приложение полностью офлайн;<br>"
            "• Г-2: словарь «код ↔ значение» хранится только зашифрованным (AES-256-GCM);<br>"
            "• Г-3: утеря пароля = безвозвратная утрата словаря;<br>"
            "• Г-4: биективные коды (1 значение = 1 код);<br>"
            "• Г-6: исходные файлы не изменяются.</p>",
        )

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 — имя API Qt
        """При выходе закрыть проект и очистить память."""
        self._close_current_workspace(log=True)
        event.accept()
