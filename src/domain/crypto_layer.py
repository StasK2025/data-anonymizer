"""Криптографический слой: PBKDF2-HMAC-SHA256 (600K), AES-256-GCM, HMAC-SHA256.

Гарантии ТЗ:
- Г-2: маппинг хранится только зашифрованным (AES-256-GCM);
- Г-3: пароль хранится лишь как хеш для проверки.

Domain не обращается к файловой системе и сети — только к переданным параметрам.
"""

from __future__ import annotations

import hashlib
import hmac as _hmac
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from src.domain.errors import CryptoError, DecryptionError

# Быстрый однострочный HMAC (без создания объекта хеша)
_hmac_digest = _hmac.digest


class CryptoLayer:
    """Крипто-операции проекта: шифрование значений и хеши для поиска дублей."""

    KEY_SIZE = 32            # AES-256
    NONCE_SIZE = 12          # 96-бит nonce для GCM
    SALT_SIZE = 16           # соль KDF (ТЗ, раздел 6)
    ITERATIONS = 600_000     # итерации PBKDF2 (ТЗ, раздел 3)

    # Контекстная метка для токена проверки пароля (не является секретом)
    _TOKEN_CONTEXT = b"local-anonymizer/password-check/v1"

    def __init__(self, key: bytes) -> None:
        """Создать слой с уже выведенным ключом (32 байта)."""
        if not isinstance(key, (bytes, bytearray)) or len(key) != self.KEY_SIZE:
            raise CryptoError(f"ключ должен быть {self.KEY_SIZE} байт")
        self._key = bytes(key)
        self._aesgcm = AESGCM(self._key)

    # --- KDF -----------------------------------------------------------------

    @staticmethod
    def derive_key(password: str, salt: bytes, iterations: int = ITERATIONS) -> bytes:
        """Вывести ключ из пароля: PBKDF2-HMAC-SHA256, 600 000 итераций, соль 16 байт."""
        if not salt:
            raise CryptoError("соль не может быть пустой")
        return hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, iterations, dklen=CryptoLayer.KEY_SIZE
        )

    # --- Шифрование значений (Г-2) ------------------------------------------

    def encrypt(self, value: str) -> bytes:
        """Зашифровать значение: формат nonce(12) || ciphertext || tag(16), AES-256-GCM."""
        if not isinstance(value, str):
            value = str(value)
        nonce = os.urandom(self.NONCE_SIZE)
        ciphertext = self._aesgcm.encrypt(nonce, value.encode("utf-8"), None)
        return nonce + ciphertext

    def decrypt(self, blob: bytes) -> str:
        """Расшифровать значение из формата nonce || ciphertext || tag.

        При неверном ключе (в т.ч. неверный пароль проекта) — DecryptionError.
        """
        if not isinstance(blob, (bytes, bytearray)) or len(blob) <= self.NONCE_SIZE:
            raise DecryptionError("повреждённые данные: слишком короткий блок")
        blob = bytes(blob)
        nonce, ciphertext = blob[: self.NONCE_SIZE], blob[self.NONCE_SIZE :]
        try:
            plaintext = self._aesgcm.decrypt(nonce, ciphertext, None)
        except InvalidTag as exc:
            raise DecryptionError("расшифровка не удалась: неверный ключ или данные повреждены") from exc
        return plaintext.decode("utf-8")

    # --- Хеши для поиска дублей ---------------------------------------------

    def hmac_hash(self, normalized_value: str) -> bytes:
        """HMAC-SHA256(нормализованное значение, ключ проекта) — для поиска дублей без раскрытия."""
        return _hmac_digest(self._key, normalized_value.encode("utf-8"), "sha256")

    # --- Токен проверки пароля (Г-3) -----------------------------------------

    def password_token(self) -> bytes:
        """Токен для проверки пароля: хеш от ключа, пароль не хранится и не восстанавливается."""
        return _hmac.new(self._key, self._TOKEN_CONTEXT, hashlib.sha256).digest()

    def verify_token(self, token: bytes) -> bool:
        """Сверить сохранённый токен с выведенным из введённого пароля."""
        return _hmac.compare_digest(self.password_token(), bytes(token))
