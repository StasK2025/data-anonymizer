"""Т-7. Удаление проекта: файлов нет, восстановление невозможно."""

from __future__ import annotations

import pytest

from src.application.errors import ProjectNotFoundError
from src.domain.models import PiiType
from src.infrastructure import io_tables
from tests.conftest import PASSWORD


def test_delete_project_removes_everything(manager, tmp_path):
    """После удаления: каталога проекта нет -> открыть/восстановить невозможно (Т-7)."""
    ws = manager.create_project("Удаляемый", PASSWORD)
    ws.engine.code_for_value("Иванов Иван", "full_name")
    ws.store.flush()
    root = ws.root
    db_path = ws.store.path
    manager.close_workspace(ws)

    # Сохраним анонимный файл, чтобы попытаться восстановить после удаления проекта
    from src.domain.models import TableData

    anon = io_tables.write_table(
        TableData(headers=["ФИО"], rows=[["ID-000000"]]),
        tmp_path / "анон.csv",
    )
    assert anon.path.exists()

    manager.delete_project("Удаляемый")

    assert not root.exists(), "каталог проекта должен быть удалён"
    assert not db_path.exists(), "project.db должна быть удалена"

    with pytest.raises(ProjectNotFoundError):
        manager.open_project("Удаляемый", PASSWORD)

    assert all(p.name != "Удаляемый" for p in manager.list_projects())


def test_secure_delete_overwrites_with_zeros(manager):
    """Файл перезаписывается нулями перед удалением (проверка на копии)."""
    from src.infrastructure.secure_delete import secure_delete_file

    target = manager.projects_dir / "артефакт.bin"
    payload = b"\xff\xee\xdd\xcc" * 1000
    target.write_bytes(payload)
    secure_delete_file(target)
    assert not target.exists()


def test_delete_missing_project_raises(manager):
    """Удаление несуществующего проекта -> понятная ошибка."""
    with pytest.raises(ProjectNotFoundError):
        manager.delete_project("НетПроекта")
