"""Базовые модели доменного слоя (сущности и перечисления)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class PiiType(str, Enum):
    """Типы персональных данных (ПДн), поддерживаемые анонимизатором."""

    FULL_NAME = "full_name"        # ФИО
    PHONE = "phone"                # Телефон
    EMAIL = "email"                # E-mail
    ADDRESS = "address"            # Адрес
    DOCUMENT = "document"          # Номер документа
    BIRTH_DATE = "birth_date"      # Дата рождения
    FREE_TEXT = "free_text"        # Свободный текст

    @property
    def title(self) -> str:
        """Русское название типа для интерфейса и отчётов."""
        return _PII_TITLES[self]

    @property
    def prefix(self) -> str:
        """Префикс кода в словаре соответствий (Г-4, раздел 6 ТЗ)."""
        return _PII_PREFIXES[self]


_PII_TITLES = {
    PiiType.FULL_NAME: "ФИО",
    PiiType.PHONE: "Телефон",
    PiiType.EMAIL: "E-mail",
    PiiType.ADDRESS: "Адрес",
    PiiType.DOCUMENT: "Номер документа",
    PiiType.BIRTH_DATE: "Дата рождения",
    PiiType.FREE_TEXT: "Свободный текст",
}

# Префиксы кодов по типам столбцов: ID-000001, PH-000001, EM-000001 и т.д.
_PII_PREFIXES = {
    PiiType.FULL_NAME: "ID",
    PiiType.PHONE: "PH",
    PiiType.EMAIL: "EM",
    PiiType.ADDRESS: "AD",
    PiiType.DOCUMENT: "DOC",
    PiiType.BIRTH_DATE: "BD",
    PiiType.FREE_TEXT: "TX",
}


def is_missing_cell(value: Any) -> bool:
    """Пропуск — пустая ячейка (None или пустая строка). Пропуски не анонимизируются."""
    return value is None or (isinstance(value, str) and value == "")


@dataclass
class TableData:
    """Табличные данные: заголовки + строки (типы ячеек сохраняются).

    Аналог «DataFrame-подобной» структуры из ТЗ, но без зависимости от pandas:
    openpyxl возвращает типизированные значения (str/int/float/datetime/None).
    """

    headers: list[str]
    rows: list[list[Any]]
    name: str = ""  # имя листа Excel / таблицы SQLite (если применимо)

    @property
    def n_rows(self) -> int:
        """Число строк данных (без заголовка)."""
        return len(self.rows)

    @property
    def n_cols(self) -> int:
        """Число столбцов."""
        return len(self.headers)

    def column_values(self, index: int) -> list[Any]:
        """Значения столбца по индексу (пропуски включаются как None/'')."""
        return [row[index] if index < len(row) else None for row in self.rows]


@dataclass
class ColumnSuggestion:
    """Предложение детектора ПДн по одному столбцу (решение за пользователем, F-1)."""

    index: int                # индекс столбца
    header: str               # заголовок
    pii_type: Optional[PiiType]  # предложенный тип (None — ПДн не выявлено)
    confidence: float         # уверенность 0..1
    level: int                # уровень срабатывания: 0 — нет, 1 — заголовки, 2 — regex, 3 — статистика
    reason: str               # пояснение (рус.)
    suspicious: bool = False  # подозрительный столбец (уровень 3, помечается, но не меняется)


@dataclass
class TransformStats:
    """Статистика анонимизации."""

    replaced_cells: int = 0                      # заменённых ячеек
    missing_cells: int = 0                       # пропусков (не тронуты)
    unique_codes_per_column: dict[str, int] = field(default_factory=dict)  # заголовок -> число уникальных кодов


@dataclass
class RestoreStats:
    """Статистика восстановления (деанонимизации)."""

    restored_cells: int = 0                      # восстановленных ячеек
    unknown_cells: int = 0                       # ячеек с неизвестными кодами
    unknown_codes: list[str] = field(default_factory=list)  # примеры неизвестных кодов
    dropped_rows: int = 0                        # исключённых строк (политика drop)
    warnings: list[str] = field(default_factory=list)       # предупреждения (рус.)


class UnknownPolicy(str, Enum):
    """Политика обработки неизвестных кодов при восстановлении (F-4)."""

    KEEP = "keep"    # оставить код как есть (по умолчанию) + предупреждение
    BLANK = "blank"  # очистить ячейку
    DROP = "drop"    # исключить строку целиком

    @property
    def title(self) -> str:
        """Русское название политики."""
        return {
            UnknownPolicy.KEEP: "оставить",
            UnknownPolicy.BLANK: "пусто",
            UnknownPolicy.DROP: "исключить строку",
        }[self]
