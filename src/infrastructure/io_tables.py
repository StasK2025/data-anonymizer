"""Чтение/запись таблиц: CSV, XLSX, XLS, JSON, SQLite (раздел 4 ТЗ).

- CSV: разделители ';' ',' '\\t'; кодировки UTF-8, UTF-8-BOM, Windows-1251 (автоопределение).
- XLSX: все листы (openpyxl), типы ячеек сохраняются.
- XLS: чтение через xlrd; запись в XLS недоступна (нет живой библиотеки) —
  результат сохраняется как .xlsx с пометкой (см. отклонение в README).
- JSON: массив записей (list of dicts).
- SQLite: выбор таблицы; запись — создание таблицы в файле БД.
- pandas не используется: структура TableData (заголовки + строки) достаточна.
"""

from __future__ import annotations

import csv
import io
import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from src.domain.models import TableData

# --- Форматы ----------------------------------------------------------------

READ_EXTENSIONS = {".csv", ".xlsx", ".xls", ".json", ".db", ".sqlite", ".sqlite3"}
WRITE_EXTENSIONS = {".csv", ".xlsx", ".xls", ".json", ".db", ".sqlite", ".sqlite3"}

_FILE_DIALOG_FILTER = (
    "Таблицы (*.csv *.xlsx *.xls *.json *.db *.sqlite *.sqlite3);;Все файлы (*)"
)

_DELIMITERS = [";", ",", "\t"]
_ENCODINGS = ["utf-8-sig", "utf-8", "cp1251"]


class TableReadError(Exception):
    """Не удалось прочитать таблицу (понятное пользователю сообщение)."""


class TableWriteError(Exception):
    """Не удалось записать таблицу."""


@dataclass
class WriteResult:
    """Результат записи: фактический путь и пометка (например, XLS -> XLSX)."""

    path: Path
    note: Optional[str] = None


def file_dialog_filter() -> str:
    """Фильтр для диалогов выбора файлов."""
    return _FILE_DIALOG_FILTER


def detect_format(path: str | Path) -> str:
    """Определить формат по расширению файла ('.csv', '.xlsx', ...)."""
    ext = Path(path).suffix.lower()
    if ext not in READ_EXTENSIONS:
        raise TableReadError(f"неподдерживаемый формат файла: '{ext or 'без расширения'}'")
    return ext


def list_table_names(path: str | Path) -> list[Optional[str]]:
    """Имена «таблиц» внутри файла: листы Excel, таблицы SQLite; иначе [None]."""
    p = Path(path)
    ext = detect_format(p)
    if not p.exists():
        raise TableReadError(f"файл не найден: {p}")
    if ext in (".xlsx", ".xls"):
        if ext == ".xlsx":
            from openpyxl import load_workbook

            wb = load_workbook(p, read_only=True, data_only=True)
            try:
                return list(wb.sheetnames)
            finally:
                wb.close()
        import xlrd

        book = xlrd.open_workbook(p)
        return list(book.sheet_names())
    if ext in (".db", ".sqlite", ".sqlite3"):
        conn = _connect_readonly(p)
        try:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
            return [r[0] for r in rows]
        finally:
            conn.close()
    return [None]


def read_table(path: str | Path, table: Optional[str] = None) -> TableData:
    """Прочитать таблицу из файла (для Excel/SQLite — указать лист/таблицу при необходимости)."""
    p = Path(path)
    ext = detect_format(p)
    if not p.exists():
        raise TableReadError(f"файл не найден: {p}")
    if ext == ".csv":
        return _read_csv(p)
    if ext == ".xlsx":
        return _read_xlsx(p, table)
    if ext == ".xls":
        return _read_xls(p, table)
    if ext == ".json":
        return _read_json(p)
    return _read_sqlite(p, table)


def write_table(table: TableData, path: str | Path, delimiter: str = ";") -> WriteResult:
    """Записать таблицу в файл; формат — по расширению.

    Для .xls (legacy, нет живой библиотеки записи) результат сохраняется как .xlsx
    с пометкой в WriteResult.note.
    """
    p = Path(path)
    ext = p.suffix.lower()
    if ext not in WRITE_EXTENSIONS:
        raise TableWriteError(f"неподдерживаемый формат для записи: '{ext or 'без расширения'}'")
    p.parent.mkdir(parents=True, exist_ok=True)

    if ext == ".csv":
        _write_csv(table, p, delimiter)
        return WriteResult(p)
    if ext == ".xlsx":
        _write_xlsx(table, p)
        return WriteResult(p)
    if ext == ".xls":
        note = "Формат XLS не поддерживает запись (xlrd только для чтения) — результат сохранён как XLSX"
        new_path = p.with_suffix(".xlsx")
        _write_xlsx(table, new_path)
        return WriteResult(new_path, note)
    if ext == ".json":
        _write_json(table, p)
        return WriteResult(p)
    _write_sqlite(table, p)
    return WriteResult(p)


