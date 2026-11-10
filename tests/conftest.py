"""Общие фикстуры тестов."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.application.project_service import ProjectManager  # noqa: E402
from src.domain.models import PiiType, TableData  # noqa: E402

PASSWORD = "СекретныйПароль1"


@pytest.fixture
def projects_dir(tmp_path) -> Path:
    """Временная папка хранения проектов."""
    directory = tmp_path / "Проекты"
    directory.mkdir()
    return directory


@pytest.fixture
def manager(projects_dir) -> ProjectManager:
    """Менеджер проектов поверх временной папки."""
    return ProjectManager(projects_dir)


@pytest.fixture
def workspace(manager):
    """Открытый тестовый проект (закрывается после теста)."""
    ws = manager.create_project("ТестПроект", PASSWORD)
    yield ws
    try:
        ws.store.close()
    except Exception:
        pass


# --- Данные -----------------------------------------------------------------

NAMES = [
    "Иванов Иван Иванович", "Петрова Мария Сергеевна", "Сидоров Пётр",
    "Кузнецова Анна", "Иванов Иван", "  Петров  Пётр  ",
    "О'Нил София", "Эльф 🧝‍♀️ Тест", "Специальные: #@%&*()",
]

PHONES = [
    "+7 (916) 123-45-67", "89211234567", "+79219876543", "8 903 111 22 33",
    "+7(903)555-66-77", "89160001122", "+79991234567", "89261234567", "+79031234567",
]

EMAILS = [
    "ivanov@example.com", "petrova@mail.ru", "sidorov@yandex.ru", "kuznecova@gmail.com",
    "ivanov2@example.com", "a.b@c.ru", "sofia.oneil@example.org", "elf@test.dev", "spec+sym@example.com",
]

PASSPORTS = [
    "4512 345678", "4609 123456", "4018 654321", "4501 112233", "4615 998877",
    "4020 556677", "4505 334455", "4603 778899", "4011 223344",
]

BIRTH_DATES = [
    "15.03.1985", "01.12.1990", "22.07.1978", "09.11.2001", "30.06.1966",
    "14.02.1992", "25.09.1988", "03.05.1975", "18.10.1999",
]


def make_pii_table(n_rows: int = 9) -> TableData:
    """Таблица со всеми типами ПДн ( значения циклически повторяются)."""
    def col(values: list[str]) -> list[str]:
        return [values[i % len(values)] for i in range(n_rows)]

    return TableData(
        headers=["ФИО", "Телефон", "Email", "Паспорт", "Дата рождения", "Зарплата"],
        rows=[
            list(row)
            for row in zip(
                col(NAMES), col(PHONES), col(EMAILS), col(PASSPORTS), col(BIRTH_DATES),
                [str(50000 + i * 1000) for i in range(n_rows)],
            )
        ],
    )


PII_COLUMNS = {
    0: PiiType.FULL_NAME,
    1: PiiType.PHONE,
    2: PiiType.EMAIL,
    3: PiiType.DOCUMENT,
    4: PiiType.BIRTH_DATE,
}
