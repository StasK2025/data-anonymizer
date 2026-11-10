"""Исключения доменного слоя."""


class DomainError(Exception):
    """Базовое исключение доменного слоя."""


class CryptoError(DomainError):
    """Ошибка криптографических операций."""


class DecryptionError(CryptoError):
    """Расшифровка не удалась (неверный ключ или повреждённые данные)."""


class MappingError(DomainError):
    """Ошибка словаря соответствий (например, исчерпан диапазон кодов)."""
