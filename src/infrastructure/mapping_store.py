"""Хранилище маппинга в SQLite (project.db) + метаданные проекта (project.meta.json).

Схема (раздел 6 ТЗ):
    mapping(index TEXT PK, value_enc BLOB, value_hash BLOB, column_type TEXT, created_at TEXT)

meta.json (не секретно, кроме хеша): версия, дата, соль KDF, итерации,
токен проверки пароля (hmac от ключа — Г-3), формат кодов.
"""

from __future__ import annotations

import base64
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.domain.crypto_layer import CryptoLayer
from src.domain.errors import CryptoError
from src.domain.ports import MappingRow

META_FILENAME = "project.meta.json"
DB_FILENAME = "project.db"
META_VERSION = 1
CODE_FORMAT = "ПРЕФИКС-NNNNNN (6 цифр), например ID-000001"


class WrongPasswordError(Exception):
    """Неверный пароль проекта — маппинг нечитаем (Г-3, Т-5)."""


# --- Хранилище (адаптер порта MappingStore) ---------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS mapping (
    "index"     TEXT PRIMARY KEY,
    value_enc   BLOB NOT NULL,
    value_hash  BLOB NOT NULL,
    column_type TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
"""
# Примечание: уникальность value_hash/code обеспечивается кэшами SqliteMappingStore
# и биективной логикой MappingEngine (Г-4); отдельный UNIQUE-индекс по value_hash
# снят ради скорости массовых вставок (вдвое дешевле вставка в B-дерево).


class SqliteMappingStore:
    """SQLite-реализация хранилища словаря соответствий."""

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._conn: Optional[sqlite3.Connection] = None
        # Кэши «в памяти» для быстрых проверок биективности (Г-4) на больших объёмах
        self._hash_to_code: dict[bytes, str] = {}
        self._codes: set[str] = set()
        self._pending_rows: list[tuple] = []

    @property
    def path(self) -> Path:
        """Путь к файлу БД."""
        return self._path

    def open(self) -> None:
        """Открыть/создать БД, навязать схему и заполнить кэши."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: операции выполняются по одной из GUI-потоков
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        # WAL + NORMAL: пакетные коммиты на порядок быстрее (ТЗ: лимит 30 с);
        # в крайнем случае теряется только последняя несброшенная пачка словаря.
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        # Массовые вставки: без авто-чекпоинтов (иначе запись страниц в WAL
        # доминирует на объёмах 100k+ строк); чекпоинт — при закрытии (close).
        self._conn.execute("PRAGMA wal_autocheckpoint=0")
        # Крупный кэш страниц для скорости чтения индекса кодов
        self._conn.execute("PRAGMA cache_size=-65536")  # 64 МиБ
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self._hash_to_code.clear()
        self._codes.clear()
        for code, value_hash in self._conn.execute('SELECT "index", value_hash FROM mapping'):
            self._hash_to_code[bytes(value_hash)] = code
            self._codes.add(code)

    def _require(self) -> sqlite3.Connection:
        if self._conn is None:
            raise CryptoError("хранилище не открыто")
        return self._conn

    # --- Быстрые кэшированные проверки (биективность, Г-4) ------------------

    def find_code_by_hash(self, value_hash: bytes) -> Optional[str]:
        """Код по HMAC значения — из кэша памяти (без запроса к БД)."""
        return self._hash_to_code.get(bytes(value_hash))

    def code_exists(self, code: str) -> bool:
        """Занят ли код — из кэша памяти."""
        return code in self._codes

    # --- MappingStore --------------------------------------------------------

    def find_by_hash(self, value_hash: bytes) -> Optional[MappingRow]:
        conn = self._require()
        self.flush()
        row = conn.execute(
            'SELECT "index", value_enc, value_hash, column_type, created_at '
            "FROM mapping WHERE value_hash = ?",
            (value_hash,),
        ).fetchone()
        return self._row(row)

    def find_by_code(self, code: str) -> Optional[MappingRow]:
        conn = self._require()
        self.flush()
        row = conn.execute(
            'SELECT "index", value_enc, value_hash, column_type, created_at '
            'FROM mapping WHERE "index" = ?',
            (code,),
        ).fetchone()
        return self._row(row)

    def insert_mapping(self, code: str, value_enc: bytes, value_hash: bytes, column_type: str) -> None:
        """Добавить запись (пакетно, через flush); кэши обновляются сразу.

        created_at проставляется на пачку при flush (экономия на массовых объёмах).
        """
        self._require()  # проверяем, что хранилище открыто
        self._pending_rows.append((code, value_enc, value_hash, column_type))
        self._hash_to_code[bytes(value_hash)] = code
        self._codes.add(code)

    def flush(self) -> None:
        """Подтвердить накопленные вставки одним batch-запросом (commit)."""
        if self._conn is None or not self._pending_rows:
            return
        created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self._conn.executemany(
            'INSERT INTO mapping ("index", value_enc, value_hash, column_type, created_at) '
            "VALUES (?, ?, ?, ?, ?)",
            [(c, e, h, t, created_at) for (c, e, h, t) in self._pending_rows],
        )
        self._conn.commit()
        self._pending_rows.clear()

    def all_mappings(self) -> list[MappingRow]:
        conn = self._require()
        self.flush()
        rows = conn.execute(
            'SELECT "index", value_enc, value_hash, column_type, created_at '
            'FROM mapping ORDER BY "index"'
        ).fetchall()
        return [r for r in (self._row(row) for row in rows) if r is not None]

    def code_value_pairs(self) -> list[tuple[str, bytes]]:
        """Только коды и шифротексты (для обратного индекса, легче all_mappings)."""
        conn = self._require()
        self.flush()
        return [(row[0], bytes(row[1])) for row in
                conn.execute('SELECT "index", value_enc FROM mapping').fetchall()]

    def count(self) -> int:
        conn = self._require()
        self.flush()
        return int(conn.execute("SELECT COUNT(*) FROM mapping").fetchone()[0])

    def close(self) -> None:
        """Закрыть соединение (чекпоинт WAL, commit) и очистить кэши памяти."""
        if self._conn is not None:
            try:
                self.flush()
                self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            finally:
                self._conn.close()
                self._conn = None
        self._hash_to_code.clear()
        self._codes.clear()
        self._pending_rows.clear()

    @staticmethod
    def _row(raw) -> Optional[MappingRow]:
        if raw is None:
            return None
        return MappingRow(
            code=raw[0],
            value_enc=bytes(raw[1]),
            value_hash=bytes(raw[2]),
            column_type=raw[3],
            created_at=raw[4],
        )


