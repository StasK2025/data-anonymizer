"""Т-9. Детерминизм и биективность кодов; Т-10 — политика неизвестных (частично)."""

from __future__ import annotations

import re

import pytest

from tests.conftest import NAMES, PASSWORD

CODE_RE = re.compile(r"^[A-Z]+-\d{6}$")


def test_same_value_same_code_within_project(workspace):
    """Т-9: повторное присвоение кода — тот же код; регистр/пробелы нормализуются."""
    engine = workspace.engine
    code1 = engine.code_for_value("Иванов Иван", "full_name")
    code2 = engine.code_for_value("Иванов Иван", "full_name")
    code3 = engine.code_for_value("  иванов иван  ", "phone")  # другой столб тот же value
    assert code1 == code2 == code3
    assert CODE_RE.match(code1)


def test_codes_bijective_no_collisions(workspace):
    """Т-9: разные значения — разные коды; коллизий нет."""
    engine = workspace.engine
    codes = [engine.code_for_value(v, "full_name") for v in NAMES]
    assert len(set(codes)) == len(set(NAMES))  # биективность
    assert all(CODE_RE.match(c) for c in codes)


def test_same_values_map_to_same_codes_on_reopen(manager):
    """Т-9: повторная анонимизация (после переоткрытия проекта) — те же коды."""
    ws1 = manager.create_project("ПроектA", PASSWORD)
    codes1 = [ws1.engine.code_for_value(v, "full_name") for v in NAMES]
    manager.close_workspace(ws1)

    ws2 = manager.open_project("ПроектA", PASSWORD)
    codes2 = [ws2.engine.code_for_value(v, "full_name") for v in NAMES]
    assert codes1 == codes2
    manager.close_workspace(ws2)


def test_different_projects_different_numbering(manager):
    """Т-9: разные проекты — разная нумерация (таблицы нельзя сопоставить)."""
    ws_a = manager.create_project("ПроектA", PASSWORD)
    ws_b = manager.create_project("ПроектB", PASSWORD)
    codes_a = {v: ws_a.engine.code_for_value(v, "phone") for v in NAMES}
    codes_b = {v: ws_b.engine.code_for_value(v, "phone") for v in NAMES}
    # Ключ проекта зависит от соли -> HMAC-числа различаются
    assert any(codes_a[v] != codes_b[v] for v in NAMES)
    manager.close_workspace(ws_a)
    manager.close_workspace(ws_b)


def test_reverse_index_and_value_for_code(workspace):
    """Обратный словарь: код -> исходное значение."""
    engine = workspace.engine
    code = engine.code_for_value("Петрова Мария Сергеевна", "full_name")
    assert engine.value_for_code(code) == "Петрова Мария Сергеевна"
    assert engine.value_for_code("ID-999999") is None
    reverse = engine.reverse_index()
    assert reverse[code] == "Петрова Мария Сергеевна"


def test_prefixes_by_type(workspace):
    """Префиксы кодов соответствуют типу столбца (ТЗ, раздел 6)."""
    engine = workspace.engine
    assert engine.code_for_value("+79161234567", "phone").startswith("PH-")
    assert engine.code_for_value("a@b.ru", "email").startswith("EM-")
    assert engine.code_for_value("4512 345678", "document").startswith("DOC-")
    assert engine.code_for_value("15.03.1985", "birth_date").startswith("BD-")
    assert engine.code_for_value("Иванов Иван", "full_name").startswith("ID-")


def test_normalized_deduplication(workspace):
    """«Иванов», « Иванов » и «ИВАНОВ» — один код (нормализация)."""
    engine = workspace.engine
    c1 = engine.code_for_value("Иванов", "full_name")
    c2 = engine.code_for_value(" Иванов ", "full_name")
    c3 = engine.code_for_value("ИВАНОВ", "full_name")
    assert c1 == c2 == c3
    assert workspace.store.count() == 1


@pytest.mark.parametrize("bad_name", ["", "  ", "имя/с", "имя:в", "..", "имя*"])
def test_invalid_project_name_rejected(manager, bad_name):
    """Недопустимые имена проектов отклоняются."""
    from src.application.errors import InvalidProjectNameError

    with pytest.raises(InvalidProjectNameError):
        manager.create_project(bad_name, PASSWORD)
