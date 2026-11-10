"""Детектор столбцов с ПДн: 3 уровня детерминированных правил (Г-5, F-1).

Уровень 1 — заголовки по словарю шаблонов (ФИО, телефон, email, адрес, документ,
дата рождения и т.п.).
Уровень 2 — regex по значениям ячеек (телефоны +7(9xx)/8..., email-маски,
даты, номера паспорта формата 4-2-4 и др.).
Уровень 3 — статистика: доля уникальных строковых значений близка к 100 %.

Никаких нейросетей и ML — только детерминированные правила (Г-5). Решение о
выборе столбцов всегда за пользователем.
"""

from __future__ import annotations

import re
from typing import Callable, Optional

from src.domain.models import ColumnSuggestion, PiiType, TableData, is_missing_cell

# --- Уровень 1: словарь шаблонов заголовков ---------------------------------

# Порядок важен: более специфичные шаблоны (дата рождения) — раньше общих.
_HEADER_PATTERNS: list[tuple[re.Pattern, PiiType, str]] = [
    (re.compile(r"дата\s+рождения|день\s+рождения|birth[\s_-]?date|birthday|\bдр\b|д\.р\.", re.I),
     PiiType.BIRTH_DATE, "заголовок соответствует шаблону «дата рождения»"),
    (re.compile(r"телефон|тел\.|\bphone\b|\bmobile\b|моб\.|контактный\s+номер|номер\s+телефона|cell\s*phone", re.I),
     PiiType.PHONE, "заголовок соответствует шаблону «телефон»"),
    (re.compile(r"e[\s_.-]?mail|почт|эл\.\s*адрес|электронн\w+\s+адрес", re.I),
     PiiType.EMAIL, "заголовок соответствует шаблону «e-mail/почта»"),
    (re.compile(r"паспорт|документ|\bdoc\b|snils|снилс|\binn\b|\bинн\b|серия\s+и\s+номер|удостоверение", re.I),
     PiiType.DOCUMENT, "заголовок соответствует шаблону «документ/паспорт»"),
    (re.compile(r"адрес|\baddress\b|место\s+(?:жительства|проживания|регистрации)|прописк", re.I),
     PiiType.ADDRESS, "заголовок соответствует шаблону «адрес»"),
    (re.compile(r"^\s*фио\s*$|фи\.?\s*о\.?|фамилия\s+имя\s+отчество|полное\s+имя|\bfull[\s_-]?name\b|"
                r"\bфамилия\b|\bsurname\b|\blast[\s_-]?name\b|^\s*имя\b|\bfirst[\s_-]?name\b|отчество|\bpatronymic\b", re.I),
     PiiType.FULL_NAME, "заголовок соответствует шаблону «ФИО»"),
]

# --- Уровень 2: regex по значениям ------------------------------------------

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-zА-Яа-я]{2,}$")
_DATE_DOT_RE = re.compile(r"^\d{2}\.\d{2}\.(?:19|20)\d{2}$")
_DATE_ISO_RE = re.compile(r"^(?:19|20)\d{2}-\d{2}-\d{2}$")
_DATE_US_RE = re.compile(r"^(?:0?[1-9]|1[0-2])/(?:0?[1-9]|[12]\d|3[01])/(?:19|20)\d{2}$")
_PASSPORT_424_RE = re.compile(r"^\d{4}\s?\d{2}\s?\d{4}$")
_PHONE_CORE_RE = re.compile(r"^\d{10,15}$")
_ADDRESS_WORD_RE = re.compile(
    r"(?:^|\s)(?:ул\.|улица|проспект|пр\.|пер\.|переулок|наб\.|шоссе|бульвар|б-р|"
    r"д\.|дом|кв\.|квартира|стр\.|корп\.|область|обл\.|район|р-н|г\.|город)\b",
    re.I,
)

# Минимум непустых значений для статистического уровня
_MIN_SAMPLES = 5


def _digits_only(text: str) -> str:
    """Убрать из строки всё, кроме цифр (для проверки телефонных масок)."""
    return re.sub(r"\D", "", text)


def _is_phone_value(text: str) -> bool:
    """Телефон: 10–15 цифр, начинается на 8/7 или имеет «+»."""
    stripped = text.strip()
    digits = _digits_only(stripped)
    if not _PHONE_CORE_RE.fullmatch(digits):
        return False
    return stripped.startswith("+") or digits.startswith(("8", "7"))


def _is_email_value(text: str) -> bool:
    """E-mail по классической маске local@domain.tld."""
    return bool(_EMAIL_RE.fullmatch(text.strip()))


def _is_date_value(text: str) -> bool:
    """Дата в форматах ДД.ММ.ГГГГ, ГГГГ-ММ-ДД, ММ/ДД/ГГГГ."""
    s = text.strip()
    return bool(_DATE_DOT_RE.fullmatch(s) or _DATE_ISO_RE.fullmatch(s) or _DATE_US_RE.fullmatch(s))


def _is_passport_value(text: str) -> bool:
    """Номер паспорта РФ формата 4-2-4 цифры."""
    return bool(_PASSPORT_424_RE.fullmatch(text.strip()))


