from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from app.models.compensacao import Compensacao


@dataclass
class WindowSessionSnapshot:
    records: List[Compensacao]
    filtered_records: List[Compensacao]
    selected: Optional[Compensacao]
    form_plantios: List[object]
    last_marker_coords: Optional[Tuple[float, float]]
    recent_files: List[str]
    record_search_index: Dict[str, str]
    local_record_read_status: object | None
    local_session_source_status: object | None
    local_filter_facets_status: object | None
    local_mutation_sync_status: object | None
    filtered_metrics: Optional[Dict[str, object]]
    dashboard_dirty: bool
    pending_dashboard_metrics: Optional[Dict[str, object]]
    dashboard_record_overview: object | None


@dataclass
class WindowSessionState:
    records: List[Compensacao] = field(default_factory=list)
    filtered_records: List[Compensacao] = field(default_factory=list)
    selected: Optional[Compensacao] = None
    form_plantios: List[object] = field(default_factory=list)
    last_marker_coords: Optional[Tuple[float, float]] = None
    recent_files: List[str] = field(default_factory=list)
    record_search_index: Dict[str, str] = field(default_factory=dict)
    local_record_read_status: object | None = None
    local_session_source_status: object | None = None
    local_filter_facets_status: object | None = None
    local_mutation_sync_status: object | None = None
    filtered_metrics: Optional[Dict[str, object]] = None
    dashboard_dirty: bool = True
    pending_dashboard_metrics: Optional[Dict[str, object]] = None
    dashboard_record_overview: object | None = None


class WindowSessionController:
    def __init__(self, window):
        self.window = window
        self.state = WindowSessionState()

    def snapshot(self) -> WindowSessionSnapshot:
        pending_metrics = self.state.pending_dashboard_metrics
        return WindowSessionSnapshot(
            records=list(self.state.records),
            filtered_records=list(self.state.filtered_records),
            selected=self.state.selected,
            form_plantios=list(self.state.form_plantios),
            last_marker_coords=self.state.last_marker_coords,
            recent_files=list(self.state.recent_files),
            record_search_index=dict(self.state.record_search_index),
            local_record_read_status=self.state.local_record_read_status,
            local_session_source_status=self.state.local_session_source_status,
            local_filter_facets_status=self.state.local_filter_facets_status,
            local_mutation_sync_status=self.state.local_mutation_sync_status,
            filtered_metrics=dict(self.state.filtered_metrics) if self.state.filtered_metrics is not None else None,
            dashboard_dirty=bool(self.state.dashboard_dirty),
            pending_dashboard_metrics=dict(pending_metrics) if pending_metrics is not None else None,
            dashboard_record_overview=self.state.dashboard_record_overview,
        )

    def restore(self, snapshot: WindowSessionSnapshot) -> None:
        self.state.records = list(snapshot.records)
        self.state.filtered_records = list(snapshot.filtered_records)
        self.state.selected = snapshot.selected
        self.state.form_plantios = list(snapshot.form_plantios)
        self.state.last_marker_coords = snapshot.last_marker_coords
        self.state.recent_files = list(snapshot.recent_files)
        self.state.record_search_index = dict(snapshot.record_search_index)
        self.state.local_record_read_status = snapshot.local_record_read_status
        self.state.local_session_source_status = snapshot.local_session_source_status
        self.state.local_filter_facets_status = snapshot.local_filter_facets_status
        self.state.local_mutation_sync_status = snapshot.local_mutation_sync_status
        self.state.filtered_metrics = dict(snapshot.filtered_metrics) if snapshot.filtered_metrics is not None else None
        self.state.dashboard_dirty = bool(snapshot.dashboard_dirty)
        self.state.pending_dashboard_metrics = (
            dict(snapshot.pending_dashboard_metrics) if snapshot.pending_dashboard_metrics is not None else None
        )
        self.state.dashboard_record_overview = snapshot.dashboard_record_overview

    def clear_workbook_state(self) -> None:
        self.state.records = []
        self.state.filtered_records = []
        self.state.selected = None
        self.state.form_plantios = []
        self.state.last_marker_coords = None
        self.state.record_search_index = {}
        self.state.local_record_read_status = None
        self.state.local_session_source_status = None
        self.state.local_filter_facets_status = None
        self.state.local_mutation_sync_status = None
        self.state.filtered_metrics = None
        self.state.dashboard_dirty = True
        self.state.pending_dashboard_metrics = None
        self.state.dashboard_record_overview = None

    def clear_recent_files(self) -> None:
        self.state.recent_files = []
