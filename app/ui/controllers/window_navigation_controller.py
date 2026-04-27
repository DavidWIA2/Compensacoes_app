from __future__ import annotations

from typing import Dict, Optional

from app.ui.controllers.window_layout_support import apply_window_responsive_layout
from app.ui.tabs.dashboard_tab_support import build_dashboard_micro_palette_keys


class WindowNavigationController:
    def __init__(self, window):
        self.window = window

    def _refresh_official_cache_if_needed(self) -> bool:
        data_controller = getattr(self.window, "data_controller", None)
        refresh = getattr(data_controller, "refresh_production_snapshot_if_stale", None)
        if not callable(refresh):
            return False
        try:
            return bool(refresh(force=False))
        except Exception:
            return False

    def is_dashboard_tab_active(self) -> bool:
        return self.window.tabs.currentWidget() is self.window.dash_tab

    def is_operations_tab_active(self) -> bool:
        return self.window.tabs.currentWidget() is self.window.operations_tab

    def is_tcra_tab_active(self) -> bool:
        return self.window.tabs.currentWidget() is getattr(self.window, "tcra_tab", None)

    def is_admin_tab_active(self) -> bool:
        return self.window.tabs.currentWidget() is getattr(self.window, "admin_users_tab", None)

    def update_operations_overview(self, *, force: bool = False) -> bool:
        self.window._operations_dirty = True
        if force or self.is_operations_tab_active():
            self.window.operations_controller.refresh_overview()
            self.window._operations_dirty = False
            return True
        return False

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
        shell_controller = getattr(self.window, "shell_controller", None)
        resolve_record_overview = getattr(shell_controller, "resolved_dashboard_record_overview", None)
        record_overview = (
            resolve_record_overview()
            if callable(resolve_record_overview)
            else self.window._dashboard_record_overview
        )
        self.window.dash_tab.update_dashboard(
            payload,
            self.window.is_dark_mode,
            build_dashboard_micro_palette_keys(payload, record_overview),
            record_overview,
            getattr(self.window, "_record_integrity_report", None),
            self.window._local_record_read_status,
        )
        if hasattr(self.window.dash_tab, "update_tcra_overview") and hasattr(self.window, "tcra_tab"):
            tcra_overview, tcra_agenda = self.window.tcra_tab.build_dashboard_payload()
            self.window.dash_tab.update_tcra_overview(tcra_overview, tcra_agenda)

    def on_tab_changed(self, _index: int):
        shell_controller = getattr(self.window, "shell_controller", None)
        sync_global_search_context = getattr(shell_controller, "sync_global_search_context", None)
        if callable(sync_global_search_context):
            sync_global_search_context()
        apply_window_responsive_layout(
            self.window,
            include_active_tab=False,
            finalize_active_tab=False,
        )

        refreshed = False
        if self.is_dashboard_tab_active() or self.is_operations_tab_active() or self.is_tcra_tab_active():
            refreshed = self._refresh_official_cache_if_needed()

        if self.is_dashboard_tab_active() and self.window._dashboard_dirty and not refreshed:
            self._render_dashboard()
            if self.window._pending_dashboard_metrics is not None:
                self.window._dashboard_dirty = False

        if self.is_operations_tab_active():
            if refreshed:
                self.window._operations_dirty = True
            elif getattr(self.window, "_operations_dirty", True):
                self.window.operations_controller.refresh_overview()
                self.window._operations_dirty = False

        if self.is_tcra_tab_active():
            self.window.tcra_tab.handle_tab_activated(schedule_fit=False)

        if self.is_admin_tab_active() and getattr(self.window, "admin_users_tab", None) is not None:
            self.window.admin_users_tab.handle_tab_activated()

        apply_window_responsive_layout(
            self.window,
            include_active_tab=True,
            finalize_active_tab=True,
        )
        refresh_window_chrome = getattr(shell_controller, "refresh_window_chrome", None)
        if callable(refresh_window_chrome):
            refresh_window_chrome()
