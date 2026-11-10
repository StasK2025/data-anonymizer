"""Авто-закрытие проекта по таймауту 30 минут (F-7).

Память очищается (ключ, словарь), требуется ввод пароля заново.
"""

from __future__ import annotations

import time
from typing import Iterable

from src.application.project_service import ProjectWorkspace

DEFAULT_TIMEOUT_SECONDS = 30 * 60  # 30 минут (F-7)


class AutoLockManager:
    """Отслеживает активность открытых проектов и авто-закрывает их."""

    def __init__(self, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        self.timeout_seconds = timeout_seconds
        self._workspaces: list[ProjectWorkspace] = []

    def register(self, workspace: ProjectWorkspace) -> None:
        """Взять проект под наблюдение (повторная регистрация игнорируется)."""
        if workspace not in self._workspaces:
            self._workspaces.append(workspace)

    def unregister(self, workspace: ProjectWorkspace) -> None:
        """Снять проект с наблюдения (например, при ручном закрытии)."""
        if workspace in self._workspaces:
            self._workspaces.remove(workspace)

    def touch(self, workspace: ProjectWorkspace) -> None:
        """Отметить активность пользователя в проекте."""
        workspace.touch()

    def is_expired(self, workspace: ProjectWorkspace) -> bool:
        """Просрочен ли таймаут бездействия."""
        return (time.monotonic() - workspace.last_activity) > self.timeout_seconds

    def sweep(self) -> list[ProjectWorkspace]:
        """Закрыть проекты с истёкшим таймаутом; вернуть список закрытых."""
        locked: list[ProjectWorkspace] = []
        for workspace in list(self._workspaces):
            if workspace.locked:
                self.unregister(workspace)
                continue
            if self.is_expired(workspace):
                workspace.lock()
                locked.append(workspace)
                self.unregister(workspace)
        return locked

    def sweep_iter(self, workspaces: Iterable[ProjectWorkspace]) -> list[ProjectWorkspace]:
        """Проверить конкретный список проектов (например, текущий открытый)."""
        locked: list[ProjectWorkspace] = []
        for workspace in workspaces:
            if not workspace.locked and self.is_expired(workspace):
                workspace.lock()
                locked.append(workspace)
        return locked
