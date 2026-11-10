"""Точка входа «Локальный анонимизатор таблиц данных».

Запуск: python main.py
GUI на PyQt6 импортируется отложенно: ядро (domain/application/infrastructure)
работает и без PyQt6 — в этом случае выводится инструкция по установке.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Корень проекта в sys.path — чтобы пакет src находился при запуске из любого каталога
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main() -> int:
    """Запустить GUI (или подсказать, как установить PyQt6)."""
    try:
        from PyQt6.QtWidgets import QApplication, QMessageBox
    except ImportError:
        print("PyQt6 не установлен — графический интерфейс недоступен.")
        print("Установите зависимости: python -m pip install -r requirements.txt")
        print("Ядро приложения (анонимизация/восстановление) доступно из консоли:")
        print("    python -m pytest   — запуск тестов")
        return 1

    from PyQt6.QtCore import QSettings

    from src.application.project_service import ProjectManager, default_projects_dir
    from src.gui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("Локальный анонимизатор таблиц данных")
    app.setOrganizationName("LocalTableAnonymizer")

    settings = QSettings("LocalTableAnonymizer", "App")
    saved_dir = settings.value("projects_dir", "")
    projects_dir = Path(saved_dir) if saved_dir else default_projects_dir()

    manager = ProjectManager(projects_dir)
    window = MainWindow(manager)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
