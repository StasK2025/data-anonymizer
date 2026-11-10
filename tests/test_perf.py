"""Т-8. Производительность: маркер/skip по умолчанию (запуск: RUN_PERF=1).

- RUN_PERF=1            — тест 20 000 × 20 (400 000 ячеек) < 30 с.
- RUN_PERF=1 и RUN_PERF_FULL=1 — полный объём ТЗ 100 000 × 100.
"""

from __future__ import annotations

import os
import time

import pytest

from src.domain.models import PiiType, TableData
from src.domain.table_transformer import TableTransformer
from tests.conftest import PASSWORD

pytestmark = [
    pytest.mark.performance,
    pytest.mark.skipif(os.environ.get("RUN_PERF") != "1",
                       reason="Т-8: укажите RUN_PERF=1 для прогона производительности"),
]

_TYPES = [PiiType.FULL_NAME, PiiType.PHONE, PiiType.EMAIL, PiiType.DOCUMENT, PiiType.BIRTH_DATE]


def _build_table(n_rows: int, n_cols: int) -> tuple[TableData, dict[int, PiiType]]:
    headers = [f"Столбец {i}" for i in range(n_cols)]
    types = {i: _TYPES[i % len(_TYPES)] for i in range(n_cols)}
    rows = [
        [f"{types[c].title} значение {r}-{c} №{r * 7 + c}" for c in range(n_cols)]
        for r in range(n_rows)
    ]
    return TableData(headers=headers, rows=rows), types


def _run(manager, n_rows: int, n_cols: int, limit: float) -> float:
    ws = manager.create_project(f"Перф{n_rows}x{n_cols}", PASSWORD)
    table, types = _build_table(n_rows, n_cols)
    transformer = TableTransformer()

    start = time.perf_counter()
    anon, _ = transformer.anonymize(table, types, ws.engine)
    reverse = ws.engine.reverse_index()
    restored, stats = transformer.restore(anon, set(types), reverse)
    elapsed = time.perf_counter() - start

    assert stats.unknown_cells == 0
    assert restored.rows == table.rows
    assert elapsed < limit, f"{n_rows}x{n_cols}: {elapsed:.1f} c (лимит {limit} c)"
    manager.close_workspace(ws)
    return elapsed


def test_perf_20k_x_20(manager):
    """400 000 ячеек: анонимизация + восстановление за <= 30 с."""
    elapsed = _run(manager, 20_000, 20, limit=30.0)
    print(f"\n20 000 x 20: {elapsed:.2f} c")


@pytest.mark.skipif(os.environ.get("RUN_PERF_FULL") != "1",
                    reason="полный объём ТЗ: RUN_PERF_FULL=1")
def test_perf_100k_x_100(manager):
    """10 000 000 ячеек (полное требование ТЗ Т-8) за <= 30 с."""
    elapsed = _run(manager, 100_000, 100, limit=30.0)
    print(f"\n100 000 x 100: {elapsed:.2f} c")
