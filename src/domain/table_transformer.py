"""Трансформация таблиц: замена ячеек на коды и обратно (F-2, F-4)."""

from __future__ import annotations

from typing import Callable, Iterable, Optional

from src.domain.mapping_engine import MappingEngine
from src.domain.models import (
    PiiType,
    RestoreStats,
    TableData,
    TransformStats,
    UnknownPolicy,
    is_missing_cell,
)

ProgressCallback = Optional[Callable[[int, int], None]]


class TableTransformer:
    """Анонимизация и восстановление таблиц по словарю соответствий."""

    # --- Анонимизация (П-1) --------------------------------------------------

    def anonymize(
        self,
        table: TableData,
        columns_with_types: dict[int, PiiType],
        engine: MappingEngine,
        progress: ProgressCallback = None,
    ) -> tuple[TableData, TransformStats]:
        """Заменить значения выбранных столбцов на коды.

        Пропуски (None / пустая строка) не трогаются; неотмеченные столбцы
        сохраняются как есть (в них работают формулы/сводные, F-2).
        """
        stats = TransformStats()
        unique_sets: dict[int, set[str]] = {idx: set() for idx in columns_with_types}
        total = max(len(table.rows) * len(columns_with_types), 1)
        done = 0

        out_rows: list[list] = []
        for row in table.rows:
            new_row = list(row)
            for idx, pii_type in columns_with_types.items():
                if idx < len(new_row):
                    value = new_row[idx]
                    if is_missing_cell(value):
                        stats.missing_cells += 1
                    else:
                        code = engine.code_for_value(value, pii_type)
                        new_row[idx] = code
                        unique_sets[idx].add(code)
                        stats.replaced_cells += 1
                done += 1
                if progress is not None and done % 10_000 == 0:
                    progress(done, total)
            out_rows.append(new_row)

        if progress is not None:
            progress(total, total)
        for idx, codes in unique_sets.items():
            header = table.headers[idx] if idx < len(table.headers) else f"#{idx}"
            stats.unique_codes_per_column[header] = len(codes)
        return TableData(headers=list(table.headers), rows=out_rows, name=table.name), stats

    # --- Восстановление (П-2, F-4) ------------------------------------------

    def restore(
        self,
        table: TableData,
        columns: Iterable[int],
        reverse_mapping: dict[str, str],
        policy: UnknownPolicy = UnknownPolicy.KEEP,
        progress: ProgressCallback = None,
    ) -> tuple[TableData, RestoreStats]:
        """Заменить коды выбранных столбцов на исходные значения.

        Политика неизвестных кодов (кода нет в словаре):
        - KEEP (по умолчанию) — оставить код, вывести предупреждение;
        - BLANK — очистить ячейку;
        - DROP — исключить строку целиком.
        """
        stats = RestoreStats()
        col_set = sorted({int(i) for i in columns})
        total = max(len(table.rows) * max(len(col_set), 1), 1)
        done = 0

        out_rows: list[list] = []
        unknown_seen: set[str] = set()
        for row in table.rows:
            new_row = list(row)
            drop_row = False
            for idx in col_set:
                if idx < len(new_row):
                    value = new_row[idx]
                    if not is_missing_cell(value):
                        text = value if isinstance(value, str) else str(value)
                        original = reverse_mapping.get(text)
                        if original is not None:
                            new_row[idx] = original
                            stats.restored_cells += 1
                        else:
                            stats.unknown_cells += 1
                            if text not in unknown_seen and len(unknown_seen) < 20:
                                unknown_seen.add(text)
                            if policy is UnknownPolicy.BLANK:
                                new_row[idx] = None
                            elif policy is UnknownPolicy.DROP:
                                drop_row = True
                            # KEEP: значение остаётся как есть
                done += 1
                if progress is not None and done % 10_000 == 0:
                    progress(done, total)

            if drop_row:
                stats.dropped_rows += 1
            else:
                out_rows.append(new_row)

        stats.unknown_codes = sorted(unknown_seen)
        if progress is not None:
            progress(total, total)

        if stats.unknown_cells:
            codes_preview = ", ".join(stats.unknown_codes[:5])
            stats.warnings.append(
                f"Неизвестных кодов: {stats.unknown_cells} (политика: {policy.title}); "
                f"примеры: {codes_preview}"
            )
        if stats.dropped_rows:
            stats.warnings.append(f"Исключено строк с неизвестными кодами: {stats.dropped_rows}")

        return TableData(headers=list(table.headers), rows=out_rows, name=table.name), stats
