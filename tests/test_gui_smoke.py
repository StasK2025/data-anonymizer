"""Smoke-тест GUI: импорт модулей и создание окон в offscreen-режиме.

Пропускается, если PyQt6 недоступен (ядро при этом работает без GUI).
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PyQt6 = pytest.importorskip("PyQt6", reason="PyQt6 не установлен — GUI-тесты пропускаются")


@pytest.fixture(scope="module")
def qapp():
    """ QApplication (offscreen)."""
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def test_import_gui_modules():
    """Все модули gui импортируются без ошибок."""
    import src.gui.workers  # noqa: F401
    import src.gui.dialogs  # noqa: F401
    import src.gui.import_wizard  # noqa: F401
    import src.gui.restore_wizard  # noqa: F401
    import src.gui.dictionary_dialog  # noqa: F401
    import src.gui.main_window  # noqa: F401


def test_main_window_created(qapp, tmp_path):
    """Главное окно создаётся и закрывается (проектная папка — временная)."""
    from src.application.project_service import ProjectManager
    from src.gui.main_window import MainWindow

    window = MainWindow(ProjectManager(tmp_path / "Проекты"))
    qapp.processEvents()
    assert window.windowTitle().startswith("Локальный анонимизатор")
    assert window.project_list.count() == 0
    window.close()


def test_main_window_lists_projects(qapp, tmp_path):
    """Окно видит созданный менеджером проект."""
    from src.application.project_service import ProjectManager
    from src.gui.main_window import MainWindow
    from tests.conftest import PASSWORD

    manager = ProjectManager(tmp_path / "Проекты")
    manager.create_project("GUIПроект", PASSWORD)
    window = MainWindow(manager)
    qapp.processEvents()
    assert window.project_list.count() == 1
    assert window.project_list.item(0).text() == "GUIПроект"
    window.close()


def test_import_wizard_builds(qapp, tmp_path):
    """Мастер импорта создаётся (страницы по ТЗ: файл/предпросмотр/столбцы/итоги)."""
    from src.gui.import_wizard import ImportWizard

    wizard = ImportWizard("Тест", None)
    qapp.processEvents()
    assert len(wizard.pageIds()) == 4
    wizard.close()


def test_restore_wizard_builds(qapp, tmp_path):
    """Мастер восстановления: при открытом проекте 3 шага (без страницы пароля)."""
    from src.application.project_service import ProjectManager
    from src.gui.restore_wizard import RestoreWizard
    from tests.conftest import PASSWORD

    manager = ProjectManager(tmp_path / "Проекты")
    ws = manager.create_project("Реставр", PASSWORD)
    wizard = RestoreWizard(ws, ["Реставр"], None)
    qapp.processEvents()
    assert len(wizard.pageIds()) == 3
    wizard.close()

    # Проект не открыт -> добавляется шаг «Проект и пароль»
    wizard2 = RestoreWizard(None, ["Реставр"], None)
    qapp.processEvents()
    assert len(wizard2.pageIds()) == 4
    wizard2.close()
    manager.close_workspace(ws)


def test_offline_pixmap_drawn(qapp):
    """Иконка «офлайн» рисуется (статусная строка Г-1)."""
    from src.gui.main_window import _offline_pixmap

    pix = _offline_pixmap()
    assert not pix.isNull()
