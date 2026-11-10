"""Порты (интерфейсы) доменного слоя.

Domain описывает, какие операции нужны от хранилища маппинга, не зная о SQLite
(реализация — в src/infrastructure/mapping_store.py, принцип «адаптер/порт»).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable


@dataclass(frozen=True)
class MappingRow:
    """Одна запись словаря соответствий."""

    code: str            # индекс/код, например ID-000001
    value_enc: bytes     # значение, зашифрованное AES-256-GCM
    value_hash: bytes    # HMAC-SHA256 нормализованного значения
    column_type: str     # тип ПДн (PiiType.value)
    created_at: str      # ISO-время создания записи


@runtime_checkable
class MappingStore(Protocol):
    """Интерфейс хранилища маппинга, требуемый от infrastructure-слоя."""

    def find_code_by_hash(self, value_hash: bytes) -> Optional[str]:
        """Быстрый путь: код по HMAC нормализованного значения (кэш в памяти)."""

    def code_exists(self, code: str) -> bool:
        """Быстрый путь: есть ли уже такой код (кэш в памяти)."""

    def find_by_hash(self, value_hash: bytes) -> Optional[MappingRow]:
        """Найти запись по HMAC нормализованного значения (биективность, Г-4)."""

    def find_by_code(self, code: str) -> Optional[MappingRow]:
        """Найти запись по коду."""

    def insert_mapping(self, code: str, value_enc: bytes, value_hash: bytes, column_type: str) -> None:
        """Добавить новую запись словаря (без немедленного commit — см. flush)."""

    def flush(self) -> None:
        """Сбросить накопленные записи на диск (commit)."""

    def all_mappings(self) -> list[MappingRow]:
        """Все записи словаря."""

    def count(self) -> int:
        """Число записей словаря."""

    def close(self) -> None:
        """Закрыть хранилище (память очищается вызывающей стороной)."""
