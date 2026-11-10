"""Работа со словарем соответствий: просмотр, экспорт, импорт (F-5).

- Просмотр словаря — только после пароля (открытый проект); значения скрыты
  по умолчанию.
- Экспорт по умолчанию — зашифрованный; открытый CSV — только при явном
  подтверждении (диалог предупреждения в GUI).
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.application.errors import AppError, ConfirmationRequired
from src.application.project_service import ProjectWorkspace
from src.domain.errors import DecryptionError
from src.domain.models import PiiType
from src.infrastructure.mapping_store import META_VERSION

EXPORT_FORMAT = "local-anonymizer-mapping"
EXPORT_VERSION = 1


@dataclass
class MappingEntryView:
    """Строка словаря для отображения."""

    code: str
    column_type: str        # русское название типа ПДн
    value: Optional[str]    # расшифрованное значение (None, если скрыто)
    masked: str             # маскированное значение
    created_at: str


def mask_value(value: str) -> str:
    """Маскировка значения: первая символ + «***» (ПДн не раскрывается)."""
    if not value:
        return ""
    return value[0] + "***"


class MappingService:
    """Сценарии просмотра/экспорта/импорта словаря."""

    def entries(self, workspace: ProjectWorkspace, reveal: bool = False) -> list[MappingEntryView]:
        """Список записей словаря; значения раскрываются только явно (F-5)."""
        workspace.require_open()
        out: list[MappingEntryView] = []
        for row in workspace.store.all_mappings():
            value: Optional[str] = None
            masked = "••••"
            if reveal:
                value = workspace.engine.decrypt_raw(row.value_enc)
                masked = str(value)
            else:
                # Маска по длине, без раскрытия первой буквы — для скрытого режима
                try:
                    plain = workspace.engine.decrypt_raw(row.value_enc)
                    masked = mask_value(str(plain))
                except DecryptionError:
                    masked = "????"
            type_title = _type_title(row.column_type)
            out.append(MappingEntryView(row.code, type_title, value, masked, row.created_at))
        return out

    def export_encrypted(self, workspace: ProjectWorkspace, path: str | Path) -> int:
        """Экспорт словаря в зашифрованном виде (по умолчанию, F-5)."""
        workspace.require_open()
        entries = [
            {
                "index": row.code,
                "value_enc_hex": row.value_enc.hex(),
                "value_hash_hex": row.value_hash.hex(),
                "column_type": row.column_type,
                "created_at": row.created_at,
            }
            for row in workspace.store.all_mappings()
        ]
        payload = {
            "format": EXPORT_FORMAT,
            "version": EXPORT_VERSION,
            "project": workspace.name,
            "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "kdf": workspace.meta.get("kdf", {}),
            "meta_version": META_VERSION,
            "entries": entries,
        }
        Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        workspace.journal.log("экспорт словаря (зашифрованный)", filename=Path(path).name,
                              note=f"записей={len(entries)}")
        return len(entries)

    def export_open_csv(self, workspace: ProjectWorkspace, path: str | Path, confirm: bool = False) -> int:
        """Экспорт словаря ОТКРЫТЫМ CSV — только после явного подтверждения (F-5, Г-2)."""
        workspace.require_open()
        if not confirm:
            raise ConfirmationRequired(
                "открытый экспорт словаря содержит персональные данные в открытом виде; "
                "требуется явное подтверждение пользователя"
            )
        rows = workspace.store.all_mappings()
        with open(path, "w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.writer(fh, delimiter=";", lineterminator="\r\n")
            writer.writerow(["код", "тип_пдн", "значение", "создан"])
            for row in rows:
                value = workspace.engine.decrypt_raw(row.value_enc)
                writer.writerow([row.code, _type_title(row.column_type), value, row.created_at])
        workspace.journal.log("экспорт словаря (ОТКРЫТЫЙ CSV)", filename=Path(path).name,
                              note=f"записей={len(rows)}")
        return len(rows)

    def import_encrypted(self, workspace: ProjectWorkspace, path: str | Path) -> int:
        """Импорт словаря из зашифрованного экспорта того же проекта."""
        workspace.require_open()
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AppError(f"не удалось прочитать файл словаря: {exc}") from exc
        if payload.get("format") != EXPORT_FORMAT:
            raise AppError("файл не является экспортом словаря этого приложения")
        export_salt = payload.get("kdf", {}).get("salt_b64")
        own_salt = workspace.meta.get("kdf", {}).get("salt_b64")
        if export_salt != own_salt:
            raise AppError("словарь принадлежит другому проекту (другая соль KDF) — импорт невозможен")

        imported = 0
        for entry in payload.get("entries", []):
            code = entry["index"]
            if workspace.store.find_by_code(code) is not None:
                continue  # уже есть — не дублируем
            workspace.store.insert_mapping(
                code,
                bytes.fromhex(entry["value_enc_hex"]),
                bytes.fromhex(entry["value_hash_hex"]),
                entry["column_type"],
            )
            imported += 1
        workspace.store.flush()
        workspace.journal.log("импорт словаря (зашифрованный)", filename=Path(path).name,
                              note=f"добавлено={imported}")
        return imported

    def import_open_csv(self, workspace: ProjectWorkspace, path: str | Path, confirm: bool = False) -> int:
        """Импорт словаря из открытого CSV (код;тип;значение) — содержит ПДн, нужен confirm."""
        workspace.require_open()
        if not confirm:
            raise ConfirmationRequired("файл содержит персональные данные в открытом виде — требуется подтверждение")
        crypto = workspace.crypto
        count = 0
        try:
            with open(path, "r", encoding="utf-8-sig", newline="") as fh:
                reader = csv.reader(fh, delimiter=";")
                header = next(reader, None)
                if header is None:
                    return 0
                for rec in reader:
                    if len(rec) < 3:
                        continue
                    code, type_raw, value = rec[0].strip(), rec[1].strip(), rec[2]
                    if not code or value == "":
                        continue
                    if workspace.store.find_by_code(code) is not None:
                        continue
                    normalized = value.strip().lower()
                    value_hash = crypto.hmac_hash(normalized)
                    if workspace.store.find_by_hash(value_hash) is not None:
                        continue
                    workspace.store.insert_mapping(code, crypto.encrypt(value), value_hash,
                                                   _type_from_title(type_raw))
                    count += 1
        except OSError as exc:
            raise AppError(f"не удалось прочитать CSV: {exc}") from exc
        workspace.store.flush()
        workspace.journal.log("импорт словаря (открытый CSV)", filename=Path(path).name,
                              note=f"добавлено={count}")
        return count


def _type_title(type_value: str) -> str:
    """Русское название типа по значению PiiType.value (с запасом на неизвестное)."""
    for pii in PiiType:
        if pii.value == type_value:
            return pii.title
    return type_value


def _type_from_title(title: str) -> str:
    """Значение PiiType.value по русскому названию (или свободный текст)."""
    title = (title or "").strip()
    for pii in PiiType:
        if pii.title.lower() == title.lower() or pii.value == title:
            return pii.value
    return PiiType.FREE_TEXT.value
