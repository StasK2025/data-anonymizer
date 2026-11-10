"""Крипто-слой: PBKDF2 (600K), AES-256-GCM, HMAC-SHA256 (Г-2, Г-3)."""

from __future__ import annotations

import hashlib

import pytest

from src.domain.crypto_layer import CryptoLayer
from src.domain.errors import CryptoError, DecryptionError


def test_derive_key_deterministic_with_same_salt():
    salt = b"0123456789abcdef"
    k1 = CryptoLayer.derive_key("пароль123", salt)
    k2 = CryptoLayer.derive_key("пароль123", salt)
    assert k1 == k2
    assert len(k1) == 32


def test_derive_key_differs_by_password_and_salt():
    salt = b"0123456789abcdef"
    k1 = CryptoLayer.derive_key("пароль123", salt)
    k2 = CryptoLayer.derive_key("пароль124", salt)
    k3 = CryptoLayer.derive_key("пароль123", b"fedcba9876543210")
    assert k1 != k2
    assert k1 != k3


def test_pbkdf2_uses_600k_iterations():
    """Проверяем параметры KDF против ручного расчёта hashlib (600 000 итераций)."""
    salt = b"salt16bytes------"
    expected = hashlib.pbkdf2_hmac("sha256", "pwd12345".encode(), salt, 600_000, dklen=32)
    assert CryptoLayer.derive_key("pwd12345", salt) == expected


def test_encrypt_decrypt_roundtrip_unicode():
    crypto = CryptoLayer(CryptoLayer.derive_key("пароль", b"salt16bytes------"))
    for value in ["Иванов Иван", "emoji 🧝‍♀️🐉", "спецсимволы #;,\"'", "  пробелы  ", ""]:
        assert crypto.decrypt(crypto.encrypt(value)) == value


def test_ciphertext_contains_no_plaintext_and_fresh_nonce():
    crypto = CryptoLayer(CryptoLayer.derive_key("пароль", b"salt16bytes------"))
    value = "Иванов Иван Иванович"
    blob1 = crypto.encrypt(value)
    blob2 = crypto.encrypt(value)
    assert blob1 != blob2  # новый nonce при каждом шифровании
    assert value.encode("utf-8") not in blob1
    assert len(blob1) > 12 + len(value)  # nonce + ciphertext + tag


def test_decrypt_with_wrong_key_fails():
    salt = b"0123456789abcdef"
    good = CryptoLayer(CryptoLayer.derive_key("пароль", salt))
    bad = CryptoLayer(CryptoLayer.derive_key("неверно", salt))
    blob = good.encrypt("секрет")
    with pytest.raises(DecryptionError):
        bad.decrypt(blob)


def test_hmac_hash_deterministic_and_key_dependent():
    salt = b"0123456789abcdef"
    c1 = CryptoLayer(CryptoLayer.derive_key("пароль", salt))
    c2 = CryptoLayer(CryptoLayer.derive_key("другой", salt))
    assert c1.hmac_hash("иванов иван") == c1.hmac_hash("иванов иван")
    assert c1.hmac_hash("иванов иван") != c2.hmac_hash("иванов иван")


def test_password_token_verify():
    salt = b"0123456789abcdef"
    good = CryptoLayer(CryptoLayer.derive_key("пароль", salt))
    bad = CryptoLayer(CryptoLayer.derive_key("неверно", salt))
    token = good.password_token()
    assert good.verify_token(token)
    assert not bad.verify_token(token)


def test_bad_key_length_rejected():
    with pytest.raises(CryptoError):
        CryptoLayer(b"korotkiy")
