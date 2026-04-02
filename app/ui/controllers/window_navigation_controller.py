from __future__ import annotations

from typing import Dict, Optional


class WindowNavigationController:
    def __init__(self, window):
        self.window = window

    def is_dashboard_tab_active(self) -> bool:
        return self.window.tabs.currentWidget() is self.window.dash_tab

    def is_operations_tab_active(self) -> bool:
        return self.window.tabs.currentWidget() is self.window.operations_tab

    def update_dashboard(self, metrics: Dict[str, object]):
        self.window._pending_dashboard_metrics = dict(metrics)
        if self.is_dashboard_tab_active():
            self._render_dashboard(metrics)
            self.window._dashboard_dirty = False
        else:
            self.window._dashboard_dirty = True

    def _render_dashboard(self, metrics: Optional[Dict[str, object]] = None):
        payload = metrics if metrics is not None else self.window._pending_dashboard_metrics
        if payload is None:
            return
        self.window.dash_tab.update_dashboard(
            payload,
            self.window.is_dark_mode,
            [record.microbacia for record in self.window.records],
            self.window._dashboard_record_overview,
            self.window._local_record_read_status,
        )

    def on_tab_changed(self, _index: int):
        if self.is_dashboard_tab_active() and self.window._dashboard_dirty:
            self._render_dashboard()
            if self.window._pending_dashboard_metrics is not None:
                self.window._dashboard_dirty = False

        if self.is_operations_tab_active():
            self.window.operations_controller.refresh_overview()
