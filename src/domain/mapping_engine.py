"""Движок биективного маппинга «значение ↔ код» (Г-4, разделы 6–8 ТЗ).

- Формат кодов: префикс по типу столбца + 6 цифр (ID-000001, PH-000001, DOC-000001).
- Детерминированность внутри проекта: одно нормализованное значение (обрезка
  пробелов + lower) — один код; поиск выполняется по HMAC-SHA256 от значения.
- Разные проекты дают разную нумерацию: ключ проекта зависит от случайной соли,
  поэтому HMAC-число для одного и того же значения в разных проектах различается.
- Биективность: коды уникальны; коллизии HMAC-чисел разрешаются детерминированным
  линейным пробингом и фиксируются в словаре.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from src.domain.crypto_layer import CryptoLayer
from src.domain.errors import MappingError
from src.domain.models import PiiType
from src.domain.ports import MappingStore

# Разделитель метки типа и значения в упакованной строке (контроль-символ \x1f)
_PACK_SEP = "\x1f"


def _pack_value(value) -> str:
    """Упаковать значение с меткой исходного типа: "тип\\x1fзначение".

    Метка типа нужна, чтобы восстановление вернуло исходный Python-тип ячейки
    (int/float/str/datetime), а не только строку. Ручная упаковка быстрее json
    на массовых объёмах (лимит ТЗ — 30 с на 100k строк).
    """
    type_name = type(value).__name__
    text = value if isinstance(value, str) else str(value)
    return type_name + _PACK_SEP + text


def _unpack_value(text: str):
    """Распаковать значение (обратная операция к _pack_value)."""
    type_name, sep, raw = text.partition(_PACK_SEP)
    if not sep:
        return text
    try:
        if type_name == "int":
            return int(raw)
        if type_name == "float":
            return float(raw)
        if type_name == "bool":
            return raw == "True"
        if type_name == "datetime":
            return datetime.fromisoformat(raw)
        if type_name == "date":
            return date.fromisoformat(raw)
    except (ValueError, TypeError):
        return raw
    return raw


class MappingEngine:
    """Биективный словарь «значение ↔ код» поверх хранилища и крипто-слоя."""

    MAX_CODE = 1_000_000  # диапазон 6-значных номеров: 000000..999999

    def __init__(self, store: MappingStore, crypto: CryptoLayer) -> None:
        """Создать движок поверх открытого хранилища и крипто-слоя проекта."""
        self._store = store
        self._crypto = crypto
        self._pending = 0  # число несброшенных вставок

    _FLUSH_EVERY = 20_000  # как часто сбрасывать вставки на диск

    # --- Нормализация --------------------------------------------------------

    @staticmethod
    def normalize(value) -> str:
        """Нормализация значения для поиска: строка + обрезка пробелов + lower."""
        text = value if isinstance(value, str) else str(value)
        return text.strip().lower()

    # --- Прямой словарь: значение -> код ------------------------------------

    def code_for_value(self, value, pii_type: PiiType) -> str:
        """Получить код для значения; при отсутствии — выдать новый и сохранить.

        Одинаковые значения (после нормализации) в рамках проекта получают
        одинаковый код независимо от столбца (Г-4).
        """
        if isinstance(pii_type, str):
            pii_type = PiiType(pii_type)  # допускаем передачу значения PiiType.value
        normalized = self.normalize(value)
        value_hash = self._crypto.hmac_hash(normalized)
        code = self._store.find_code_by_hash(value_hash)
        if code is not None:
            return code

        prefix = pii_type.prefix
        number = int.from_bytes(value_hash[:8], "big") % self.MAX_CODE
        code_candidate: Optional[str] = None
        for _ in range(self.MAX_CODE):
            candidate = f"{prefix}-{number:06d}"
            if not self._store.code_exists(candidate):
                code_candidate = candidate
                break
            number = (number + 1) % self.MAX_CODE
        if code_candidate is None:
            raise MappingError(f"исчерпан диапазон кодов префикса {prefix}")
        code = code_candidate

        value_enc = self._crypto.encrypt(_pack_value(value))
        self._store.insert_mapping(code, value_enc, value_hash, pii_type.value)
        self._pending += 1
        if self._pending >= self._FLUSH_EVERY:
            self._store.flush()
            self._pending = 0
        return code

    # --- Обратный словарь: код -> значение ----------------------------------

    def value_for_code(self, code: str) -> Optional[str]:
        """Расшифровать значение по коду; None, если кода нет в словаре."""
        row = self._store.find_by_code(code)
        if row is None:
            return None
        return _unpack_value(self._crypto.decrypt(row.value_enc))

    def reverse_index(self) -> dict[str, str]:
        """Полный обратный индекс «код -> значение» в памяти (для восстановления)."""
        pairs = getattr(self._store, "code_value_pairs", None)
        if callable(pairs):  # быстрый путь хранилища (только код + шифротекст)
            return {code: _unpack_value(self._crypto.decrypt(enc)) for code, enc in pairs()}
        index: dict[str, str] = {}
        for row in self._store.all_mappings():
            index[row.code] = _unpack_value(self._crypto.decrypt(row.value_enc))
        return index

    def decrypt_raw(self, value_enc: bytes) -> str:
        """Расшифровать сохранённое значение как чистый текст (для сервисов)."""
        return _unpack_value(self._crypto.decrypt(value_enc))

    def contains_hash(self, value_hash: bytes) -> bool:
        """Есть ли значение с таким HMAC в словаре (без раскрытия значения)."""
        return self._store.find_by_hash(value_hash) is not None

    def count(self) -> int:
        """Число записей словаря."""
        return self._store.count()
