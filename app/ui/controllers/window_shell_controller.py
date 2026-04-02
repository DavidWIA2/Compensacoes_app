from __future__ import annotations

import os
from typing import List

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QIntValidator, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.application.use_cases.local_record_queries import LocalRecordQueriesUseCases
from app.config import APP_WINDOW_TITLE
from app.models.display_columns import DISPLAY_COLUMN_ATTRS, DISPLAY_COLUMN_LABELS
from app.services.records_service import (
    STANDARD_TIPO_OPTIONS,
    TIPO_NULO,
    display_tipo_value,
    tipo_is_eletronico,
)
from app.ui.components.themes import THEME_DARK, THEME_LIGHT, get_app_qss
from app.ui.components.widgets import ColumnsDialog


class WindowShellController:
    def __init__(self, window):
        self.window = window
        self.local_record_queries = LocalRecordQueriesUseCases(getattr(window, "persistence_service", None))

    def setup_ui(self):
        central = QWidget()
        self.window.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(5, 5, 5, 5)

        top = QHBoxLayout()
        self.window.btn_open = QPushButton("Abrir Excel")
        self.window.btn_reload = QPushButton("Recarregar")
        self.window.btn_open.setProperty("kind", "primary")
        self.window.btn_reload.setProperty("kind", "secondary")

        self.window.search = QLineEdit()
        self.window.search.setPlaceholderText("Buscar (of\u00edcio, av. tec., endere\u00e7o...)")
        self.window.search.setClearButtonEnabled(True)

        self.window.btn_theme = QPushButton("Tema")
        self.window.btn_theme.setProperty("kind", "secondary")
        self.window.btn_theme.setFixedWidth(int(70 * self.window.scale_factor))

        top.addWidget(self.window.btn_open)
        top.addWidget(self.window.btn_reload)
        top.addWidget(self.window.search, 1)
        top.addWidget(self.window.btn_theme)
        layout.addLayout(top)

        self.window.tabs = QTabWidget()
        self.window.data_tab = self.window._data_tab_cls(self.window)
        self.window.dash_tab = self.window._dashboard_tab_cls(self.window)
        self.window.operations_tab = self.window._operations_tab_cls(self.window)
        self.window.data_tab.search = self.window.search
        self.window.tabs.addTab(self.window.data_tab, "Dados & Cadastro")
        self.window.tabs.addTab(self.window.dash_tab, "Painel")
        self.window.tabs.addTab(self.window.operations_tab, "Opera\u00e7\u00f5es")
        layout.addWidget(self.window.tabs)

        self.window.progress_bar = QProgressBar()
        self.window.progress_bar.setMaximumWidth(200)
        self.window.progress_bar.setVisible(False)

        self.window.progress_cancel_button = QPushButton("Cancelar")
        self.window.progress_cancel_button.setProperty("kind", "secondary")
        self.window.progress_cancel_button.setVisible(False)
        self.window.progress_cancel_button.clicked.connect(self.window.cancel_active_operation)

        self.window.form_state_label = QLabel("Sem altera\u00e7\u00f5es")
        self.window.form_state_label.setObjectName("FormStateLabel")

        self.window.statusBar().addPermanentWidget(self.window.progress_bar)
        self.window.statusBar().addPermanentWidget(self.window.progress_cancel_button)
        self.window.statusBar().addPermanentWidget(self.window.form_state_label)

        self.window.session_file_label = QLabel("Planilha: nenhuma")
        self.window.session_file_label.setObjectName("StatusChip")
        self.window.session_file_label.setMinimumWidth(int(220 * self.window.scale_factor))
        self.window.session_file_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self.window.session_records_label = QLabel("Registros: 0")
        self.window.session_records_label.setObjectName("StatusChip")

        self.window.session_selection_label = QLabel("Modo: novo cadastro")
        self.window.session_selection_label.setObjectName("StatusChip")

        self.window.statusBar().addPermanentWidget(self.window.session_file_label)
        self.window.statusBar().addPermanentWidget(self.window.session_records_label)
        self.window.statusBar().addPermanentWidget(self.window.session_selection_label)
        self.window.statusBar().setSizeGripEnabled(False)
        self.window.statusBar().setStyleSheet("QStatusBar::item { border: none; }")
        self.update_filters_from_records()
        self.setup_dynamic_form_options_from_records()

    def current_file_label_text(self) -> str:
        path = str(getattr(self.window.excel, "path", "") or "").strip()
        if not path:
            return "Planilha: nenhuma"
        return f"Planilha: {os.path.basename(path) or path}"

    def current_records_label_text(self) -> str:
        total = len(self.window.records)
        filtered = len(self.window.filtered_records)
        if total <= 0:
            return "Registros: 0"
        if filtered == total:
            return f"Registros: {total}"
        return f"Registros: {filtered} de {total}"

    def current_selection_label_text(self) -> str:
        if self.window.selected is None:
            return "Modo: novo cadastro"

        summary = (self.window.selected.av_tec or "").strip()
        if not summary:
            summary = (self.window.selected.oficio_processo or "").strip()
        if not summary:
            row_number = max(int(getattr(self.window.selected, "excel_row", 0)) - 1, 0)
            summary = f"linha {row_number}" if row_number else "registro ativo"
        return f"Selecionado: {summary}"

    def refresh_window_chrome(self):
        path = str(getattr(self.window.excel, "path", "") or "").strip()
        title = APP_WINDOW_TITLE
        if path:
            title = f"{APP_WINDOW_TITLE}[*] - {os.path.basename(path) or path}"
            if self.window.records:
                title = f"{title} ({len(self.window.filtered_records)}/{len(self.window.records)})"
        self.window.setWindowTitle(title)

        self.window.session_file_label.setText(self.current_file_label_text())
        self.window.session_file_label.setToolTip(path or "Nenhuma planilha carregada.")

        self.window.session_records_label.setText(self.current_records_label_text())
        search_text = self.window.search.text().strip()
        if search_text:
            self.window.session_records_label.setToolTip(f"Busca atual: {search_text}")
        else:
            self.window.session_records_label.setToolTip("Resumo do conjunto filtrado na tela.")

        self.window.session_selection_label.setText(self.current_selection_label_text())
        if self.window.selected is None:
            self.window.session_selection_label.setToolTip("Formulario pronto para novo cadastro.")
        else:
            self.window.session_selection_label.setToolTip("Registro atualmente carregado no formulario.")

    def setup_menus(self):
        build_command = self.window.command_controller.build_handler
        menubar = self.window.menuBar()
        file_menu = menubar.addMenu("Arquivo")

        self.window.action_import = QAction("Importar Excel (Mesclar)", self.window)
        self.window.action_import.triggered.connect(build_command("import_excel_data"))
        file_menu.addAction(self.window.action_import)

        self.window.action_rollback = QAction("M\u00e1quina do Tempo (Restaurar Backup)", self.window)
        self.window.action_rollback.triggered.connect(build_command("show_rollback_dialog"))
        file_menu.addAction(self.window.action_rollback)

        self.window.action_operation_history = QAction("Hist\u00f3rico de Opera\u00e7\u00f5es", self.window)
        self.window.action_operation_history.triggered.connect(build_command("show_operation_history"))
        file_menu.addAction(self.window.action_operation_history)

        file_menu.addSeparator()

        self.window.menu_recent = file_menu.addMenu("Recentes")
        self.window._update_recent_files_menu()

        help_menu = menubar.addMenu("Ajuda")
        self.window.action_check_updates = QAction("Verificar Atualizacoes", self.window)
        self.window.action_check_updates.triggered.connect(build_command("check_for_updates"))
        help_menu.addAction(self.window.action_check_updates)
        help_menu.addSeparator()

        self.window.action_export_diagnostics = QAction("Exportar Diagn\u00f3stico", self.window)
        self.window.action_export_diagnostics.triggered.connect(build_command("export_diagnostics"))
        help_menu.addAction(self.window.action_export_diagnostics)

        self.window.action_open_logs = QAction("Abrir Pasta de Logs", self.window)
        self.window.action_open_logs.triggered.connect(build_command("open_logs_folder"))
        help_menu.addAction(self.window.action_open_logs)

        help_menu.addSeparator()

        self.window.action_about = QAction("Sobre", self.window)
        self.window.action_about.triggered.connect(build_command("show_about_dialog"))
        help_menu.addAction(self.window.action_about)

    def connect_signals(self):
        build_command = self.window.command_controller.build_handler

        self.window.btn_open.clicked.connect(build_command("open_excel"))
        self.window.btn_reload.clicked.connect(build_command("reload"))
        self.window.btn_theme.clicked.connect(build_command("toggle_theme"))

        self.window.search.textChanged.connect(self.window.schedule_apply_filter)
        self.window.tabs.currentChanged.connect(self.window._on_tab_changed)

        self.window.data_tab.filter_micro.selectionChanged.connect(self.window.schedule_apply_filter)
        self.window.data_tab.filter_eletronico.selectionChanged.connect(self.window.schedule_apply_filter)
        self.window.data_tab.filter_status.currentTextChanged.connect(self.window.schedule_apply_filter)
        self.window.data_tab.filter_year.currentTextChanged.connect(self.window.schedule_apply_filter)
        self.window.data_tab.btn_clear_filters.clicked.connect(build_command("clear_filters"))
        self.window.data_tab.btn_reset_sort.clicked.connect(build_command("reset_sorting"))
        self.window.data_tab.btn_columns.clicked.connect(build_command("open_columns_dialog"))
        self.window.data_tab.btn_table_full.clicked.connect(build_command("open_table_fullscreen"))
        self.window.data_tab.table.clicked.connect(self.window._on_table_clicked)

        self.window.data_tab.btn_clear.clicked.connect(build_command("clear_form"))
        self.window.data_tab.btn_add.clicked.connect(build_command("add_new"))
        self.window.data_tab.btn_save_edit.clicked.connect(build_command("save_edit"))
        self.window.data_tab.btn_delete.clicked.connect(build_command("delete_selected"))
        self.window.data_tab.btn_ficha_pdf.clicked.connect(build_command("export_ficha_pdf"))
        self.window.data_tab.btn_manage_plantios.clicked.connect(build_command("edit_plantios"))

        self.window.data_tab.btn_maps.clicked.connect(build_command("search_on_map"))
        self.window.data_tab.btn_maps_plantio.clicked.connect(build_command("search_on_map_plantio"))
        self.window.data_tab.btn_batch_geo.clicked.connect(build_command("run_batch_geocode"))
        self.window.data_tab.btn_map_full.clicked.connect(build_command("open_map_fullscreen"))
        self.window.data_tab.btn_street_view.clicked.connect(build_command("open_street_view"))
        self.window.data_tab.btn_add_layer.clicked.connect(build_command("load_custom_layer"))
        self.window.data_tab.chk_heatmap.stateChanged.connect(build_command("toggle_heatmap"))
        self.window.data_tab.combo_heatmap_type.currentTextChanged.connect(build_command("toggle_heatmap"))
        self.window.data_tab.web.loadFinished.connect(self.window._on_map_loaded)

        self.window.data_tab.in_oficio.textChanged.connect(self.window._validate_as_you_type)
        self.window.data_tab.in_oficio.textChanged.connect(self.window._on_form_field_changed)
        self.window.data_tab.in_caixa.textChanged.connect(self.window._on_form_field_changed)
        self.window.data_tab.in_avtec.textChanged.connect(self.window._validate_as_you_type)
        self.window.data_tab.in_avtec.textChanged.connect(self.window._on_form_field_changed)
        self.window.data_tab.in_comp.textChanged.connect(self.window._on_form_field_changed)
        self.window.data_tab.in_end.textChanged.connect(self.window._on_form_field_changed)
        self.window.data_tab.in_end_plantio.textChanged.connect(self.window._on_form_field_changed)
        self.window.data_tab.in_micro.currentTextChanged.connect(self.window._on_form_field_changed)

        self.window.data_tab.chk_compensado.toggled.connect(self.window.form_controller.on_compensado_toggled)
        self.window.data_tab.chk_sn.toggled.connect(self.window._on_chk_sn_toggled)
        self.window.data_tab.chk_arquivado.toggled.connect(self.window._on_chk_arquivado_toggled)
        self.window.data_tab.chk_arquivado.toggled.connect(self.window._on_form_field_changed)

        self.window.data_tab.btn_export_csv.clicked.connect(build_command("export_csv_clicked"))
        self.window.data_tab.btn_export_excel.clicked.connect(build_command("export_excel_clicked"))
        self.window.data_tab.btn_export_pdf.clicked.connect(build_command("export_pdf_clicked"))
        self.window.dash_tab.btn_export_pdf.clicked.connect(build_command("export_dashboard_pdf_clicked"))

        self.window.operations_tab.btn_refresh.clicked.connect(build_command("refresh_operations_overview"))
        self.window.operations_tab.btn_history.clicked.connect(build_command("show_operation_history"))
        self.window.operations_tab.btn_rollback.clicked.connect(build_command("show_rollback_dialog"))
        self.window.operations_tab.btn_open_backup.clicked.connect(build_command("open_selected_operation_backup"))

    def setup_shortcuts(self):
        build_command = self.window.command_controller.build_handler

        act_save = QAction(self.window)
        act_save.setShortcut("Ctrl+S")
        act_save.triggered.connect(build_command("save_edit"))
        self.window.addAction(act_save)

        act_undo = QAction(self.window)
        act_undo.setShortcut(QKeySequence.Undo)
        act_undo.triggered.connect(build_command("undo"))
        self.window.addAction(act_undo)

        act_redo = QAction(self.window)
        act_redo.setShortcut(QKeySequence.Redo)
        act_redo.triggered.connect(build_command("redo"))
        self.window.addAction(act_redo)

        act_new = QAction(self.window)
        act_new.setShortcut("Ctrl+N")
        act_new.triggered.connect(build_command("clear_form"))
        self.window.addAction(act_new)

        act_delete = QAction(self.window.data_tab.table)
        act_delete.setShortcut(QKeySequence(Qt.Key_Delete))
        act_delete.setShortcutContext(Qt.WidgetShortcut)
        act_delete.triggered.connect(build_command("delete_selected_from_table_shortcut"))
        self.window.data_tab.table.addAction(act_delete)

    def on_form_field_changed(self):
        self.refresh_tipo_controls()
        self.window.form_controller.remember_current_state()
        self.window._update_form_action_buttons()
        self.window._update_address_search_enabled()

    def validate_as_you_type(self):
        self.window.form_controller.validate_as_you_type()

    def is_form_dirty(self) -> bool:
        return self.window.form_controller.has_pending_changes()

    def update_address_search_enabled(self):
        self.window.map_controller.update_address_search_enabled()

    def on_chk_sn_toggled(self, checked):
        self.window.data_tab.in_oficio.blockSignals(True)
        try:
            if checked:
                self.window.data_tab.in_oficio.setText("S/N")
                self.window.data_tab.in_oficio.setEnabled(False)
            else:
                if self.window.data_tab.in_oficio.text().upper() == "S/N":
                    self.window.data_tab.in_oficio.clear()
                self.window.data_tab.in_oficio.setEnabled(True)
                self.window.data_tab.in_oficio.setFocus()
        finally:
            self.window.data_tab.in_oficio.blockSignals(False)
        self.window.form_controller.remember_current_state()
        self.window._update_form_action_buttons()

    def on_chk_arquivado_toggled(self, checked):
        self.window.data_tab.in_caixa.blockSignals(True)
        try:
            if checked:
                self.window.data_tab.in_caixa.setText("Arquivado")
            else:
                if self.window.data_tab.in_caixa.text().upper() == "ARQUIVADO":
                    self.window.data_tab.in_caixa.clear()
            self.refresh_tipo_controls(
                focus_if_enabled=not checked,
                clear_archived_text=not checked,
            )
        finally:
            self.window.data_tab.in_caixa.blockSignals(False)
        self.window.form_controller.remember_current_state()
        self.window._update_form_action_buttons()

    def finalize_startup_layout(self):
        self.window._startup_layout_pending = False
        self.window.data_tab.align_splitter_to_table_width()
        self.window.data_tab._sync_left_panel_heights()
        self.window.data_tab._update_form_group_height()
        self.window.data_tab._update_responsive_constraints()

    def apply_theme(self):
        theme = THEME_DARK if self.window.is_dark_mode else THEME_LIGHT
        qss = get_app_qss(theme, self.window.scale_factor)
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(qss)
        self.window.setStyleSheet(qss)
        self.window.data_tab.table_model.set_dark_mode(self.window.is_dark_mode)
        self.window.dash_tab.apply_theme(theme)
        self.window.operations_tab.apply_theme(theme)
        self.apply_theme_to_map()

    def apply_theme_to_map(self):
        mode = "dark" if self.window.is_dark_mode else "light"
        self.window._run_map_js(f"if(window.setTheme) window.setTheme('{mode}');", "theme")

    def update_filters_from_records(self):
        facets = self.local_record_queries.resolve_filter_facets(
            str(getattr(self.window.excel, "path", "") or ""),
            fallback_records=self.window.records,
        )
        self.window._local_filter_facets_status = self.local_record_queries.build_filter_facets_status(facets)
        self.window.data_tab.filter_micro.set_items(list(facets.microbacias))
        self.window.data_tab.filter_eletronico.set_items(list(STANDARD_TIPO_OPTIONS))
        self.window.data_tab.filter_year.blockSignals(True)
        self.window.data_tab.filter_year.clear()
        self.window.data_tab.filter_year.addItems(["Todos"] + list(facets.years))
        self.window.data_tab.filter_year.blockSignals(False)

    def setup_dynamic_form_options_from_records(self):
        facets = self.local_record_queries.resolve_filter_facets(
            str(getattr(self.window.excel, "path", "") or ""),
            fallback_records=self.window.records,
        )
        self.window._local_filter_facets_status = self.local_record_queries.build_filter_facets_status(facets)
        current_micro = self.window.data_tab.in_micro.currentText()
        self.window.data_tab.in_micro.blockSignals(True)
        self.window.data_tab.in_micro.clear()
        self.window.data_tab.in_micro.addItem("")
        for micro in facets.microbacias:
            self.window.data_tab.in_micro.addItem(micro)
        if current_micro:
            self.window.data_tab.in_micro.setCurrentText(current_micro)
        self.window.data_tab.in_micro.blockSignals(False)

        checked_button = self.window.data_tab.eletronico_group.checkedButton()
        current_eletronico = display_tipo_value(checked_button.text() if checked_button else "")

        while self.window.data_tab.eletronico_layout.count():
            item = self.window.data_tab.eletronico_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                self.window.data_tab.eletronico_group.removeButton(widget)
                widget.deleteLater()

        selected_button = None
        for option in STANDARD_TIPO_OPTIONS:
            button = QRadioButton(option)
            button.setMinimumHeight(24)
            button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            button.clicked.connect(self.window._on_form_field_changed)
            self.window.data_tab.eletronico_group.addButton(button)
            self.window.data_tab.eletronico_layout.addWidget(button)
            if option == current_eletronico:
                button.setChecked(True)
                selected_button = button

        if selected_button is None:
            for button in self.window.data_tab.eletronico_group.buttons():
                if button.text() == TIPO_NULO:
                    button.setChecked(True)
                    break

        self.window.data_tab.eletronico_layout.addStretch(1)
        self.refresh_tipo_controls()

    def refresh_tipo_controls(
        self,
        *,
        focus_if_enabled: bool = False,
        clear_archived_text: bool = False,
    ):
        checked_button = self.window.data_tab.eletronico_group.checkedButton()
        selected_tipo = display_tipo_value(checked_button.text() if checked_button else "")
        is_arquivado = self.window.data_tab.chk_arquivado.isChecked()
        caixa = self.window.data_tab.in_caixa
        caixa.setValidator(None if is_arquivado else QIntValidator(0, 999999))
        if is_arquivado:
            caixa.setText("Arquivado")
        elif clear_archived_text and caixa.text().strip().upper() == "ARQUIVADO":
            caixa.clear()

        is_editable = not is_arquivado and not tipo_is_eletronico(selected_tipo)
        caixa.setEnabled(is_editable)
        if is_editable and focus_if_enabled:
            caixa.setFocus()

    def open_columns_dialog(self):
        visible_map = {
            index: not self.window.data_tab.table.isColumnHidden(index)
            for index in range(self.window.data_tab.table_model.columnCount())
        }
        dialog = ColumnsDialog(self.window, list(DISPLAY_COLUMN_LABELS), visible_map)
        if not dialog.exec():
            return

        new_map = dialog.visible_map()
        if not any(new_map.values()):
            QMessageBox.warning(self.window, "Aviso", "Selecione pelo menos uma coluna para exibir.")
            return

        for index, is_visible in new_map.items():
            self.window.data_tab.table.setColumnHidden(index, not is_visible)

    def on_table_clicked(self, index):
        if self.window.selected is not None and self.window.form_controller.has_pending_changes():
            if not self.window.form_controller.confirm_discard_changes("trocar de registro"):
                return

        source_index = self.window.data_tab.proxy.mapToSource(index)
        if not source_index.isValid() or source_index.row() >= len(self.window.filtered_records):
            return

        self.window.selected = self._resolve_filtered_record_selection(source_index.row())
        self.window._fill_form(self.window.selected)
        self.window._update_form_action_buttons()
        self.window._update_address_search_enabled()

        lat = getattr(self.window.selected, "latitude", "")
        lon = getattr(self.window.selected, "longitude", "")
        if str(lat).strip() and str(lon).strip():
            self.window._set_map_marker(float(lat), float(lon))
            if self.window.selected.microbacia:
                self.window._highlight_microbacia(self.window.selected.microbacia)

    def delete_selected_from_table_shortcut(self):
        current_index = self.window.data_tab.table.currentIndex()
        if current_index.isValid():
            source_index = self.window.data_tab.proxy.mapToSource(current_index)
            if 0 <= source_index.row() < len(self.window.filtered_records):
                self.window.selected = self._resolve_filtered_record_selection(source_index.row())
        self.window.delete_selected()

    def _resolve_filtered_record_selection(self, row_index: int):
        fallback_record = self.window.filtered_records[row_index]
        selected_result = self.local_record_queries.resolve_selected_record(
            str(getattr(self.window.excel, "path", "") or ""),
            fallback_records=self.window.records,
            uid=str(getattr(fallback_record, "uid", "") or ""),
            excel_row=int(getattr(fallback_record, "excel_row", 0) or 0),
        )
        return selected_result.record or fallback_record

    def get_visible_column_attrs(self) -> List[str]:
        attrs = []
        for index, attr in enumerate(DISPLAY_COLUMN_ATTRS):
            if not self.window.data_tab.table.isColumnHidden(index):
                attrs.append(attr)
        return attrs