# --- Метаданные проекта ------------------------------------------------------

def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"))


def build_meta(password: str, iterations: int = CryptoLayer.ITERATIONS) -> tuple[dict, bytes]:
    """Создать метаданные проекта для нового пароля. Возвращает (meta, ключ).

    Пароль не сохраняется: только соль, итерации и токен-хеш для проверки (Г-3).
    """
    salt = os.urandom(CryptoLayer.SALT_SIZE)
    key = CryptoLayer.derive_key(password, salt, iterations)
    token = CryptoLayer(key).password_token()
    meta = {
        "version": META_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "code_format": CODE_FORMAT,
        "kdf": {
            "algorithm": "PBKDF2-HMAC-SHA256",
            "iterations": iterations,
            "salt_b64": _b64(salt),
        },
        "password_check_b64": _b64(token),
    }
    return meta, key


def key_from_meta(meta: dict, password: str) -> bytes:
    """Вывести и проверить ключ по метаданным; неверный пароль -> WrongPasswordError."""
    try:
        kdf = meta["kdf"]
        salt = _unb64(kdf["salt_b64"])
        iterations = int(kdf["iterations"])
        token = _unb64(meta["password_check_b64"])
    except (KeyError, ValueError, TypeError) as exc:
        raise WrongPasswordError("повреждённые метаданные проекта") from exc

    key = CryptoLayer.derive_key(password, salt, iterations)
    if not CryptoLayer(key).verify_token(token):
        raise WrongPasswordError("неверный пароль — маппинг нечитаем")
    return key


def save_meta(path: str | Path, meta: dict) -> None:
    """Сохранить метаданные (JSON, UTF-8)."""
    Path(path).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def load_meta(path: str | Path) -> dict:
    """Загрузить метаданные проекта."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WrongPasswordError(f"не удалось прочитать метаданные проекта: {exc}") from exc
