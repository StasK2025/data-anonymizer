"""Сценарий анонимизации: детект ПДн -> замена на коды -> запись копии (П-1, F-1, F-2)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from src.application.project_service import ProjectWorkspace
from src.domain.column_detector import ColumnDetector
from src.domain.models import (
    ColumnSuggestion,
    PiiType,
    TableData,
    TransformStats,
)
from src.domain.table_transformer import TableTransformer
from src.infrastructure import io_tables

ProgressCallback = Optional[Callable[[int, int], None]]


@dataclass
class AnonymizeResult:
    """Итог анонимизации."""

    output_path: Path
    table: TableData                      # анонимная таблица (для предпросмотра в GUI)
    stats: TransformStats
    note: Optional[str] = None            # пометка формата (например, XLS -> XLSX)
    source_name: str = ""


@dataclass
class StatsReport:
    """Отчёт статистики (F-3): без раскрытия ПДн."""

    rows: int = 0
    columns: int = 0
    pii_columns: int = 0
    missing_total: int = 0
    column_lines: list[str] = field(default_factory=list)


class AnonymizeService:
    """Сценарии: предложение столбцов ПДн, анонимизация в файл, статистика."""

    def __init__(
        self,
        detector: Optional[ColumnDetector] = None,
        transformer: Optional[TableTransformer] = None,
    ) -> None:
        self.detector = detector or ColumnDetector()
        self.transformer = transformer or TableTransformer()

    def detect_columns(self, table: TableData) -> list[ColumnSuggestion]:
        """Предложить столбцы ПДн (3 уровня, Г-5); решение — за пользователем."""
        return self.detector.detect(table)

    def anonymize(
        self,
        workspace: ProjectWorkspace,
        table: TableData,
        columns_with_types: dict[int, PiiType],
        output_path: str | Path,
        progress: ProgressCallback = None,
    ) -> AnonymizeResult:
        """Анонимизировать таблицу и записать результат в НОВЫЙ файл (Г-6).

        Исходный файл не изменяется; результат — <имя>__anon.<расширение>.
        """
        workspace.require_open()
        out_path = Path(output_path)
        transformed, stats = self.transformer.anonymize(
            table, columns_with_types, workspace.engine, progress=progress
        )
        result = io_tables.write_table(transformed, out_path)
        workspace.journal.log(
            "анонимизация",
            filename=result.path.name,
            rows=transformed.n_rows,
            cols=transformed.n_cols,
            note=f"столбцов ПДн={len(columns_with_types)}",
        )
        return AnonymizeResult(
            output_path=result.path,
            table=transformed,
            stats=stats,
            note=result.note,
            source_name=table.name,
        )

    def compute_stats(self, table: TableData, columns_with_types: dict[int, PiiType]) -> StatsReport:
        """Статистика анонимной таблицы: строки, уникальные коды, пропуски (F-3)."""
        report = StatsReport(rows=table.n_rows, columns=table.n_cols, pii_columns=len(columns_with_types))
        for idx, header in enumerate(table.headers):
            values = table.column_values(idx)
            missing = sum(1 for v in values if v is None or v == "")
            non_missing = [v for v in values if not (v is None or v == "")]
            unique = len({str(v) for v in non_missing})
            pii = columns_with_types.get(idx)
            report.missing_total += missing
            report.column_lines.append(
                f"{header}: непустых={len(non_missing)}, уникальных={unique}, "
                f"пропусков={missing}"
                + (f", тип ПДн={pii.title}" if pii else "")
            )
        return report
