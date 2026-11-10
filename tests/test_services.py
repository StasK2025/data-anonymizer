"""Интеграционные тесты сценариев: журнал, авто-закрытие, словарь, статистика, детектор."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from src.application.anonymize_service import AnonymizeService
from src.application.autolock import AutoLockManager
from src.application.errors import ConfirmationRequired, ProjectExistsError
from src.application.mapping_service import MappingService
from src.application.restore_service import RestorePlanColumn, RestoreService
from src.domain.column_detector import ColumnDetector
from src.domain.models import PiiType, TableData, UnknownPolicy
from tests.conftest import PASSWORD, make_pii_table


# --- Проекты -----------------------------------------------------------------

def test_create_twice_rejected(manager):
    """Повторное создание проекта с тем же именем -> ProjectExistsError."""
    manager.create_project("Дубль", PASSWORD)
    with pytest.raises(ProjectExistsError):
        manager.create_project("Дубль", PASSWORD)


def test_open_missing_project(manager):
    """Открытие несуществующего проекта -> ProjectNotFoundError."""
    from src.application.errors import ProjectNotFoundError

    with pytest.raises(ProjectNotFoundError):
        manager.open_project("Нет", PASSWORD)


# --- Журнал (F-6, без ПДн) ---------------------------------------------------

def test_journal_metadata_only(manager, tmp_path: Path):
    """Журнал содержит метаданные; ни значений, ни паролей (F-6, Г-2)."""
    ws = manager.create_project("Журнал", PASSWORD)
    table = make_pii_table(9)
    service = AnonymizeService()
    service.anonymize(ws, table, {0: PiiType.FULL_NAME, 1: PiiType.PHONE},
                      tmp_path / "anon.csv")
    lines = ws.journal.read()
    manager.close_workspace(ws)

    assert len(lines) >= 2
    text = "\n".join(lines)
    assert "анонимизация" in text
    assert "строк=9" in text
    for secret in (PASSWORD, "Иванов Иван", "Петрова Мария"):
        assert secret not in text


# --- Авто-закрытие (F-7) -----------------------------------------------------

def test_autolock_clears_memory(manager):
    """По истечении таймаута проект закрывается, память очищается."""
    ws = manager.create_project("АвтоЛок", PASSWORD)
    ws.engine.code_for_value("Иванов Иван", "full_name")
    lock = AutoLockManager(timeout_seconds=0.0)
    lock.register(ws)
    time.sleep(0.01)
    locked = lock.sweep()
    assert ws in locked
    assert ws.locked
    assert ws.engine is None and ws.key == b""
    with pytest.raises(Exception):
        ws.require_open()


def test_autolock_not_expired_yet(manager):
    """До истечения таймаута проект остаётся открытым."""
    ws = manager.create_project("Живой", PASSWORD)
    lock = AutoLockManager(timeout_seconds=3600)
    lock.register(ws)
    lock.touch(ws)
    assert lock.sweep() == []
    assert not ws.locked
    manager.close_workspace(ws)


# --- Словарь (F-5) ------------------------------------------------------------

def test_mapping_entries_masked_by_default(workspace):
    """Значения скрыты по умолчанию; при reveal — раскрываются."""
    workspace.engine.code_for_value("Иванов Иван", "full_name")
    workspace.store.flush()
    service = MappingService()

    hidden = service.entries(workspace, reveal=False)
    assert len(hidden) == 1
    assert hidden[0].value is None
    assert "Иванов" not in hidden[0].masked

    shown = service.entries(workspace, reveal=True)
    assert shown[0].value == "Иванов Иван"


def test_export_open_csv_requires_confirmation(workspace, tmp_path: Path):
    """Открытый экспорт словаря — только с подтверждением (F-5)."""
    workspace.engine.code_for_value("Иванов Иван", "full_name")
    workspace.store.flush()
    service = MappingService()
    path = tmp_path / "словарь.csv"
    with pytest.raises(ConfirmationRequired):
        service.export_open_csv(workspace, path, confirm=False)
    assert not path.exists()

    count = service.export_open_csv(workspace, path, confirm=True)
    assert count == 1
    text = path.read_text(encoding="utf-8-sig")
    assert "Иванов Иван" in text


def test_export_import_encrypted_roundtrip(manager, tmp_path: Path):
    """Зашифрованный экспорт -> импорт в тот же проект (словарь пополняется)."""
    ws = manager.create_project("Обмен", PASSWORD)
    ws.engine.code_for_value("Иванов Иван", "full_name")
    ws.store.flush()
    service = MappingService()
    dump = tmp_path / "словарь.map.json"
    assert service.export_encrypted(ws, dump) == 1

    # Импорт повторной записи не создаёт дублей
    assert service.import_encrypted(ws, dump) == 0
    assert ws.store.count() == 1
    manager.close_workspace(ws)


def test_import_encrypted_from_other_project_rejected(manager, tmp_path: Path):
    """Словарь другого проекта (другая соль) не импортируется."""
    ws_a = manager.create_project("ПроектА", PASSWORD)
    ws_a.engine.code_for_value("Иванов Иван", "full_name")
    ws_a.store.flush()
    dump = tmp_path / "словарь.map.json"
    MappingService().export_encrypted(ws_a, dump)
    manager.close_workspace(ws_a)

    ws_b = manager.create_project("ПроектБ", PASSWORD)
    with pytest.raises(Exception):
        MappingService().import_encrypted(ws_b, dump)
    manager.close_workspace(ws_b)


def test_import_open_csv_adds_entries(workspace, tmp_path: Path):
    """Импорт открытого CSV пополняет словарь (с подтверждением)."""
    path = tmp_path / "ввод.csv"
    path.write_text("код;тип_пдн;значение;создан\nID-000424;ФИО;Новое Имя;x\n", encoding="utf-8-sig")
    service = MappingService()
    assert service.import_open_csv(workspace, path, confirm=True) == 1
    assert workspace.engine.value_for_code("ID-000424") == "Новое Имя"


# --- Статистика (F-3) --------------------------------------------------------

def test_stats_without_pii_disclosure(manager, tmp_path: Path):
    """Статистика: строки/уникальные коды/пропуски; значения ПДн не раскрываются."""
    ws = manager.create_project("Стат", PASSWORD)
    table = make_pii_table(9)
    service = AnonymizeService()
    result = service.anonymize(ws, table, {0: PiiType.FULL_NAME}, tmp_path / "anon.csv")

    report = service.compute_stats(result.table, {0: PiiType.FULL_NAME})
    assert report.rows == 9
    assert report.pii_columns == 1
    summary = "\n".join(report.column_lines)
    assert "ФИО:" in summary
    assert "Иванов" not in summary  # значения не раскрываются
    manager.close_workspace(ws)


# --- Детектор ПДн (Г-5, Т-1 уровень) -----------------------------------------

def test_detector_finds_pii_columns():
    """Детектор находит ФИО/телефон/email/паспорт/дату по заголовкам и значениям."""
    table = make_pii_table(9)
    suggestions = ColumnDetector().detect(table)
    by_header = {s.header: s for s in suggestions}
    assert by_header["ФИО"].pii_type == PiiType.FULL_NAME
    assert by_header["Телефон"].pii_type == PiiType.PHONE
    assert by_header["Email"].pii_type == PiiType.EMAIL
    assert by_header["Паспорт"].pii_type == PiiType.DOCUMENT
    assert by_header["Дата рождения"].pii_type == PiiType.BIRTH_DATE
    # Зарплата — числа, ПДн не предложено
    assert by_header["Зарплата"].pii_type is None


def test_detector_value_level_without_header():
    """Уровень 2: значения-телефоны без заголовка-подсказки."""
    table = TableData(
        headers=["Поле без имени"],
        rows=[["+79161234567"], ["89211234567"], ["+79991234567"], ["89031112233"], ["+79269998877"]],
    )
    suggestion = ColumnDetector().detect(table)[0]
    assert suggestion.pii_type == PiiType.PHONE
    assert suggestion.level == 2


def test_detector_statistical_level_marks_suspicious():
    """Уровень 3: уникальные строковые значения -> подозрение, но не автовыбор."""
    rows = [[f"ID-{i:05d}@secret-server"] for i in range(10)]
    table = TableData(headers=["Поле"], rows=rows)
    suggestion = ColumnDetector().detect(table)[0]
    assert suggestion.suspicious is True
    assert suggestion.level == 3
    assert suggestion.pii_type is None  # решение за пользователем


# --- Restore service: именование столбцов ------------------------------------

def test_restore_renames_columns(manager, tmp_path: Path):
    """Восстановление с переименованием столбца по плану."""
    ws = manager.create_project("Имена", PASSWORD)
    from src.domain.models import PiiType as P

    table = TableData(headers=["ФИО", "Прочее"], rows=[["Иванов Иван", "а"], ["Петров Пётр", "б"]])
    service = AnonymizeService()
    anon = service.anonymize(ws, table, {0: P.FULL_NAME}, tmp_path / "anon.csv")
    anon_table = TableData(headers=["Сотрудник", "Прочее"], rows=anon.table.rows)

    plan = [
        RestorePlanColumn(0, "Сотрудник", "ФИО сотрудника"),
        RestorePlanColumn(1, "Прочее", ""),  # не восстанавливать
    ]
    result = RestoreService().restore(ws, anon_table, plan, UnknownPolicy.KEEP,
                                      tmp_path / "restored.csv")
    assert result.table.headers == ["ФИО сотрудника", "Прочее"]
    assert result.table.rows[0][0] == "Иванов Иван"
    assert result.table.rows[0][1] == "а"
    manager.close_workspace(ws)
