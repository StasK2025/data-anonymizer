"""Т-6. Исходный файл не изменяется (Г-6): хеш до/после совпадает."""

from __future__ import annotations

import hashlib
from pathlib import Path

from src.application.anonymize_service import AnonymizeService
from src.application.restore_service import RestorePlanColumn, RestoreService
from src.domain.models import PiiType, UnknownPolicy
from src.infrastructure import io_tables
from tests.conftest import PASSWORD, make_pii_table


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_source_file_hash_unchanged(manager, tmp_path: Path):
    """Хеш исходника до/после анонимизации и восстановления совпадает (Т-6)."""
    ws = manager.create_project("Источник", PASSWORD)
    table = make_pii_table(15)

    for name in ("исходник.csv", "исходник.xlsx", "исходник.json"):
        src = tmp_path / name
        io_tables.write_table(table, src)
        before = _sha256(src)

        anon = AnonymizeService().anonymize(
            ws, table, {0: PiiType.FULL_NAME, 1: PiiType.PHONE}, tmp_path / "out" / f"{name}.anon.xlsx"
        )
        assert _sha256(src) == before

        anon_table = io_tables.read_table(anon.output_path)
        plan = [RestorePlanColumn(i, str(h), str(h)) for i, h in enumerate(anon_table.headers)]
        restored = RestoreService().restore(
            ws, anon_table, plan, UnknownPolicy.KEEP, tmp_path / "out" / f"{name}.restored.xlsx"
        )
        assert restored.output_path.exists()
        assert _sha256(src) == before

    manager.close_workspace(ws)
