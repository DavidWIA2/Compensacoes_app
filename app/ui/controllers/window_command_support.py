from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class WindowCommandBinding:
    name: str
    controller_attr: str
    method_name: str

    def resolve(self, window: Any) -> Callable[..., Any]:
        controller = getattr(window, self.controller_attr)
        return getattr(controller, self.method_name)


def build_window_command_bindings() -> tuple[WindowCommandBinding, ...]:
    return (
        WindowCommandBinding("new_session", "data_controller", "new_session"),
        WindowCommandBinding("open_session", "data_controller", "open_session"),
        WindowCommandBinding("open_session_source", "data_controller", "open_session"),
        WindowCommandBinding("reload", "data_controller", "reload"),
        WindowCommandBinding("sign_out", "shell_controller", "sign_out"),
        WindowCommandBinding("toggle_theme", "settings_controller", "toggle_theme"),
        WindowCommandBinding("clear_filters", "data_controller", "clear_filters"),
        WindowCommandBinding("reset_sorting", "settings_controller", "reset_sorting"),
        WindowCommandBinding("open_columns_dialog", "shell_controller", "open_columns_dialog"),
        WindowCommandBinding("open_table_fullscreen", "map_controller", "open_table_fullscreen"),
        WindowCommandBinding("clear_form", "form_controller", "clear_form"),
        WindowCommandBinding("add_new", "form_controller", "add_new"),
        WindowCommandBinding("save_edit", "form_controller", "save_edit"),
        WindowCommandBinding("delete_selected", "form_controller", "delete_selected"),
        WindowCommandBinding("undo", "form_controller", "undo"),
        WindowCommandBinding("redo", "form_controller", "redo"),
        WindowCommandBinding("export_ficha_pdf", "export_controller", "export_ficha_pdf"),
        WindowCommandBinding("edit_plantios", "form_controller", "open_plantios_dialog"),
        WindowCommandBinding("search_on_map", "map_controller", "search_on_map"),
        WindowCommandBinding("search_on_map_plantio", "map_controller", "search_on_map_plantio"),
        WindowCommandBinding("run_batch_geocode", "map_controller", "run_batch_geocode"),
        WindowCommandBinding("open_map_fullscreen", "map_controller", "open_map_fullscreen"),
        WindowCommandBinding("open_street_view", "map_controller", "open_street_view"),
        WindowCommandBinding("load_custom_layer", "map_controller", "load_custom_layer"),
        WindowCommandBinding("toggle_heatmap", "map_controller", "toggle_heatmap"),
        WindowCommandBinding("export_csv_clicked", "export_controller", "export_csv_clicked"),
        WindowCommandBinding("export_spreadsheet_clicked", "export_controller", "export_spreadsheet_clicked"),
        WindowCommandBinding("export_pdf_clicked", "export_controller", "export_pdf_clicked"),
        WindowCommandBinding("export_dashboard_pdf_clicked", "export_controller", "export_dashboard_pdf_clicked"),
        WindowCommandBinding("show_rollback_dialog", "data_controller", "show_rollback_dialog"),
        WindowCommandBinding("show_operation_history", "data_controller", "show_operation_history"),
        WindowCommandBinding("refresh_operations_overview", "operations_controller", "refresh_overview"),
        WindowCommandBinding("refresh_production_snapshot", "operations_controller", "refresh_production_snapshot"),
        WindowCommandBinding("open_selected_operation_backup", "operations_controller", "open_selected_backup"),
        WindowCommandBinding("open_logs_folder", "support_controller", "open_logs_folder"),
        WindowCommandBinding("export_diagnostics", "support_controller", "export_diagnostics"),
        WindowCommandBinding("check_for_updates", "support_controller", "check_for_updates"),
        WindowCommandBinding("present_update_offer", "support_controller", "present_update_offer"),
        WindowCommandBinding("show_about_dialog", "support_controller", "show_about_dialog"),
        WindowCommandBinding(
            "delete_selected_from_table_shortcut",
            "shell_controller",
            "delete_selected_from_table_shortcut",
        ),
    )


def build_window_command_binding_map() -> dict[str, WindowCommandBinding]:
    return {binding.name: binding for binding in build_window_command_bindings()}
