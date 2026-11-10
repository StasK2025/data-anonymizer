"""Форматы ввода/вывода: CSV/XLSX/JSON/SQLite (+ заметка для XLS)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.domain.models import TableData
from src.infrastructure import io_tables
from src.infrastructure.io_tables import TableReadError, TableWriteError

SAMPLE = TableData(
    headers=["ФИО", "Телефон", "Число"],
    rows=[["Иванов Иван", "+79161234567", 1], ["Эльф 🧝‍♀️", "", 2.5], ["", None, 3]],
)


@pytest.mark.parametrize("ext", [".csv", ".xlsx", ".json"])
def test_roundtrip_formats(tmp_path: Path, ext: str):
    """Запись -> чтение: заголовки и значения сохраняются."""
    path = tmp_path / f"таблица{ext}"
    io_tables.write_table(SAMPLE, path)
    loaded = io_tables.read_table(path)
    assert loaded.headers == SAMPLE.headers
    assert loaded.n_rows == SAMPLE.n_rows
    assert loaded.rows[0][0] == "Иванов Иван"
    assert "🧝‍♀️" in loaded.rows[1][0]


def test_csv_roundtrip_values_with_delimiters(tmp_path: Path):
    """Значения с ';' и переводами строк переживают CSV-раунд-трип (кавычки)."""
    table = TableData(headers=["Заметка"], rows=[["a;b"], ["c,d"], ["е\nф"]])
    path = tmp_path / "raw.csv"
    io_tables.write_table(table, path, delimiter=";")
    loaded = io_tables.read_table(path)
    assert [r[0] for r in loaded.rows] == ["a;b", "c,d", "е\nф"]


def test_xlsx_multiple_sheets(tmp_path: Path):
    """Все листы книги доступны через list_table_names/read_table."""
    from openpyxl import Workbook

    path = tmp_path / "книга.xlsx"
    wb = Workbook()
    wb.active.title = "Лист1"
    wb.active.append(["ФИО"])
    wb.active.append(["Иванов"])
    ws2 = wb.create_sheet("Лист2")
    ws2.append(["Email"])
    ws2.append(["i@x.ru"])
    wb.save(path)

    assert set(io_tables.list_table_names(path)) == {"Лист1", "Лист2"}
    first = io_tables.read_table(path)
    assert first.name == "Лист1" and first.rows[0][0] == "Иванов"
    second = io_tables.read_table(path, "Лист2")
    assert second.rows[0][0] == "i@x.ru"


def test_sqlite_read_and_list(tmp_path: Path):
    """SQLite: чтение таблицы и список таблиц; данные не изменяются (Г-6)."""
    db = tmp_path / "данные.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE клиенты (ФИО TEXT, Телефон TEXT)")
    conn.execute("INSERT INTO клиенты VALUES (?, ?)", ("Иванов Иван", "+79161234567"))
    conn.commit()
    before = db.read_bytes()
    conn.close()

    assert io_tables.list_table_names(db) == ["клиенты"]
    table = io_tables.read_table(db, "клиенты")
    assert table.headers == ["ФИО", "Телефон"]
    assert table.rows[0] == ["Иванов Иван", "+79161234567"]
    assert db.read_bytes() == before  # исходная БД не изменена


def test_sqlite_write(tmp_path: Path):
    """SQLite: запись результата в новую БД."""
    path = tmp_path / "результат.db"
    io_tables.write_table(SAMPLE, path)
    loaded = io_tables.read_table(path)
    assert loaded.headers == SAMPLE.headers
    assert loaded.n_rows == SAMPLE.n_rows


def test_xls_write_converts_to_xlsx(tmp_path: Path):
    """XLS не поддерживает запись -> результат сохраняется как .xlsx с пометкой."""
    path = tmp_path / "старый_формат.xls"
    result = io_tables.write_table(SAMPLE, path)
    assert result.path.suffix == ".xlsx"
    assert result.path.exists()
    assert result.note and "XLSX" in result.note
    assert not path.exists()


def test_unsupported_write_extension(tmp_path: Path):
    """Запись в неподдерживаемый формат -> понятная ошибка."""
    with pytest.raises(TableWriteError):
        io_tables.write_table(SAMPLE, tmp_path / "файл.docx")


def test_json_not_list_raises(tmp_path: Path):
    """JSON не-массив -> понятная ошибка."""
    path = tmp_path / "объект.json"
    path.write_text('{"a": 1}', encoding="utf-8")
    with pytest.raises(TableReadError):
        io_tables.read_table(path)


def test_json_records_union_of_keys(tmp_path: Path):
    """JSON: заголовки — объединение ключей записей."""
    path = tmp_path / "записи.json"
    path.write_text('[{"а": 1, "б": 2}, {"б": 3, "в": 4}]', encoding="utf-8")
    table = io_tables.read_table(path)
    assert table.headers == ["а", "б", "в"]
    assert table.rows[1] == [None, 3, 4]
