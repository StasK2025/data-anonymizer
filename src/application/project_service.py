"""Управление проектами: создание, открытие, список, удаление (F-5, F-7, Т-7).

Хранилище проектов: <папка пользователя>/Проекты/<имя>/
    project.db, project.meta.json, journal.log
Папка настраивается (передаётся в конструктор ProjectManager).
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from src.application.errors import (
    InvalidProjectNameError,
    ProjectExistsError,
    ProjectNotFoundError,
    WeakPasswordError,
)
from src.domain.crypto_layer import CryptoLayer
from src.domain.mapping_engine import MappingEngine
from src.infrastructure import mapping_store as ms
from src.infrastructure.journal import Journal
from src.infrastructure.secure_delete import secure_delete_dir

MIN_PASSWORD_LENGTH = 8  # F-7
_INVALID_NAME_CHARS = re.compile(r'[\\/:*?"<>|]')


def default_projects_dir() -> Path:
    """Папка проектов по умолчанию: <пользователь>/Проекты."""
    return Path.home() / "Проекты"


@dataclass
class ProjectInfo:
    """Краткая карточка проекта для списка."""

    name: str
    path: Path
    created_at: Optional[str] = None
    db_size: int = 0


@dataclass
class ProjectWorkspace:
    """Открытый проект: ключ в памяти, открытое хранилище, журнал."""

    name: str
    root: Path
    meta: dict
    key: bytes
    store: ms.SqliteMappingStore
    crypto: CryptoLayer
    engine: MappingEngine
    journal: Journal
    opened_at: float = field(default_factory=time.monotonic)
    last_activity: float = field(default_factory=time.monotonic)
    locked: bool = False

    def touch(self) -> None:
        """Отметить активность (сбрасывает таймер авто-закрытия)."""
        self.last_activity = time.monotonic()

    def lock(self) -> None:
        """Авто-закрытие: очистить память (ключ, словарь), закрыть хранилище (F-7)."""
        self.store.close()
        self.key = b""
        self.crypto = None  # type: ignore[assignment]
        self.engine = None  # type: ignore[assignment]
        self.locked = True

    def require_open(self) -> None:
        """Проверить, что проект не закрыт по таймауту."""
        if self.locked:
            from src.application.errors import WorkspaceLockedError

            raise WorkspaceLockedError("проект автоматически закрыт (30 мин бездействия) — введите пароль")


class ProjectManager:
    """Сценарии жизненного цикла проектов."""

    def __init__(self, projects_dir: str | Path | None = None) -> None:
        """projects_dir настраивается; по умолчанию — <пользователь>/Проекты."""
        self._root = Path(projects_dir) if projects_dir else default_projects_dir()

    @property
    def projects_dir(self) -> Path:
        """Текущая папка проектов."""
        return self._root

    def project_path(self, name: str) -> Path:
        """Путь каталога проекта."""
        self._validate_name(name)
        return self._root / name

    def list_projects(self) -> list[ProjectInfo]:
        """Список проектов в папке хранения."""
        if not self._root.exists():
            return []
        out: list[ProjectInfo] = []
        for child in sorted(self._root.iterdir()):
            if not child.is_dir():
                continue
            meta_path = child / ms.META_FILENAME
            created_at = None
            if meta_path.exists():
                try:
                    created_at = ms.load_meta(meta_path).get("created_at")
                except Exception:
                    created_at = None
            db_path = child / ms.DB_FILENAME
            out.append(ProjectInfo(
                name=child.name,
                path=child,
                created_at=created_at,
                db_size=db_path.stat().st_size if db_path.exists() else 0,
            ))
        return out

    def create_project(self, name: str, password: str) -> ProjectWorkspace:
        """Создать проект: соль, хеш пароля, пустой словарь, журнал."""
        self._validate_name(name)
        self._validate_password(password)
        root = self.project_path(name)
        if root.exists():
            raise ProjectExistsError(f"проект '{name}' уже существует")
        root.mkdir(parents=True, exist_ok=True)

        meta, key = ms.build_meta(password)
        ms.save_meta(root / ms.META_FILENAME, meta)

        store = ms.SqliteMappingStore(root / ms.DB_FILENAME)
        store.open()
        journal = Journal(root / "journal.log")
        crypto = CryptoLayer(key)
        workspace = ProjectWorkspace(
            name=name, root=root, meta=meta, key=key, store=store,
            crypto=crypto, engine=MappingEngine(store, crypto), journal=journal,
        )
        journal.log("создан проект")
        return workspace

    def open_project(self, name: str, password: str) -> ProjectWorkspace:
        """Открыть проект по паролю; неверный пароль -> WrongPasswordError (Т-5)."""
        self._validate_name(name)
        root = self.project_path(name)
        meta_path = root / ms.META_FILENAME
        if not root.exists() or not meta_path.exists():
            raise ProjectNotFoundError(f"проект '{name}' не найден")
        meta = ms.load_meta(meta_path)
        key = ms.key_from_meta(meta, password)  # WrongPasswordError при отказе

        store = ms.SqliteMappingStore(root / ms.DB_FILENAME)
        store.open()
        crypto = CryptoLayer(key)
        journal = Journal(root / "journal.log")
        workspace = ProjectWorkspace(
            name=name, root=root, meta=meta, key=key, store=store,
            crypto=crypto, engine=MappingEngine(store, crypto), journal=journal,
        )
        journal.log("открыт проект")
        return workspace

    def close_workspace(self, workspace: ProjectWorkspace, log: bool = True) -> None:
        """Закрыть проект вручную: очистить память, закрыть БД."""
        if not workspace.locked:
            if log:
                try:
                    workspace.journal.log("закрыт проект")
                except Exception:
                    pass
            workspace.lock()

    def delete_project(self, name: str) -> None:
        """Удалить проект с безопасной очисткой: перезапись нулями + удаление (Т-7)."""
        self._validate_name(name)
        root = self.project_path(name)
        if not root.exists():
            raise ProjectNotFoundError(f"проект '{name}' не найден")
        secure_delete_dir(root)

    # --- Валидация -----------------------------------------------------------

    @staticmethod
    def _validate_name(name: str) -> None:
        name = (name or "").strip()
        if not name:
            raise InvalidProjectNameError("имя проекта не может быть пустым")
        if _INVALID_NAME_CHARS.search(name) or name in (".", ".."):
            raise InvalidProjectNameError(f"недопустимое имя проекта: '{name}'")

    @staticmethod
    def _validate_password(password: str) -> None:
        if len(password or "") < MIN_PASSWORD_LENGTH:
            raise WeakPasswordError(f"пароль должен содержать минимум {MIN_PASSWORD_LENGTH} символов")
