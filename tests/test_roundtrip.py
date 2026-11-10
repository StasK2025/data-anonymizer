"""Т-3. Round-trip: анонимизация -> восстановление -> 100 % совпадение.

Кириллица, эмодзи, спецсимволы, разные регистры и пробелы. Реальный объём
(2 000 × 10 и 10 000 × 5) укладывается в разумное время за счёт пакетного
коммита словаря.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.application.anonymize_service import AnonymizeService
from src.application.restore_service import RestorePlanColumn, RestoreService
from src.domain.models import PiiType, TableData, UnknownPolicy
from src.domain.table_transformer import TableTransformer
from src.infrastructure import io_tables
from tests.conftest import PASSWORD, PII_COLUMNS, make_pii_table

SPECIAL_VALUES = [
    "Иванов Иван", "Второй Участник", "  с пробелами  ", "Смешанный Регистр",
    "emoji 🧝‍♀️🐉🔥 и кириллица ёЁ", "спецсимволы: #;,\"'\\|<>", "кавычки «ёлочки» и — тире",
    "метка@почта.ру", "01.01.1990", "4512 345678", "+7 (916) 000-00-00",
    "89160000000", "a", "1", "NULL", "None", "таб\tсимвол",
]


def _big_table(n_rows: int, n_cols: int) -> TableData:
    """Крупная таблица: 5 типов ПДн + 5 обычных столбцов (чередованием)."""
    types: list[PiiType | None] = []
    for i in range(n_cols):
        types.append([PiiType.FULL_NAME, PiiType.PHONE, PiiType.EMAIL,
                      PiiType.DOCUMENT, PiiType.BIRTH_DATE][i % 5])
    headers = [f"Столбец {i + 1} ({(types[i] or PiiType.FREE_TEXT).title})" for i in range(n_cols)]
    pool = SPECIAL_VALUES
    rows = []
    for r in range(n_rows):
        row = []
        for c in range(n_cols):
            row.append(pool[(r * n_cols + c) % len(pool)])
        rows.append(row)
    return TableData(headers=headers, rows=rows)


def _roundtrip_in_memory(workspace, table: TableData, columns: dict[int, PiiType]) -> TableData:
    transformer = TableTransformer()
    anonymized, _stats = transformer.anonymize(table, columns, workspace.engine)
    reverse = workspace.engine.reverse_index()
    restored, rstats = transformer.restore(
        anonymized, set(columns), reverse, policy=UnknownPolicy.KEEP
    )
    assert rstats.unknown_cells == 0
    return restored


@pytest.mark.parametrize("n_rows,n_cols", [(2000, 10), (10000, 5)])
def test_roundtrip_big_table(manager, n_rows, n_cols):
    """Т-3: 100 % совпадение на крупной таблице (в памяти, без файлов)."""
    ws = manager.create_project("RoundTrip", PASSWORD)
    table = _big_table(n_rows, n_cols)
    columns = {i: t for i, t in enumerate(
        [PiiType.FULL_NAME, PiiType.PHONE, PiiType.EMAIL, PiiType.DOCUMENT,
         PiiType.BIRTH_DATE] * (n_cols // 5 + 1)
    ) if i < n_cols}
    restored = _roundtrip_in_memory(ws, table, columns)
    assert restored.rows == table.rows
    manager.close_workspace(ws)


def test_roundtrip_through_files(manager, tmp_path: Path):
    """Т-3 сквозной: файл CSV -> анонимизация -> файл -> восстановление -> сравнение."""
    ws = manager.create_project("Файлы", PASSWORD)
    table = make_pii_table(20)
    src = tmp_path / "исходник.csv"
    io_tables.write_table(table, src)
    before = src.read_bytes()

    service = AnonymizeService()
    anon_path = tmp_path / "исходник__anon.csv"
    result = service.anonymize(ws, table, dict(PII_COLUMNS), anon_path)
    assert result.output_path.exists()
    assert src.read_bytes() == before  # Г-6: исходник не изменяется

    anon_table = io_tables.read_table(result.output_path)
    restore = RestoreService()
    plan = [RestorePlanColumn(i, str(h), str(h)) for i, h in enumerate(anon_table.headers)]
    restored_path = tmp_path / "исходник__restored.csv"
    restored = restore.restore(ws, anon_table, plan, UnknownPolicy.KEEP, restored_path)

    assert restored.table.rows == table.rows
    manager.close_workspace(ws)


def test_roundtrip_xlsx(manager, tmp_path: Path):
    """Т-3: то же самое через XLSX (типы ячеек сохраняются)."""
    ws = manager.create_project("XLSX", PASSWORD)
    table = make_pii_table(12)
    src = tmp_path / "данные.xlsx"
    io_tables.write_table(table, src)
    loaded = io_tables.read_table(src)
    assert loaded.headers == table.headers

    service = AnonymizeService()
    anon = service.anonymize(ws, loaded, {0: PiiType.FULL_NAME, 1: PiiType.PHONE},
                             tmp_path / "данные__anon.xlsx")
    anon_table = io_tables.read_table(anon.output_path)
    # все значения ПДн-столбцов превратились в коды
    for row in anon_table.rows:
        assert row[0].startswith("ID-") and row[1].startswith("PH-")

    restore = RestoreService()
    plan = [RestorePlanColumn(i, str(h), str(h)) for i, h in enumerate(anon_table.headers)]
    restored = restore.restore(ws, anon_table, plan, UnknownPolicy.KEEP,
                               tmp_path / "данные__restored.xlsx")
    assert restored.table.rows == table.rows
    manager.close_workspace(ws)
