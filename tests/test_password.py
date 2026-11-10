"""Т-5. Пароль: неверный пароль -> отказ, маппинг нечитаем (Г-3)."""

from __future__ import annotations

import base64
import shutil
import sqlite3
from pathlib import Path

import pytest

from src.application.errors import WeakPasswordError, WrongPasswordError
from src.domain.crypto_layer import CryptoLayer
from src.domain.errors import DecryptionError
from src.domain.models import PiiType
from tests.conftest import PASSWORD

SECRET = "Иванов Иван Иванович"


def test_wrong_password_refused(manager):
    """Открытие с неверным паролем -> WrongPasswordError."""
    manager.create_project("Защищён", PASSWORD)
    with pytest.raises(WrongPasswordError):
        manager.open_project("Защищён", "неверный пароль")


def test_short_password_refused(manager):
    """Пароль < 8 символов -> WeakPasswordError (F-7)."""
    with pytest.raises(WeakPasswordError):
        manager.create_project("Слабый", "1234567")


def test_mapping_unreadable_with_wrong_key(manager, tmp_path: Path):
    """Копия project.db: данные не расшифровываются без верного ключа (Т-5)."""
    ws = manager.create_project("База", PASSWORD)
    ws.engine.code_for_value(SECRET, "full_name")
    ws.store.flush()
    # Закрываем проект до копирования: при закрытии выполняется чекпоинт WAL,
    # и project.db становится самодостаточной копией словаря.
    db_path = ws.store.path
    manager.close_workspace(ws)
    db_copy = tmp_path / "project_copy.db"
    shutil.copyfile(db_path, db_copy)

    # Прямое чтение SQLite: шифротекст, открытого текста нет
    conn = sqlite3.connect(db_copy)
    row = conn.execute('SELECT "index", value_enc FROM mapping').fetchone()
    conn.close()
    assert row is not None
    assert SECRET.encode("utf-8") not in bytes(row[1])
    assert str(row[0]).startswith("ID-")

    # Расшифровка «неверным ключом» невозможна
    wrong_key = CryptoLayer.derive_key("другой пароль", b"0123456789abcdef")
    with pytest.raises(DecryptionError):
        CryptoLayer(wrong_key).decrypt(bytes(row[1]))


def test_no_plaintext_in_db_or_meta(manager, tmp_path: Path):
    """Ни в project.db, ни в meta.json нет пароля и открытых значений (Г-2, Г-3)."""
    ws = manager.create_project("Проверка", PASSWORD)
    ws.engine.code_for_value(SECRET, "full_name")
    ws.store.flush()
    root = ws.root
    manager.close_workspace(ws)

    db_bytes = (root / "project.db").read_bytes()
    meta_bytes = (root / "project.meta.json").read_bytes()
    for secret in (PASSWORD, SECRET):
        assert secret.encode("utf-8") not in db_bytes
        assert secret.encode("utf-8") not in meta_bytes


def test_meta_contains_only_salt_and_hash(manager):
    """meta.json: только соль, итерации и хеш-токен; пароля нет (Г-3)."""
    import json

    ws = manager.create_project("Мета", PASSWORD)
    meta = json.loads((ws.root / "project.meta.json").read_text(encoding="utf-8"))
    manager.close_workspace(ws)
    assert meta["kdf"]["algorithm"] == "PBKDF2-HMAC-SHA256"
    assert meta["kdf"]["iterations"] == 600_000
    salt = base64.b64decode(meta["kdf"]["salt_b64"])
    assert len(salt) == 16
    assert "password" not in {k.lower() for k in meta if k != "password_check_b64"}
