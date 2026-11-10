"""Безопасное удаление: перезапись файлов нулями перед удалением (F-5, Т-7)."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

_CHUNK = 1024 * 1024  # 1 МиБ


def secure_delete_file(path: str | Path) -> None:
    """Перезаписать файл нулями (побайтово, с fsync) и удалить его."""
    p = Path(path)
    if not p.exists():
        return
    if p.is_dir():
        secure_delete_dir(p)
        return
    size = p.stat().st_size
    try:
        with open(p, "r+b", buffering=0) as fh:
            remaining = size
            while remaining > 0:
                fh.write(b"\x00" * min(_CHUNK, remaining))
                remaining -= _CHUNK
            fh.flush()
            os.fsync(fh.fileno())
    except OSError:
        # Файл мог быть только что удалён или недоступен — просто продолжаем
        pass
    p.unlink(missing_ok=True)


def secure_delete_dir(path: str | Path) -> None:
    """Перезаписать нулями все файлы каталога и удалить каталог целиком."""
    root = Path(path)
    if not root.exists():
        return
    if root.is_file():
        secure_delete_file(root)
        return
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            secure_delete_file(Path(dirpath) / name)
    shutil.rmtree(root, ignore_errors=True)
