"""Т-4. Границы: пустой файл, 1 столбец, дубликаты, пропуски, 1251, BOM."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.domain.models import PiiType, TableData, is_missing_cell
from src.domain.table_transformer import TableTransformer
from src.infrastructure import io_tables
from src.infrastructure.io_tables import TableReadError
from tests.conftest import PASSWORD


# --- CSV: кодировки и разделители -------------------------------------------

def test_csv_windows1251(manager, tmp_path: Path):
    """CSV в Windows-1251 читается корректно."""
    path = tmp_path / "cp1251.csv"
    content = "ФИО;Город\nИванов Иван;Москва\nПетров Пётр;Казань\n"
    path.write_bytes(content.encode("cp1251"))
    table = io_tables.read_table(path)
    assert table.headers == ["ФИО", "Город"]
    assert table.rows[0][0] == "Иванов Иван"


def test_csv_utf8_bom(manager, tmp_path: Path):
    """CSV с BOM: заголовок без \\ufeff."""
    path = tmp_path / "bom.csv"
    path.write_bytes("ФИО;Телефон\nИванов;+79161234567\n".encode("utf-8-sig"))
    table = io_tables.read_table(path)
    assert table.headers == ["ФИО", "Телефон"]


def test_csv_comma_inside_quoted_values(tmp_path: Path):
    """Разделитель ';', запятые внутри кавычек не ломают разбор."""
    path = tmp_path / "quotes.csv"
    path.write_text('адрес;примечание\n"ул. Ленина, д. 5";"цена: 1, 2"\n', encoding="utf-8")
    table = io_tables.read_table(path)
    assert table.rows[0][0] == "ул. Ленина, д. 5"
    assert table.rows[0][1] == "цена: 1, 2"


def test_csv_tab_delimiter(tmp_path: Path):
    """TSV-файл (разделитель табуляция)."""
    path = tmp_path / "tab.csv"
    path.write_text("ФИО\tEmail\nИванов\ti@x.ru\n", encoding="utf-8")
    table = io_tables.read_table(path)
    assert table.headers == ["ФИО", "Email"]


# --- Пустые и вырожденные ----------------------------------------------------

def test_empty_file_raises_understandable_error(tmp_path: Path):
    """Полностью пустой файл (0 байт) -> понятная ошибка, без падения."""
    path = tmp_path / "пусто.csv"
    path.write_bytes(b"")
    with pytest.raises(TableReadError):
        io_tables.read_table(path)


def test_headers_only_csv_ok(tmp_path: Path):
    """Файл только с заголовками -> таблица 0 строк."""
    path = tmp_path / "только_заголовки.csv"
    path.write_text("ФИО;Телефон\n", encoding="utf-8")
    table = io_tables.read_table(path)
    assert table.n_rows == 0
    assert table.headers == ["ФИО", "Телефон"]


def test_single_column_table(workspace):
    """Одна колонка: анонимизация и восстановление работают."""
    transformer = TableTransformer()
    table = TableData(headers=["Телефон"], rows=[["+79161234567"], [""], ["89160001123"], [None]])
    anon, stats = transformer.anonymize(table, {0: PiiType.PHONE}, workspace.engine)
    assert stats.replaced_cells == 2
    assert stats.missing_cells == 2
    assert anon.rows[1][0] == "" and anon.rows[3][0] is None  # пропуски не тронуты
    restored, rstats = transformer.restore(anon, {0}, workspace.engine.reverse_index())
    assert restored.rows == table.rows


def test_duplicates_share_one_code(workspace):
    """Дубликаты значений -> один код; пропуски не трогаются."""
    transformer = TableTransformer()
    table = TableData(headers=["Email"], rows=[["a@b.ru"], ["a@b.ru"], [""], ["c@d.ru"], [None]])
    anon, stats = transformer.anonymize(table, {0: PiiType.EMAIL}, workspace.engine)
    assert anon.rows[0][0] == anon.rows[1][0]
    assert stats.unique_codes_per_column["Email"] == 2
    assert workspace.store.count() == 2


def test_missing_detection():
    """Пропуск — None или пустая строка; пробелы — значение (сохраняется)."""
    assert is_missing_cell(None)
    assert is_missing_cell("")
    assert not is_missing_cell(" ")
    assert not is_missing_cell(0)


def test_unsupported_extension(tmp_path: Path):
    """Неподдерживаемое расширение -> понятная ошибка."""
    with pytest.raises(TableReadError):
        io_tables.read_table(tmp_path / "файл.docx")


def test_missing_file(tmp_path: Path):
    """Отсутствующий файл -> понятная ошибка."""
    with pytest.raises(TableReadError):
        io_tables.read_table(tmp_path / "нет_такого.csv")


# --- Типы ячеек XLSX ---------------------------------------------------------

def test_xlsx_preserves_cell_types(tmp_path: Path):
    """Числа и даты в XLSX не превращаются в строки при чтении."""
    from datetime import datetime

    path = tmp_path / "типы.xlsx"
    table = TableData(headers=["Число", "Дата", "Текст"],
                      rows=[[42, datetime(2020, 1, 2), "привет"], [3.14, None, "мир"]])
    io_tables.write_table(table, path)
    loaded = io_tables.read_table(path)
    assert loaded.rows[0][0] == 42
    assert isinstance(loaded.rows[0][1], datetime)
    assert loaded.rows[1][0] == 3.14
