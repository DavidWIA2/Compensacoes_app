from __future__ import annotations

import os
from typing import Callable, Optional


class SessionWorkbookRuntime:
    """Lazy workbook adapter that keeps session state without materializing Excel eagerly."""

    def __init__(self, *, loader_factory: Callable[[], object]):
        self._loader_factory = loader_factory
        self._service: Optional[object] = None
        self._path = ""
        self._wb = None
        self._ws = None
        self._plantio_ws = None
        self._col_map: dict[str, int] = {}
        self._plantio_col_map: dict[str, int] = {}
        self._uid_to_row: dict[str, int] = {}
        self._last_backup_time = 0
        self._merged_cells_warning = False
        self._loaded_source_mtime_ns = 0
        self._loaded_source_size = 0

    def create_loader(self):
        return SessionWorkbookRuntime(loader_factory=self._loader_factory)

    def has_materialized_workbook(self) -> bool:
        return self._service is not None

    def has_materialized_session(self) -> bool:
        return self.has_materialized_workbook()

    def _sync_shadow_from_service(self) -> None:
        service = self._service
        if service is None:
            return
        self._path = str(getattr(service, "path", "") or "")
        self._wb = getattr(service, "wb", None)
        self._ws = getattr(service, "ws", None)
        self._plantio_ws = getattr(service, "plantio_ws", None)
        self._col_map = dict(getattr(service, "col_map", {}) or {})
        self._plantio_col_map = dict(getattr(service, "plantio_col_map", {}) or {})
        self._uid_to_row = dict(getattr(service, "uid_to_row", {}) or {})
        self._last_backup_time = getattr(service, "last_backup_time", 0)
        self._merged_cells_warning = getattr(service, "merged_cells_warning", False)
        self._loaded_source_mtime_ns = int(getattr(service, "loaded_source_mtime_ns", 0) or 0)
        self._loaded_source_size = int(getattr(service, "loaded_source_size", 0) or 0)

    def _apply_shadow_to_service(self, service) -> None:
        service.path = self._path
        service.wb = self._wb
        service.ws = self._ws
        service.plantio_ws = self._plantio_ws
        service.col_map = dict(self._col_map)
        service.plantio_col_map = dict(self._plantio_col_map)
        service.uid_to_row = dict(self._uid_to_row)
        service.last_backup_time = self._last_backup_time
        service.merged_cells_warning = self._merged_cells_warning
        if hasattr(service, "loaded_source_mtime_ns"):
            service.loaded_source_mtime_ns = self._loaded_source_mtime_ns
        if hasattr(service, "loaded_source_size"):
            service.loaded_source_size = self._loaded_source_size

    def _get_service(self):
        if self._service is None:
            service = self._loader_factory()
            self._apply_shadow_to_service(service)
            self._service = service
        return self._service

    def _ensure_loaded_service(self):
        service = self._get_service()
        current_path = str(getattr(service, "path", "") or "").strip() or self._path
        if current_path and getattr(service, "ws", None) is None and os.path.exists(current_path):
            service.load(current_path)
        self._sync_shadow_from_service()
        return service

    @property
    def path(self) -> str:
        self._sync_shadow_from_service()
        return self._path

    @path.setter
    def path(self, value: str) -> None:
        self._path = str(value or "")
        if self._service is not None:
            self._service.path = self._path

    @property
    def session_path(self) -> str:
        return self.path

    @session_path.setter
    def session_path(self, value: str) -> None:
        self.path = value

    @property
    def wb(self):
        self._sync_shadow_from_service()
        return self._wb

    @wb.setter
    def wb(self, value) -> None:
        self._wb = value
        if self._service is not None:
            self._service.wb = value

    @property
    def ws(self):
        self._sync_shadow_from_service()
        return self._ws

    @ws.setter
    def ws(self, value) -> None:
        self._ws = value
        if self._service is not None:
            self._service.ws = value

    @property
    def plantio_ws(self):
        self._sync_shadow_from_service()
        return self._plantio_ws

    @plantio_ws.setter
    def plantio_ws(self, value) -> None:
        self._plantio_ws = value
        if self._service is not None:
            self._service.plantio_ws = value

    @property
    def col_map(self) -> dict[str, int]:
        self._sync_shadow_from_service()
        return dict(self._col_map)

    @col_map.setter
    def col_map(self, value: dict[str, int]) -> None:
        self._col_map = dict(value or {})
        if self._service is not None:
            self._service.col_map = dict(self._col_map)

    @property
    def plantio_col_map(self) -> dict[str, int]:
        self._sync_shadow_from_service()
        return dict(self._plantio_col_map)

    @plantio_col_map.setter
    def plantio_col_map(self, value: dict[str, int]) -> None:
        self._plantio_col_map = dict(value or {})
        if self._service is not None:
            self._service.plantio_col_map = dict(self._plantio_col_map)

    @property
    def uid_to_row(self) -> dict[str, int]:
        self._sync_shadow_from_service()
        return dict(self._uid_to_row)

    @uid_to_row.setter
    def uid_to_row(self, value: dict[str, int]) -> None:
        self._uid_to_row = dict(value or {})
        if self._service is not None:
            self._service.uid_to_row = dict(self._uid_to_row)

    @property
    def last_backup_time(self):
        self._sync_shadow_from_service()
        return self._last_backup_time

    @last_backup_time.setter
    def last_backup_time(self, value) -> None:
        self._last_backup_time = value
        if self._service is not None:
            self._service.last_backup_time = value

    @property
    def merged_cells_warning(self):
        self._sync_shadow_from_service()
        return self._merged_cells_warning

    @merged_cells_warning.setter
    def merged_cells_warning(self, value) -> None:
        self._merged_cells_warning = value
        if self._service is not None:
            self._service.merged_cells_warning = value

    @property
    def loaded_source_mtime_ns(self) -> int:
        self._sync_shadow_from_service()
        return self._loaded_source_mtime_ns

    @loaded_source_mtime_ns.setter
    def loaded_source_mtime_ns(self, value: int) -> None:
        self._loaded_source_mtime_ns = int(value or 0)
        if self._service is not None and hasattr(self._service, "loaded_source_mtime_ns"):
            self._service.loaded_source_mtime_ns = self._loaded_source_mtime_ns

    @property
    def loaded_source_size(self) -> int:
        self._sync_shadow_from_service()
        return self._loaded_source_size

    @loaded_source_size.setter
    def loaded_source_size(self, value: int) -> None:
        self._loaded_source_size = int(value or 0)
        if self._service is not None and hasattr(self._service, "loaded_source_size"):
            self._service.loaded_source_size = self._loaded_source_size

    def load(self, path: str):
        service = self._get_service()
        result = service.load(path)
        self._sync_shadow_from_service()
        return result

    def ensure_workbook_is_current(self) -> None:
        if not self.path:
            return
        service = self._ensure_loaded_service()
        ensure_current = getattr(service, "ensure_workbook_is_current", None)
        if callable(ensure_current):
            ensure_current()
            self._sync_shadow_from_service()

    def ensure_session_is_current(self) -> None:
        self.ensure_workbook_is_current()

    def create_operation_backup(self, label: str):
        if not self.path:
            return ""
        service = self._ensure_loaded_service()
        backup = service.create_operation_backup(label)
        self._sync_shadow_from_service()
        return backup

    def create_session_backup(self, label: str):
        return self.create_operation_backup(label)

    def save_edit(self, record) -> None:
        service = self._ensure_loaded_service()
        service.save_edit(record)
        self._sync_shadow_from_service()

    def save_batch_edits(self, records) -> int:
        service = self._ensure_loaded_service()
        result = service.save_batch_edits(records)
        self._sync_shadow_from_service()
        return result

    def delete_record_shift_up(self, row_idx: int, uid: str = "") -> None:
        service = self._ensure_loaded_service()
        service.delete_record_shift_up(row_idx, uid)
        self._sync_shadow_from_service()

    def import_records_atomic(self, records, *, progress_callback=None) -> int:
        service = self._ensure_loaded_service()
        result = service.import_records_atomic(records, progress_callback=progress_callback)
        self._sync_shadow_from_service()
        return result

    def __getattr__(self, name: str):
        service = self._get_service()
        return getattr(service, name)
