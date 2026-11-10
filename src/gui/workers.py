"""Работники для фонового выполнения операций в QThread (интерфейс не блокируется)."""

from __future__ import annotations

from typing import Any, Callable

from PyQt6.QtCore import QThread, pyqtSignal


class FunctionWorker(QThread):
    """Выполняет произвольную функцию в отдельном потоке.

    Сигналы:
    - finished_ok(object) — результат;
    - failed(str) — текст ошибки (по-русски, от сервиса);
    - progress(int, int) — прогресс (текущий, всего).
    """

    finished_ok = pyqtSignal(object)
    failed = pyqtSignal(str)
    progress = pyqtSignal(int, int)

    def __init__(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs

    def run(self) -> None:  # noqa: D102 — выполняется в потоке
        try:
            result = self._fn(*self._args, **self._kwargs)
        except Exception as exc:  # показываем пользователю текст ошибки
            message = str(exc) or type(exc).__name__
            self.failed.emit(message)
            return
        self.finished_ok.emit(result)

    def emit_progress(self, current: int, total: int) -> None:
        """Колбэк прогресса для сервисов (безопасен из другого потока)."""
        self.progress.emit(current, total)
