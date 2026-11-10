"""Исключения слоя приложения."""

from src.infrastructure.mapping_store import WrongPasswordError  # переэкспорт

__all__ = ["WrongPasswordError"]


class AppError(Exception):
    """Базовое исключение слоя приложения."""


class ProjectExistsError(AppError):
    """Проект с таким именем уже существует."""


class InvalidProjectNameError(AppError):
    """Имя проекта пустое или содержит недопустимые символы."""


class ProjectNotFoundError(AppError):
    """Проект не найден."""


class WeakPasswordError(AppError):
    """Пароль короче 8 символов (F-7)."""


class ConfirmationRequired(AppError):
    """Опасная операция требует явного подтверждения (например, открытый экспорт словаря)."""


class WorkspaceLockedError(AppError):
    """Проект закрыт по таймауту — требуется ввести пароль заново."""
