"""Т-1. Статический анализ: запрещённые импорты в src/ — 0 совпадений (Г-1, Г-5).

Ищем импорты: socket, ssl, http, httpx, requests, urllib, ftplib, smtplib,
telnetlib, poplib, imaplib, webbrowser, torch, tensorflow, transformers, sklearn.
Whitelist пуст — никаких исключений.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN = [
    "socket", "ssl", "http", "httpx", "requests", "urllib",
    "ftplib", "smtplib", "telnetlib", "poplib", "imaplib", "webbrowser",
    "torch", "tensorflow", "transformers", "sklearn", "keras", "pandas",
]

_IMPORT_RE = re.compile(
    r"^\s*(?:import|from)\s+(" + "|".join(FORBIDDEN) + r")\b", re.MULTILINE
)


def _sources() -> list[Path]:
    files = sorted((ROOT / "src").rglob("*.py"))
    files.append(ROOT / "main.py")
    return files


def test_no_forbidden_imports_in_src():
    """Т-1: в src/ и main.py нет ни одного запрещённого импорта."""
    offenders: list[str] = []
    for path in _sources():
        text = path.read_text(encoding="utf-8")
        for match in _IMPORT_RE.finditer(text):
            line_no = text[: match.start()].count("\n") + 1
            offenders.append(f"{path.relative_to(ROOT)}:{line_no}: {match.group(0).strip()}")
    assert offenders == [], "обнаружены запрещённые импорты:\n" + "\n".join(offenders)


def test_sources_exist():
    """Каркас src/ по ТЗ присутствует (4 уровня + тесты + main.py)."""
    for part in (
        "src/gui", "src/application", "src/domain", "src/infrastructure", "tests",
    ):
        assert (ROOT / part).is_dir(), f"нет каталога {part}"
    assert (ROOT / "main.py").is_file()
