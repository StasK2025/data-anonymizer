"""Т-10. Неизвестные коды: политика keep / blank / drop + предупреждения."""

from __future__ import annotations

from src.domain.models import PiiType, TableData, UnknownPolicy
from src.domain.table_transformer import TableTransformer
from tests.conftest import PASSWORD


def _make_workspace_table(workspace):
    """Анонимизируем телефонные значения и возвращаем (анонимную таблицу, reverse)."""
    transformer = TableTransformer()
    table = TableData(
        headers=["Телефон"],
        rows=[["+79161234567"], ["+79169876543"], ["+79165555555"]],
    )
    anon, _ = transformer.anonymize(table, {0: PiiType.PHONE}, workspace.engine)
    reverse = workspace.engine.reverse_index()
    return transformer, anon, reverse


def _with_unknown(anon: TableData) -> TableData:
    rows = [list(r) for r in anon.rows]
    rows[1][0] = "PH-999999"  # кода нет в словаре
    return TableData(headers=list(anon.headers), rows=rows)


def test_policy_keep(workspace):
    """keep (по умолчанию): код остаётся, есть предупреждение."""
    transformer, anon, reverse = _make_workspace_table(workspace)
    table = _with_unknown(anon)
    restored, stats = transformer.restore(table, {0}, reverse, policy=UnknownPolicy.KEEP)
    assert restored.rows[1][0] == "PH-999999"
    assert stats.unknown_cells == 1
    assert "PH-999999" in stats.unknown_codes
    assert stats.warnings and "оставить" in stats.warnings[0]
    assert stats.dropped_rows == 0


def test_policy_blank(workspace):
    """blank: ячейка с неизвестным кодом очищается."""
    transformer, anon, reverse = _make_workspace_table(workspace)
    table = _with_unknown(anon)
    restored, stats = transformer.restore(table, {0}, reverse, policy=UnknownPolicy.BLANK)
    assert restored.rows[1][0] is None
    assert stats.unknown_cells == 1


def test_policy_drop(workspace):
    """drop: строка с неизвестным кодом исключается целиком."""
    transformer, anon, reverse = _make_workspace_table(workspace)
    table = _with_unknown(anon)
    restored, stats = transformer.restore(table, {0}, reverse, policy=UnknownPolicy.DROP)
    assert restored.n_rows == 2
    assert stats.dropped_rows == 1
    assert all("PH-999999" not in str(r[0]) for r in restored.rows)


def test_default_policy_is_keep(workspace):
    """По умолчанию — политика keep."""
    transformer, anon, reverse = _make_workspace_table(workspace)
    table = _with_unknown(anon)
    restored, stats = transformer.restore(table, {0}, reverse)
    assert restored.rows[1][0] == "PH-999999"
    assert stats.unknown_cells == 1