# --- CSV --------------------------------------------------------------------

def _decode_text(raw: bytes) -> str:
    """Автоопределение кодировки: UTF-8-BOM, UTF-8, Windows-1251."""
    for encoding in _ENCODINGS:
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise TableReadError(
        "не удалось определить кодировку файла (поддерживаются UTF-8, UTF-8-BOM, Windows-1251)"
    )


def _detect_delimiter(text: str) -> str:
    """Выбрать разделитель по максимальному числу вхождений в начале файла."""
    sample = "\n".join(text.splitlines()[:10])
    best, best_count = ",", 0
    for delim in _DELIMITERS:
        count = sample.count(delim)
        if count > best_count:
            best, best_count = delim, count
    return best


def _read_csv(path: Path) -> TableData:
    if path.stat().st_size == 0:
        raise TableReadError("файл пуст (0 байт)")
    text = _decode_text(path.read_bytes())
    delimiter = _detect_delimiter(text)
    try:
        reader = csv.reader(io.StringIO(text), delimiter=delimiter)
        records = [row for row in reader]
    except csv.Error as exc:
        raise TableReadError(f"ошибка разбора CSV: {exc}") from exc
    return _records_to_table(records)


def _records_to_table(records: list[list[str]]) -> TableData:
    """Первая строка — заголовки; далее — данные (пустой файл -> пустая таблица)."""
    if not records:
        return TableData(headers=[], rows=[])
    headers = [(h or "").lstrip("\ufeff") for h in records[0]]
    width = len(headers)
    rows: list[list[str]] = []
    for rec in records[1:]:
        row = list(rec[:width]) + [""] * max(width - len(rec), 0)
        rows.append(row)
    return TableData(headers=headers, rows=rows)


def _write_csv(table: TableData, path: Path, delimiter: str) -> None:
    # utf-8-sig — чтобы Excel корректно открывал кириллицу
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh, delimiter=delimiter, lineterminator="\r\n")
        writer.writerow([str(h) for h in table.headers])
        for row in table.rows:
            writer.writerow(["" if cell is None else cell for cell in row])


# --- XLSX -------------------------------------------------------------------

def _normalize_excel_rows(raw_rows: list[tuple], sheet_name: str) -> TableData:
    rows = [list(r) for r in raw_rows]
    # Отрезаем полностью пустые строки в конце
    while rows and all(v is None for v in rows[-1]):
        rows.pop()
    if not rows:
        return TableData(headers=[], rows=[], name=sheet_name)
    header_row = rows[0]
    # ширина по заголовку и по данным
    width = max(len(header_row), max((len(r) for r in rows), default=0))
    headers = [
        str(h).lstrip("\ufeff") if h is not None else f"Столбец {i + 1}"
        for i, h in enumerate(header_row)
    ]
    while len(headers) < width:
        headers.append(f"Столбец {len(headers) + 1}")
    data: list[list[Any]] = []
    for raw in rows[1:]:
        row = list(raw[:width]) + [None] * max(width - len(raw), 0)
        data.append(row)
    return TableData(headers=headers, rows=data, name=sheet_name)


def _read_xlsx(path: Path, sheet: Optional[str] = None) -> TableData:
    from openpyxl import load_workbook

    try:
        wb = load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:  # openpyxl бросает разные типы ошибок
        raise TableReadError(f"не удалось открыть XLSX: {exc}") from exc
    try:
        if sheet is not None and sheet not in wb.sheetnames:
            raise TableReadError(f"лист '{sheet}' не найден в книге")
        ws = wb[sheet] if sheet else wb.active
        if ws is None:
            raise TableReadError("в книге нет листов")
        raw_rows = list(ws.iter_rows(values_only=True))
        return _normalize_excel_rows(raw_rows, ws.title)
    finally:
        wb.close()


def _write_xlsx(table: TableData, path: Path) -> None:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = (table.name or "Лист1")[:31] or "Лист1"
    ws.append([str(h) for h in table.headers])
    for row in table.rows:
        ws.append(list(row))
    wb.save(path)


# --- XLS (только чтение) ----------------------------------------------------

def _read_xls(path: Path, sheet: Optional[str] = None) -> TableData:
    try:
        book = xlrd_open(path)
    except Exception as exc:
        raise TableReadError(f"не удалось открыть XLS: {exc}") from exc
    names = book.sheet_names()
    if sheet is not None:
        if sheet not in names:
            raise TableReadError(f"лист '{sheet}' не найден в книге")
        sh = book.sheet_by_name(sheet)
    else:
        sh = book.sheet_by_index(0)
    rows: list[list[Any]] = []
    for r in range(sh.nrows):
        rows.append([_xlrd_cell_to_value(sh.cell(r, c), book) for c in range(sh.ncols)])
    return _normalize_excel_rows([tuple(r) for r in rows], sh.name)


