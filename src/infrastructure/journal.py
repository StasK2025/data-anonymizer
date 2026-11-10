"""Журнал операций (journal.log): только метаданные, без ПДн и паролей (F-6, Г-2)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional


def _sanitize(text: str) -> str:
    """Одна строка журнала: без переводов строк и управляющих символов."""
    return str(text).replace("\r", " ").replace("\n", " ").strip()


class Journal:
    """Append-only журнал операций проекта."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        """Путь к файлу журнала."""
        return self._path

    def log(
        self,
        action: str,
        filename: Optional[str] = None,
        rows: Optional[int] = None,
        cols: Optional[int] = None,
        note: Optional[str] = None,
    ) -> None:
        """Записать событие: время, действие, файл, число строк/столбцов.

        В журнал не должны попадать значения ячеек и пароли — только метаданные.
        """
        parts = [datetime.now().strftime("%Y-%m-%d %H:%M:%S"), _sanitize(action)]
        if filename:
            parts.append(f"файл={_sanitize(filename)}")
        if rows is not None:
            parts.append(f"строк={rows}")
        if cols is not None:
            parts.append(f"столбцов={cols}")
        if note:
            parts.append(f"прим={_sanitize(note)}")
        line = " | ".join(parts) + "\n"

        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "a", encoding="utf-8") as fh:
            fh.write(line)

    def read(self, limit: Optional[int] = None) -> list[str]:
        """Прочитать строки журнала (последние limit, если указано)."""
        if not self._path.exists():
            return []
        lines = self._path.read_text(encoding="utf-8").splitlines()
        if limit is not None and len(lines) > limit:
            return lines[-limit:]
        return lines