def _is_address_value(text: str) -> bool:
    """Адрес — наличие типичных адресных слов (ул., д., г. и т.п.)."""
    return bool(_ADDRESS_WORD_RE.search(text))


# Упорядоченные проверки: (тип, функция, описание)
_VALUE_CHECKS: list[tuple[PiiType, Callable[[str], bool], str]] = [
    (PiiType.EMAIL, _is_email_value, "значения похожи на e-mail (маска local@domain.tld)"),
    (PiiType.BIRTH_DATE, _is_date_value, "значения похожи на дату (ДД.ММ.ГГГГ / ГГГГ-ММ-ДД)"),
    (PiiType.PHONE, _is_phone_value, "значения похожи на телефон (10–15 цифр, +7/8)"),
    (PiiType.DOCUMENT, _is_passport_value, "значения похожи на номер паспорта (4-2-4)"),
    (PiiType.ADDRESS, _is_address_value, "значения содержат типичные адресные слова"),
]

# Доля совпадений на уровне 2, чтобы предложить тип
_MATCH_THRESHOLD = 0.75
# Доля уникальных значений на уровне 3 (статистика)
_UNIQUE_THRESHOLD = 0.98


class ColumnDetector:
    """3-уровневый детерминированный детектор ПДн по столбцам таблицы."""

    def __init__(self, sample_size: int = 200) -> None:
        """sample_size — сколько непустых значений анализировать на уровне 2/3."""
        self.sample_size = sample_size

    def detect(self, table: TableData) -> list[ColumnSuggestion]:
        """Предложить типы ПДн для всех столбцов таблицы (решение — за пользователем)."""
        suggestions: list[ColumnSuggestion] = []
        for idx, header in enumerate(table.headers):
            suggestions.append(self._detect_column(table, idx, str(header)))
        return suggestions

    # --- Уровни --------------------------------------------------------------

    def _detect_column(self, table: TableData, idx: int, header: str) -> ColumnSuggestion:
        # Уровень 1: заголовок
        header_type, header_reason = self._match_header(header)

        # Уровень 2: regex по значениям
        values = self._sample_values(table, idx)
        value_type, ratio, value_reason = self._match_values(values)

        # Уровень 3: статистика уникальности
        stats_hit, stats_reason = self._match_statistics(table, idx, values)

        # Комбинированное решение
        if header_type is not None and value_type is header_type:
            return ColumnSuggestion(idx, header, header_type, 0.97, 1,
                                    f"{header_reason}; {value_reason}")
        if header_type is not None:
            return ColumnSuggestion(idx, header, header_type, 0.9, 1, header_reason)
        if value_type is not None:
            return ColumnSuggestion(idx, header, value_type, min(0.75 + ratio / 4, 0.95), 2, value_reason)
        if stats_hit:
            return ColumnSuggestion(idx, header, None, 0.4, 3, stats_reason, suspicious=True)
        return ColumnSuggestion(idx, header, None, 0.0, 0, "ПДн не выявлено")

    @staticmethod
    def _match_header(header: str) -> tuple[Optional[PiiType], str]:
        for pattern, pii_type, reason in _HEADER_PATTERNS:
            if pattern.search(header):
                return pii_type, reason
        return None, ""

    def _sample_values(self, table: TableData, idx: int) -> list[str]:
        """Непустые строковые значения столбца (не более sample_size)."""
        out: list[str] = []
        for value in table.column_values(idx):
            if is_missing_cell(value):
                continue
            out.append(value if isinstance(value, str) else str(value))
            if len(out) >= self.sample_size:
                break
        return out

    @staticmethod
    def _match_values(values: list[str]) -> tuple[Optional[PiiType], float, str]:
        """Уровень 2: лучшая маска с долей совпадений >= _MATCH_THRESHOLD."""
        if not values:
            return None, 0.0, ""
        best_type: Optional[PiiType] = None
        best_ratio = 0.0
        best_reason = ""
        for pii_type, check, reason in _VALUE_CHECKS:
            matched = sum(1 for v in values if check(v))
            ratio = matched / len(values)
            if ratio >= _MATCH_THRESHOLD and ratio > best_ratio:
                best_type, best_ratio, best_reason = pii_type, ratio, reason
        return best_type, best_ratio, best_reason

    @staticmethod
    def _match_statistics(table: TableData, idx: int, values: list[str]) -> tuple[bool, str]:
        """Уровень 3: строковой столбец с долей уникальных значений ~100 % — подозрение."""
        if len(values) < _MIN_SAMPLES:
            return False, ""
        non_empty_total = sum(
            1 for v in table.column_values(idx) if not is_missing_cell(v)
        )
        if non_empty_total < _MIN_SAMPLES:
            return False, ""
        # Числовые/датовые значения не считаем «подозрительными» по одной уникальности
        if any(not isinstance(v, str) for v in table.column_values(idx) if not is_missing_cell(v)):
            return False, ""
        unique_ratio = len(set(values)) / len(values)
        if unique_ratio >= _UNIQUE_THRESHOLD:
            return True, (
                f"статистика: {unique_ratio:.0%} значений уникальны (уровень 3) — "
                "возможны идентификаторы или ПДн; автоматически не выбирается"
            )
        return False, ""