def xlrd_open(path: Path):
    """Открыть .xls через xlrd (импорт здесь — тонкая прослойка для тестов/моков)."""
    import xlrd

    return xlrd.open_workbook(path)


def _xlrd_cell_to_value(cell, book) -> Any:
    """Преобразовать ячейку xlrd в python-значение (даты -> datetime)."""
    import xlrd

    t = cell.ctype
    if t == xlrd.XL_CELL_TEXT:
        return cell.value
    if t == xlrd.XL_CELL_NUMBER:
        value = cell.value
        return int(value) if float(value).is_integer() else value
    if t == xlrd.XL_CELL_DATE:
        try:
            return xlrd.xldate_as_datetime(cell.value, book.datemode)
        except Exception:
            return None
    if t == xlrd.XL_CELL_BOOLEAN:
        return bool(cell.value)
    return None  # EMPTY / BLANK / ERROR


# --- JSON -------------------------------------------------------------------

def _read_json(path: Path) -> TableData:
    text = _decode_text(path.read_bytes())
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise TableReadError(f"ошибка разбора JSON: {exc}") from exc
    if not isinstance(data, list):
        raise TableReadError("JSON: ожидается массив записей (list of objects)")
    if not data:
        return TableData(headers=[], rows=[])
    if not isinstance(data[0], dict):
        raise TableReadError("JSON: записи должны быть объектами вида {поле: значение}")
    headers: list[str] = []
    for record in data:
        if isinstance(record, dict):
            for key in record:
                if key not in headers:
                    headers.append(str(key))
    rows = [[record.get(h) for h in headers] for record in data]
    return TableData(headers=headers, rows=rows)


def _write_json(table: TableData, path: Path) -> None:
    records = [
        {str(h): (row[i] if i < len(row) else None) for i, h in enumerate(table.headers)}
        for row in table.rows
    ]
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(records, fh, ensure_ascii=False, indent=2, default=str)


# --- SQLite -----------------------------------------------------------------

def _connect_readonly(path: Path) -> sqlite3.Connection:
    """Открыть БД строго на чтение (исходники не изменяются, Г-6)."""
    uri = f"file:{path.as_posix()}?mode=ro"
    try:
        return sqlite3.connect(uri, uri=True, check_same_thread=False)
    except sqlite3.Error as exc:
        raise TableReadError(f"не удалось открыть БД SQLite: {exc}") from exc


def _read_sqlite(path: Path, table: Optional[str] = None) -> TableData:
    conn = _connect_readonly(path)
    try:
        names = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        ]
        if not names:
            raise TableReadError("в базе SQLite нет таблиц")
        if table is None:
            table = names[0]
        if table not in names:
            raise TableReadError(f"таблица '{table}' не найдена в базе")
        quoted = table.replace('"', '""')
        cur = conn.execute(f'SELECT * FROM "{quoted}"')
        headers = [d[0] for d in cur.description]
        rows = [list(r) for r in cur.fetchall()]
        return TableData(headers=headers, rows=rows, name=table)
    except sqlite3.Error as exc:
        raise TableReadError(f"ошибка чтения SQLite: {exc}") from exc
    finally:
        conn.close()


def _sanitize_table_name(stem: str) -> str:
    """Имя таблицы из имени файла (только буквы/цифры/подчёркивания)."""
    name = re.sub(r"\W+", "_", stem, flags=re.UNICODE).strip("_")
    return name or "таблица"


def _write_sqlite(table: TableData, path: Path) -> None:
    table_name = _sanitize_table_name(path.stem)
    quoted_name = table_name.replace('"', '""')
    columns_sql = ", ".join(f'"{str(h).replace(chr(34), chr(34) * 2)}" TEXT' for h in table.headers) \
        or '"нет_данных" TEXT'
    try:
        conn = sqlite3.connect(path)
        try:
            conn.execute(f'DROP TABLE IF EXISTS "{quoted_name}"')
            conn.execute(f'CREATE TABLE "{quoted_name}" ({columns_sql})')
            if table.headers:
                placeholders = ", ".join("?" for _ in table.headers)
                col_names = ", ".join(
                    f'"{str(h).replace(chr(34), chr(34) * 2)}"' for h in table.headers
                )
                conn.executemany(
                    f'INSERT INTO "{quoted_name}" ({col_names}) VALUES ({placeholders})',
                    [tuple(row[: len(table.headers)]) for row in table.rows],
                )
            conn.commit()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        raise TableWriteError(f"ошибка записи SQLite: {exc}") from exc
