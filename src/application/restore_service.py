"""Сценарий восстановления ПДн: пароль -> словарь -> замена кодов -> новый файл (П-2, F-4)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from src.application.project_service import ProjectWorkspace
from src.domain.models import RestoreStats, TableData, UnknownPolicy
from src.domain.table_transformer import TableTransformer
from src.infrastructure import io_tables

ProgressCallback = Optional[Callable[[int, int], None]]


@dataclass
class RestorePlanColumn:
    """План восстановления одного столбца исходной (анонимной) таблицы."""

    src_index: int            # индекс столбца в анонимной таблице
    src_header: str           # его заголовок
    target_header: str        # заголовок в результате; "" — столбец не восстанавливать


@dataclass
class RestoreResult:
    """Итог восстановления."""

    output_path: Path
    table: TableData
    stats: RestoreStats
    note: Optional[str] = None


class RestoreService:
    """Сценарий деанонимизации по зашифрованному словарю проекта."""

    def __init__(self, transformer: Optional[TableTransformer] = None) -> None:
        self.transformer = transformer or TableTransformer()

    def restore(
        self,
        workspace: ProjectWorkspace,
        table: TableData,
        plan: list[RestorePlanColumn],
        policy: UnknownPolicy = UnknownPolicy.KEEP,
        output_path: str | Path = "restored.xlsx",
        progress: ProgressCallback = None,
    ) -> RestoreResult:
        """Восстановить значения выбранных столбцов и записать НОВЫЙ файл (Г-6).

        Неотмеченные столбцы проходят без изменений; неизвестные коды
        обрабатываются по политике (оставить/пусто/исключить строку).
        """
        workspace.require_open()
        reverse = workspace.engine.reverse_index()
        restore_indices = [c.src_index for c in plan if (c.target_header or "").strip()]

        transformed, stats = self.transformer.restore(
            table, restore_indices, reverse, policy=policy, progress=progress
        )

        # Переименовать восстановленные столбцы по плану
        headers = list(transformed.headers)
        for column in plan:
            target = (column.target_header or "").strip()
            if target and 0 <= column.src_index < len(headers):
                headers[column.src_index] = target
        restored_table = TableData(headers=headers, rows=transformed.rows, name=transformed.name)

        out_path = Path(output_path)
        result = io_tables.write_table(restored_table, out_path)
        workspace.journal.log(
            "восстановление",
            filename=result.path.name,
            rows=restored_table.n_rows,
            cols=restored_table.n_cols,
            note=f"политика={policy.value}, неизвестных={stats.unknown_cells}",
        )
        return RestoreResult(output_path=result.path, table=restored_table, stats=stats, note=result.note)


def auto_plan(table: TableData) -> list[RestorePlanColumn]:
    """Автоматический план сопоставления столбцов: восстанавливаем все столбцы.

    Заголовки сохраняются; при необходимости пользователь правит их в мастере.
    """
    return [
        RestorePlanColumn(src_index=i, src_header=str(h), target_header=str(h))
        for i, h in enumerate(table.headers)
    ]
