from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from app.models.compensacao import Compensacao
from app.models.plantio_item import PlantioItem
from app.services.audit_service import serialize_record
from app.utils.app_paths import ensure_dir, resolve_data_path


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_label(label: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", str(label or "").strip()).strip("-._")
    return normalized or "snapshot"


@dataclass(frozen=True)
class SqliteSessionBackup:
    workbook_path: str
    label: str
    created_at: str
    backup_path: str
    metadata: dict[str, Any]
    records: tuple[Compensacao, ...]


class SqliteSessionBackupService:
    def __init__(self, *, root_dir: str | Path | None = None):
        self.root_dir = Path(root_dir) if root_dir else resolve_data_path("state", "session_backups")
        ensure_dir(self.root_dir)

    def create_backup(
        self,
        *,
        workbook_path: str,
        label: str,
        records: Sequence[Compensacao],
        metadata: dict[str, Any] | None = None,
    ) -> str:
        normalized_path = str(workbook_path or "").strip()
        if not normalized_path:
            return ""

        created_at = _utc_timestamp()
        target_dir = self.root_dir / hashlib.sha1(normalized_path.encode("utf-8")).hexdigest()[:12]
        ensure_dir(target_dir)
        filename = f"{created_at.replace(':', '-').replace('.', '_')}_{_safe_label(label)}.json"
        backup_path = target_dir / filename
        payload = {
            "workbook_path": normalized_path,
            "label": str(label or "").strip(),
            "created_at": created_at,
            "metadata": dict(metadata or {}),
            "records": [serialize_record(record) for record in records],
        }
        backup_path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        return str(backup_path)

    def load_backup(self, backup_path: str) -> SqliteSessionBackup:
        target = Path(str(backup_path or "").strip())
        payload = json.loads(target.read_text(encoding="utf-8"))
        workbook_path = str(payload.get("workbook_path") or "").strip()
        label = str(payload.get("label") or "").strip()
        created_at = str(payload.get("created_at") or "").strip()
        metadata = dict(payload.get("metadata") or {})
        records = tuple(self._deserialize_record(item) for item in list(payload.get("records") or []))
        return SqliteSessionBackup(
            workbook_path=workbook_path,
            label=label,
            created_at=created_at,
            backup_path=str(target),
            metadata=metadata,
            records=records,
        )

    @staticmethod
    def _deserialize_record(payload: dict[str, Any]) -> Compensacao:
        plantios = [
            PlantioItem(
                sequence=int(item.get("sequence", 1) or 1),
                endereco=str(item.get("endereco", "") or ""),
                qtd_mudas=str(item.get("qtd_mudas", "") or ""),
                latitude=str(item.get("latitude", "") or ""),
                longitude=str(item.get("longitude", "") or ""),
            )
            for item in list(payload.get("plantios") or [])
        ]
        return Compensacao(
            excel_row=int(payload.get("excel_row", 0) or 0),
            uid=str(payload.get("uid", "") or ""),
            oficio_processo=str(payload.get("oficio_processo", "") or ""),
            eletronico=str(payload.get("eletronico", "") or ""),
            caixa=str(payload.get("caixa", "") or ""),
            av_tec=str(payload.get("av_tec", "") or ""),
            compensacao=payload.get("compensacao"),
            endereco=str(payload.get("endereco", "") or ""),
            microbacia=str(payload.get("microbacia", "") or ""),
            compensado=str(payload.get("compensado", "") or ""),
            endereco_plantio=str(payload.get("endereco_plantio", "") or ""),
            latitude_plantio=str(payload.get("latitude_plantio", "") or ""),
            longitude_plantio=str(payload.get("longitude_plantio", "") or ""),
            latitude=str(payload.get("latitude", "") or ""),
            longitude=str(payload.get("longitude", "") or ""),
            plantios=plantios,
        )
