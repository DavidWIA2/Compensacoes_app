from __future__ import annotations

from typing import Any, Callable


class WindowCommandController:
    def __init__(self, window):
        self.window = window
        self._command_names = {
            "open_excel",
            "reload",
            "toggle_theme",
            "clear_filters",
            "reset_sorting",
            "open_columns_dialog",
            "open_table_fullscreen",
            "clear_form",
            "add_new",
            "save_edit",
            "delete_selected",
            "undo",
            "redo",
            "export_ficha_pdf",
            "edit_plantios",
            "search_on_map",
            "search_on_map_plantio",
            "run_batch_geocode",
            "open_map_fullscreen",
            "open_street_view",
            "load_custom_layer",
            "toggle_heatmap",
            "export_csv_clicked",
            "export_excel_clicked",
            "export_pdf_clicked",
            "export_dashboard_pdf_clicked",
            "import_excel_data",
            "show_rollback_dialog",
            "show_operation_history",
            "refresh_operations_overview",
            "open_selected_operation_backup",
            "open_logs_folder",
            "export_diagnostics",
            "check_for_updates",
            "present_update_offer",
            "show_about_dialog",
            "delete_selected_from_table_shortcut",
        }

    def list_commands(self) -> tuple[str, ...]:
        return tuple(sorted(self._command_names))

    def execute(self, command_name: str, *args, **kwargs):
        if command_name not in self._command_names:
            raise KeyError(f"Comando desconhecido: {command_name}")
        return getattr(self, command_name)(*args, **kwargs)

    def build_handler(self, command_name: str, *args, **kwargs) -> Callable[..., Any]:
        def _handler(*_signal_args):
            return self.execute(command_name, *args, **kwargs)

        return _handler

    def open_excel(self):
        return self.window.data_controller.open_excel()

    def reload(self, confirm_discard: bool = True):
        return self.window.data_controller.reload(confirm_discard=confirm_discard)

    def toggle_theme(self):
        return self.window.settings_controller.toggle_theme()

    def clear_filters(self):
        return self.window.data_controller.clear_filters()

    def reset_sorting(self):
        return self.window.settings_controller.reset_sorting()

    def open_columns_dialog(self):
        return self.window.shell_controller.open_columns_dialog()

    def open_table_fullscreen(self):
        return self.window.map_controller.open_table_fullscreen()

    def clear_form(self, force: bool = False):
        return self.window.form_controller.clear_form(force=force)

    def add_new(self):
        return self.window.form_controller.add_new()

    def save_edit(self):
        return self.window.form_controller.save_edit()

    def delete_selected(self):
        return self.window.form_controller.delete_selected()

    def undo(self):
        return self.window.form_controller.undo()

    def redo(self):
        return self.window.form_controller.redo()

    def export_ficha_pdf(self):
        return self.window.export_controller.export_ficha_pdf()

    def edit_plantios(self):
        return self.window.form_controller.open_plantios_dialog()

    def search_on_map(self):
        return self.window.map_controller.search_on_map()

    def search_on_map_plantio(self):
        return self.window.map_controller.search_on_map_plantio()

    def run_batch_geocode(self):
        return self.window.map_controller.run_batch_geocode()

    def open_map_fullscreen(self):
        return self.window.map_controller.open_map_fullscreen()

    def open_street_view(self):
        return self.window.map_controller.open_street_view()

    def load_custom_layer(self):
        return self.window.map_controller.load_custom_layer()

    def toggle_heatmap(self):
        return self.window.map_controller.toggle_heatmap()

    def export_csv_clicked(self):
        return self.window.export_controller.export_csv_clicked()

    def export_excel_clicked(self):
        return self.window.export_controller.export_excel_clicked()

    def export_pdf_clicked(self):
        return self.window.export_controller.export_pdf_clicked()

    def export_dashboard_pdf_clicked(self):
        return self.window.export_controller.export_dashboard_pdf_clicked()

    def import_excel_data(self):
        return self.window.data_controller.import_excel_data()

    def show_rollback_dialog(self):
        return self.window.data_controller.show_rollback_dialog()

    def show_operation_history(self):
        return self.window.data_controller.show_operation_history()

    def refresh_operations_overview(self):
        return self.window.operations_controller.refresh_overview()

    def open_selected_operation_backup(self):
        return self.window.operations_controller.open_selected_backup()

    def open_logs_folder(self):
        return self.window.support_controller.open_logs_folder()

    def export_diagnostics(self):
        return self.window.support_controller.export_diagnostics()

    def check_for_updates(self):
        return self.window.support_controller.check_for_updates()

    def present_update_offer(self, *args, **kwargs):
        return self.window.support_controller.present_update_offer(*args, **kwargs)

    def show_about_dialog(self):
        return self.window.support_controller.show_about_dialog()

    def delete_selected_from_table_shortcut(self):
        return self.window.shell_controller.delete_selected_from_table_shortcut()
