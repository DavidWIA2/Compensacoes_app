import os
import sys
import json
import tempfile
import gc
import time
from dataclasses import replace
from typing import List, Optional, Tuple, Dict

from PySide6.QtCore import Qt, QSettings, QTimer, QUrl, Slot
from PySide6.QtGui import QIcon, QAction, QKeySequence, QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QPushButton, QLineEdit, QTabWidget, QMessageBox, QFileDialog, QProgressBar, QLabel,
    QRadioButton, QSizePolicy, QMenu, QInputDialog
)

# --- Imports do Projeto ---
from app.config import APP_WINDOW_TITLE, APP_SETTINGS_NAME, APP_SETTINGS_ORG
from app.models.compensacao import Compensacao
from app.models.display_columns import DISPLAY_COLUMN_ATTRS, DISPLAY_COLUMN_LABELS
from app.services.excel_service import ExcelService
from app.services.geocode_service import geocode_address_arcgis
from app.services.geocode_update_service import apply_geocode_to_record, build_cached_microbacia_finder
from app.services.geocode_update_service import find_record_by_excel_row
from app.services.app_settings import AppSettings
from app.services.validation import validate_compensacao
from app.services.report_service import (
    export_csv, export_pdf, export_dashboard_pdf, export_individual_pdf,
    export_excel_two_sheets
)
from app.services.coordinates import build_heatmap_point
from app.services.gis_service import GisService
from app.services.records_service import (
    compute_metrics, filter_records, extract_year, safe_upper, unique_non_empty
)

# --- Componentes Modularizados ---
from app.ui.controllers.data_controller import DataController
from app.ui.controllers.export_controller import ExportController
from app.ui.controllers.form_controller import FormController
from app.ui.controllers.map_controller import MapController
from app.ui.controllers.settings_controller import SettingsController
from app.ui.controllers.support_controller import SupportController
from app.ui.components.ui_utils import resource_path, _setup_i18n, msg_confirm, _ajustar_ambiente_pyinstaller
from app.ui.components.widgets import ColumnsDialog, MapBridge
from app.ui.components.workers import GeocodeWorker, UpdaterWorker
from app.ui.components.themes import THEME_LIGHT, THEME_DARK, get_app_qss
from app.ui.components.dialogs import MapFullScreenDialog, TableFullScreenDialog
from app.ui.tabs.data_tab import DataTab
from app.ui.tabs.dashboard_tab import DashboardTab
from app.utils.logger import logger

_ajustar_ambiente_pyinstaller()

MICROB_NAME_FIELD = "Nome_Do_Arquivo"
MICROB_DIR = resource_path("data", "microbacias")

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_WINDOW_TITLE)
        self.MICROB_NAME_FIELD = MICROB_NAME_FIELD
        self.MICROB_DIR = MICROB_DIR
        
        # Cálculo de Escala Proporcional baseada na resolução
        screen = QApplication.primaryScreen().geometry()
        self.scale_factor = min(screen.width() / 1920, screen.height() / 1080)
        self.scale_factor = max(0.7, self.scale_factor) # Piso reduzido para 0.7
        
        font = self.font()
        font.setPointSize(int(10 * self.scale_factor))
        QApplication.instance().setFont(font)

        icon_path = resource_path("assets", "app.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        
        # Estado
        self.excel = ExcelService()
        self.records: List[Compensacao] = []
        self.filtered_records: List[Compensacao] = []
        self.selected: Optional[Compensacao] = None
        self.is_dark_mode = False
        self.settings = AppSettings(QSettings(APP_SETTINGS_ORG, APP_SETTINGS_NAME))
        self.gis: Optional[GisService] = None
        self.last_marker_coords: Optional[Tuple[float, float]] = None
        self.geo_worker = None
        self.recent_files: List[str] = []
        self._record_search_index: Dict[str, str] = {}
        self._startup_window_state_applied = False
        self._startup_layout_pending = False
        self._dashboard_dirty = True
        self._pending_dashboard_metrics: Optional[Dict[str, object]] = None
        self._skip_close_discard_confirmation = False
        self._startup_window_timer = QTimer(self)
        self._startup_window_timer.setSingleShot(True)
        self._startup_window_timer.timeout.connect(self._apply_startup_window_state)
        self._initial_map_sync_timer = QTimer(self)
        self._initial_map_sync_timer.setSingleShot(True)
        self._initial_map_sync_timer.timeout.connect(self._initial_map_sync)

        self._setup_ui()
        self.settings_controller = SettingsController(self)
        self.export_controller = ExportController(self)
        self.form_controller = FormController(self)
        self.data_controller = DataController(self)
        self.map_controller = MapController(self)
        self.support_controller = SupportController(self)
        self._bind_controller_methods()
        self._startup_window_timer.timeout.disconnect()
        self._startup_window_timer.timeout.connect(self._apply_startup_window_state)
        self._initial_map_sync_timer.timeout.disconnect()
        self._initial_map_sync_timer.timeout.connect(self._initial_map_sync)
        self.data_tab.bridge._on_clicked = self._on_map_click
        self.data_tab.bridge._on_layer_changed = self.save_map_layer_preference
        self._setup_menus()
        self._load_settings()
        self._connect_signals()
        self._setup_shortcuts()
        self.form_controller.setup_form_state_ui()
        self._startup_window_timer.start(0)
        
        # Inicialização
        _setup_i18n()
        self._load_last_excel()
        self._apply_theme()
        
        # Estado Inicial
        self._update_form_action_buttons()
        self._update_address_search_enabled()
        self._refresh_window_chrome()
        self.setWindowModified(False)
        self.statusBar().showMessage("Pronto")
        
        # Iniciar verificação de atualizações em segundo plano
        self._updater = UpdaterWorker()
        if hasattr(self._updater, "update_ready"):
            self._updater.update_ready.connect(self.present_update_offer)
        elif hasattr(self._updater, "update_available"):
            self._updater.update_available.connect(self._prompt_update)
        self._updater.start()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._startup_layout_pending and not self.isMinimized():
            self._startup_layout_pending = False
            self._finalize_startup_layout()

    def _bind_controller_methods(self):
        self.schedule_apply_filter = self.data_controller.schedule_apply_filter
        self._update_recent_files_menu = self.settings_controller.update_recent_files_menu
        self._snapshot_excel_service_state = self.data_controller.snapshot_excel_service_state
        self._restore_excel_service_state = self.data_controller.restore_excel_service_state
        self._snapshot_filter_state = self.data_controller.snapshot_filter_state
        self._restore_filter_state = self.data_controller.restore_filter_state
        self._clear_loaded_data_state = self.data_controller.clear_loaded_data_state
        self._restore_previous_state = self.data_controller.restore_previous_state
        self._metrics_to_kpi_rows = self.export_controller.metrics_to_kpi_rows
        self._build_filter_summary = self.export_controller.build_filter_summary
        self.show_rollback_dialog = self.data_controller.show_rollback_dialog
        self.import_excel_data = self.data_controller.import_excel_data
        self._update_form_action_buttons = self.form_controller.update_form_action_buttons
        self._on_map_loaded = self.map_controller.on_map_loaded
        self._initial_map_sync = self.map_controller.initial_map_sync
        self._load_settings = self.settings_controller.load_settings
        self._apply_startup_window_state = self.settings_controller.apply_startup_window_state
        self.toggle_theme = self.settings_controller.toggle_theme
        self._load_excel = self.data_controller.load_excel
        self.open_excel = self.data_controller.open_excel
        self._load_sort_settings = self.settings_controller.load_sort_settings
        self._save_sort_settings = self.settings_controller.save_sort_settings
        self._update_ui_after_load = self.data_controller.update_ui_after_load
        self._load_gis = self.data_controller.load_gis
        self._update_dashboard_view = self.data_controller.update_dashboard_view
        self._on_tab_changed = self.data_controller.on_tab_changed
        self._load_microbacias_layer = self.map_controller.load_microbacias_layer
        self._run_map_js = self.map_controller.run_map_js
        self.apply_filter = self.data_controller.apply_filter
        self.clear_filters = self.data_controller.clear_filters
        self.reset_sorting = self.settings_controller.reset_sorting
        self._on_map_click = self.map_controller.on_map_click
        self._set_map_marker = self.map_controller.set_map_marker
        self._highlight_microbacia = self.map_controller.highlight_microbacia
        self._set_map_status = self.map_controller.set_map_status
        self._fill_form = self.form_controller.fill_form
        self._check_duplicate_av_tec = self.form_controller.check_duplicate_av_tec
        self._read_form = self.form_controller.read_form
        self.add_new = self.form_controller.add_new
        self.save_edit = self.form_controller.save_edit
        self.delete_selected = self.form_controller.delete_selected
        self.reload = self.data_controller.reload
        self.clear_form = self.form_controller.clear_form
        self.search_on_map = self.map_controller.search_on_map
        self.search_on_map_plantio = self.map_controller.search_on_map_plantio
        self._perform_geocode = self.map_controller.perform_geocode
        self.open_street_view = self.map_controller.open_street_view
        self.load_custom_layer = self.map_controller.load_custom_layer
        self.open_map_fullscreen = self.map_controller.open_map_fullscreen
        self.open_table_fullscreen = self.map_controller.open_table_fullscreen
        self._record_needs_batch_geocode = self.map_controller.record_needs_batch_geocode
        self._persist_batch_geocode_results = self.map_controller.persist_batch_geocode_results
        self.run_batch_geocode = self.map_controller.run_batch_geocode
        self.on_geocode_finished = self.map_controller.on_geocode_finished
        self.toggle_heatmap = self.map_controller.toggle_heatmap
        self._build_heatmap_point = build_heatmap_point
        self.save_map_layer_preference = self.settings_controller.save_map_layer_preference
        self.export_csv_clicked = self.export_controller.export_csv_clicked
        self.export_excel_clicked = self.export_controller.export_excel_clicked
        self.export_pdf_clicked = self.export_controller.export_pdf_clicked
        self.export_ficha_pdf = self.export_controller.export_ficha_pdf
        self.export_dashboard_pdf_clicked = self.export_controller.export_dashboard_pdf_clicked
        self._get_save_path = self.export_controller.get_save_path
        self.show_about_dialog = self.support_controller.show_about_dialog
        self.open_logs_folder = self.support_controller.open_logs_folder
        self.export_diagnostics = self.support_controller.export_diagnostics
        self.check_for_updates = self.support_controller.check_for_updates
        self.present_update_offer = self.support_controller.present_update_offer

    def _prompt_update(self, version: str, notes: str):
        msg = f"Uma nova versão do aplicativo ({version}) está disponível!\n\nNovidades:\n{notes}\n\nDeseja atualizar agora?"
        reply = QMessageBox.question(self, "Atualização Disponível", msg, QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.statusBar().showMessage("Baixando atualização em segundo plano...")
            # Aqui chamaria o subprocess para baixar o .exe novo e substituir via script .bat auxiliar
            QMessageBox.information(self, "Atualizador", "A atualização será baixada. O aplicativo será reiniciado em breve.")

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(5, 5, 5, 5)

        top = QHBoxLayout()
        self.btn_open = QPushButton("Abrir Excel")
        self.btn_reload = QPushButton("Recarregar")
        self.btn_open.setProperty("kind", "primary")
        self.btn_reload.setProperty("kind", "secondary")
        
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar (ofício, av. tec., endereço...)")
        self.search.setClearButtonEnabled(True)

        self.btn_theme = QPushButton("Tema")
        self.btn_theme.setProperty("kind", "secondary")
        self.btn_theme.setFixedWidth(int(70 * self.scale_factor))

        top.addWidget(self.btn_open)
        top.addWidget(self.btn_reload)
        top.addWidget(self.search, 1)
        top.addWidget(self.btn_theme)
        layout.addLayout(top)

        self.tabs = QTabWidget()
        self.data_tab = DataTab(self)
        self.dash_tab = DashboardTab(self)
        self.data_tab.search = self.search
        self.tabs.addTab(self.data_tab, "Dados & Cadastro")
        self.tabs.addTab(self.dash_tab, "Painel")
        layout.addWidget(self.tabs)

        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumWidth(200)
        self.progress_bar.setVisible(False)
        self.form_state_label = QLabel("Sem alterações")
        self.form_state_label.setObjectName("FormStateLabel")
        self.statusBar().addPermanentWidget(self.progress_bar)
        self.statusBar().addPermanentWidget(self.form_state_label)
        self.session_file_label = QLabel("Planilha: nenhuma")
        self.session_file_label.setObjectName("StatusChip")
        self.session_file_label.setMinimumWidth(int(220 * self.scale_factor))
        self.session_file_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.session_records_label = QLabel("Registros: 0")
        self.session_records_label.setObjectName("StatusChip")
        self.session_selection_label = QLabel("Modo: novo cadastro")
        self.session_selection_label.setObjectName("StatusChip")
        self.statusBar().addPermanentWidget(self.session_file_label)
        self.statusBar().addPermanentWidget(self.session_records_label)
        self.statusBar().addPermanentWidget(self.session_selection_label)
        self.statusBar().setSizeGripEnabled(False)

    def _current_file_label_text(self) -> str:
        path = str(getattr(self.excel, "path", "") or "").strip()
        if not path:
            return "Planilha: nenhuma"
        return f"Planilha: {os.path.basename(path) or path}"

    def _current_records_label_text(self) -> str:
        total = len(self.records)
        filtered = len(self.filtered_records)
        if total <= 0:
            return "Registros: 0"
        if filtered == total:
            return f"Registros: {total}"
        return f"Registros: {filtered} de {total}"

    def _current_selection_label_text(self) -> str:
        if self.selected is None:
            return "Modo: novo cadastro"

        summary = (self.selected.av_tec or "").strip()
        if not summary:
            summary = (self.selected.oficio_processo or "").strip()
        if not summary:
            row_number = max(int(getattr(self.selected, "excel_row", 0)) - 1, 0)
            summary = f"linha {row_number}" if row_number else "registro ativo"
        return f"Selecionado: {summary}"

    def _refresh_window_chrome(self):
        path = str(getattr(self.excel, "path", "") or "").strip()
        title = APP_WINDOW_TITLE
        if path:
            title = f"{APP_WINDOW_TITLE}[*] - {os.path.basename(path) or path}"
            if self.records:
                title = f"{title} ({len(self.filtered_records)}/{len(self.records)})"
        self.setWindowTitle(title)

        self.session_file_label.setText(self._current_file_label_text())
        self.session_file_label.setToolTip(path or "Nenhuma planilha carregada.")

        self.session_records_label.setText(self._current_records_label_text())
        search_text = self.search.text().strip()
        if search_text:
            self.session_records_label.setToolTip(f"Busca atual: {search_text}")
        else:
            self.session_records_label.setToolTip("Resumo do conjunto filtrado na tela.")

        self.session_selection_label.setText(self._current_selection_label_text())
        if self.selected is None:
            self.session_selection_label.setToolTip("Formulario pronto para novo cadastro.")
        else:
            self.session_selection_label.setToolTip("Registro atualmente carregado no formulario.")

    def _setup_menus(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu("Arquivo")
        
        self.action_import = QAction("Importar Excel (Mesclar)", self)
        self.action_import.triggered.connect(self.import_excel_data)
        file_menu.addAction(self.action_import)
        
        self.action_rollback = QAction("Máquina do Tempo (Restaurar Backup)", self)
        self.action_rollback.triggered.connect(self.show_rollback_dialog)
        file_menu.addAction(self.action_rollback)
        
        file_menu.addSeparator()

        self.menu_recent = file_menu.addMenu("Recentes")
        self._update_recent_files_menu()

        help_menu = menubar.addMenu("Ajuda")
        self.action_check_updates = QAction("Verificar Atualizacoes", self)
        self.action_check_updates.triggered.connect(self.check_for_updates)
        help_menu.addAction(self.action_check_updates)
        help_menu.addSeparator()
        self.action_export_diagnostics = QAction("Exportar Diagnóstico", self)
        self.action_export_diagnostics.triggered.connect(self.export_diagnostics)
        help_menu.addAction(self.action_export_diagnostics)

        self.action_open_logs = QAction("Abrir Pasta de Logs", self)
        self.action_open_logs.triggered.connect(self.open_logs_folder)
        help_menu.addAction(self.action_open_logs)

        help_menu.addSeparator()

        self.action_about = QAction("Sobre", self)
        self.action_about.triggered.connect(self.show_about_dialog)
        help_menu.addAction(self.action_about)

    def _update_recent_files_menu(self):
        self.menu_recent.clear()
        if not self.recent_files:
            act = self.menu_recent.addAction("Nenhum")
            act.setEnabled(False)
            return
            
        for path in self.recent_files:
            act = self.menu_recent.addAction(os.path.basename(path))
            act.setToolTip(path)
            act.triggered.connect(lambda checked=False, p=path: self._load_excel(p))

    def _snapshot_excel_service_state(self) -> Dict[str, object]:
        return {
            "path": self.excel.path,
            "wb": self.excel.wb,
            "ws": self.excel.ws,
            "col_map": dict(self.excel.col_map),
            "uid_to_row": dict(self.excel.uid_to_row),
            "last_backup_time": self.excel.last_backup_time,
            "merged_cells_warning": self.excel.merged_cells_warning,
        }

    def _restore_excel_service_state(self, snapshot: Dict[str, object]):
        self.excel.path = snapshot["path"]
        self.excel.wb = snapshot["wb"]
        self.excel.ws = snapshot["ws"]
        self.excel.col_map = dict(snapshot["col_map"])
        self.excel.uid_to_row = dict(snapshot["uid_to_row"])
        self.excel.last_backup_time = snapshot["last_backup_time"]
        self.excel.merged_cells_warning = snapshot["merged_cells_warning"]

    def _metrics_to_kpi_rows(self, metrics: Dict[str, object]) -> List[Tuple[str, str]]:
        return [
            ("Total de Registros", str(metrics["count_total"])),
            ("Total de Mudas", f"{metrics['total_geral']:g}"),
            ("Pendentes", f"{metrics['total_pendente']:g}"),
            ("Compensadas", f"{metrics['total_compensado']:g}"),
        ]

    def _build_filter_summary(self) -> str:
        parts = []
        search_text = self.search.text().strip()
        if search_text:
            parts.append(f"Busca: {search_text}")

        status = self.data_tab.filter_status.currentText()
        if status != "Todos":
            parts.append(f"Status: {status}")

        if not self.data_tab.filter_micro.is_all_selected():
            micros = ", ".join(self.data_tab.filter_micro.checked_items())
            parts.append(f"Microbacias: {micros or 'Nenhuma'}")

        if not self.data_tab.filter_eletronico.is_all_selected():
            eletronicos = ", ".join(self.data_tab.filter_eletronico.checked_items())
            parts.append(f"Eletrônico: {eletronicos or 'Nenhum'}")

        year = self.data_tab.filter_year.currentText()
        if year and year != "Todos":
            parts.append(f"Ano: {year}")

        return "Sem filtros aplicados" if not parts else " | ".join(parts)

    def _snapshot_filter_state(self) -> Dict[str, object]:
        return {
            "search_text": self.search.text(),
            "status": self.data_tab.filter_status.currentText(),
            "year": self.data_tab.filter_year.currentText(),
            "micro_all_selected": self.data_tab.filter_micro.is_all_selected(),
            "selected_micros": list(self.data_tab.filter_micro.checked_items()),
            "eletronico_all_selected": self.data_tab.filter_eletronico.is_all_selected(),
            "selected_eletronicos": list(self.data_tab.filter_eletronico.checked_items()),
        }

    def _restore_filter_state(self, state: Dict[str, object]):
        self.search.blockSignals(True)
        self.data_tab.filter_status.blockSignals(True)
        self.data_tab.filter_year.blockSignals(True)
        self.data_tab.filter_micro.blockSignals(True)
        self.data_tab.filter_eletronico.blockSignals(True)
        try:
            self.search.setText(str(state.get("search_text", "")))

            status = str(state.get("status", "Todos"))
            status_index = self.data_tab.filter_status.findText(status)
            self.data_tab.filter_status.setCurrentIndex(status_index if status_index >= 0 else 0)

            year = str(state.get("year", "Todos"))
            year_index = self.data_tab.filter_year.findText(year)
            self.data_tab.filter_year.setCurrentIndex(year_index if year_index >= 0 else 0)

            self.data_tab.filter_micro.set_checked_items(
                list(state.get("selected_micros", [])),
                all_selected=bool(state.get("micro_all_selected", True)),
            )
            self.data_tab.filter_eletronico.set_checked_items(
                list(state.get("selected_eletronicos", [])),
                all_selected=bool(state.get("eletronico_all_selected", True)),
            )
        finally:
            self.search.blockSignals(False)
            self.data_tab.filter_status.blockSignals(False)
            self.data_tab.filter_year.blockSignals(False)
            self.data_tab.filter_micro.blockSignals(False)
            self.data_tab.filter_eletronico.blockSignals(False)

    def _clear_loaded_data_state(self):
        self.records = []
        self.filtered_records = []
        self.selected = None
        self.gis = None
        self.last_marker_coords = None

        empty_metrics = compute_metrics([])
        self.data_tab.table.clearSelection()
        self.data_tab.table_model.update_data([])
        self.data_tab.update_totals_tables(empty_metrics)
        self.dash_tab.update_dashboard(empty_metrics, self.is_dark_mode, [])
        self.data_tab.lbl_results.setText("0 registros")
        self._update_filters_from_records()
        self._setup_dynamic_form_options_from_records()
        self.clear_form()
        self.statusBar().showMessage("Nenhuma planilha carregada")

    def _restore_previous_state(
        self,
        previous_records: List[Compensacao],
        previous_filtered: List[Compensacao],
        previous_selected: Optional[Compensacao],
        previous_marker: Optional[Tuple[float, float]],
        previous_filter_state: Dict[str, object],
    ):
        self.records = list(previous_records)
        self.filtered_records = list(previous_filtered)
        self.last_marker_coords = previous_marker

        if self.records:
            self._update_ui_after_load()
            self._restore_filter_state(previous_filter_state)
            self.apply_filter()
            self._load_sort_settings()
            if previous_selected is not None:
                self.selected = previous_selected
                self._fill_form(previous_selected)
                self._update_form_action_buttons()
                self._update_address_search_enabled()
        else:
            self._clear_loaded_data_state()

    def _connect_signals(self):
        self.btn_open.clicked.connect(self.open_excel)
        self.btn_reload.clicked.connect(self.reload)
        self.btn_theme.clicked.connect(self.toggle_theme)
        
        # Conexão da busca restaurada
        self.search.textChanged.connect(self.schedule_apply_filter)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        
        self.data_tab.filter_micro.currentTextChanged.connect(self.schedule_apply_filter)
        self.data_tab.filter_eletronico.currentTextChanged.connect(self.schedule_apply_filter)
        self.data_tab.filter_status.currentTextChanged.connect(self.schedule_apply_filter)
        self.data_tab.filter_year.currentTextChanged.connect(self.schedule_apply_filter)
        
        self.data_tab.btn_clear_filters.clicked.connect(self.clear_filters)
        self.data_tab.btn_reset_sort.clicked.connect(self.reset_sorting)
        self.data_tab.btn_columns.clicked.connect(self.open_columns_dialog)
        self.data_tab.btn_table_full.clicked.connect(self.open_table_fullscreen)
        
        self.data_tab.table.clicked.connect(self._on_table_clicked)
        
        self.data_tab.btn_clear.clicked.connect(self.clear_form)
        self.data_tab.btn_add.clicked.connect(self.add_new)
        self.data_tab.btn_save_edit.clicked.connect(self.save_edit)
        self.data_tab.btn_delete.clicked.connect(self.delete_selected)
        self.data_tab.btn_ficha_pdf.clicked.connect(self.export_ficha_pdf)
        
        self.data_tab.btn_maps.clicked.connect(self.search_on_map)
        self.data_tab.btn_maps_plantio.clicked.connect(self.search_on_map_plantio)
        self.data_tab.btn_batch_geo.clicked.connect(self.run_batch_geocode)
        self.data_tab.btn_map_full.clicked.connect(self.open_map_fullscreen)
        self.data_tab.btn_street_view.clicked.connect(self.open_street_view)
        self.data_tab.btn_add_layer.clicked.connect(self.load_custom_layer)
        self.data_tab.chk_heatmap.stateChanged.connect(self.toggle_heatmap)
        self.data_tab.combo_heatmap_type.currentTextChanged.connect(self.toggle_heatmap)
        
        self.data_tab.web.loadFinished.connect(self._on_map_loaded)
        
        # Monitoramento de Mudanças (DIRTY CHECK e AS-YOU-TYPE)
        self.data_tab.in_oficio.textChanged.connect(self._validate_as_you_type)
        self.data_tab.in_oficio.textChanged.connect(self._on_form_field_changed)
        self.data_tab.in_caixa.textChanged.connect(self._on_form_field_changed)
        self.data_tab.in_avtec.textChanged.connect(self._validate_as_you_type)
        self.data_tab.in_avtec.textChanged.connect(self._on_form_field_changed)
        self.data_tab.in_comp.textChanged.connect(self._on_form_field_changed)
        self.data_tab.in_end.textChanged.connect(self._on_form_field_changed)
        self.data_tab.in_end_plantio.textChanged.connect(self._on_form_field_changed)
        self.data_tab.in_micro.currentTextChanged.connect(self._on_form_field_changed)
        
        self.data_tab.chk_compensado.toggled.connect(self.data_tab.in_end_plantio.setEnabled)
        self.data_tab.chk_compensado.toggled.connect(self._on_form_field_changed)
        self.data_tab.chk_sn.toggled.connect(self._on_chk_sn_toggled)
        self.data_tab.chk_arquivado.toggled.connect(self._on_chk_arquivado_toggled)
        self.data_tab.chk_arquivado.toggled.connect(self._on_form_field_changed)
        
        self.data_tab.btn_export_csv.clicked.connect(self.export_csv_clicked)
        self.data_tab.btn_export_excel.clicked.connect(self.export_excel_clicked)
        self.data_tab.btn_export_pdf.clicked.connect(self.export_pdf_clicked)
        self.dash_tab.btn_export_pdf.clicked.connect(self.export_dashboard_pdf_clicked)

    def _on_form_field_changed(self):
        self.form_controller.remember_current_state()
        self._update_form_action_buttons()
        self._update_address_search_enabled()

    def _validate_as_you_type(self):
        self.form_controller.validate_as_you_type()

    def _is_form_dirty(self) -> bool:
        return self.form_controller.has_pending_changes()

    def _update_address_search_enabled(self):
        self.map_controller.update_address_search_enabled()

    def open_street_view(self):
        if not self.last_marker_coords:
            QMessageBox.information(self, "Street View", "Clique em um ponto no mapa ou faça uma busca primeiro para obter uma coordenada.")
            return
        lat, lon = self.last_marker_coords
        url = f"https://www.google.com/maps/@?api=1&map_action=pano&viewpoint={lat},{lon}"
        QDesktopServices.openUrl(QUrl(url))
        logger.info(f"Street View aberto para {lat}, {lon}")

    def load_custom_layer(self):
        path, _ = QFileDialog.getOpenFileName(self, "Adicionar Camada GIS", "", "Arquivos GIS (*.geojson *.json *.kml)")
        if not path:
            return
            
        self.statusBar().showMessage(f"Carregando camada: {os.path.basename(path)}...")
        try:
            import geopandas as gpd
            # fiona is required for KML, already in requirements
            import fiona
            fiona.drvsupport.supported_drivers['KML'] = 'rw'
            
            gdf = gpd.read_file(path)
            if gdf.crs and gdf.crs.to_epsg() != 4326:
                gdf = gdf.to_crs(epsg=4326)
                
            geojson_str = gdf.to_json()
            geojson_obj = json.loads(geojson_str)
            
            # Adiciona a camada externa ao Leaflet (precisamos garantir que a função exista no JS, usaremos a mesma base de microbacias por hora ou injetaremos direto)
            script = f"""
            if(window.map) {{
                if(window.customLayer) window.map.removeLayer(window.customLayer);
                window.customLayer = L.geoJSON({json.dumps(geojson_obj)}, {{
                    style: function(feature) {{
                        return {{color: "#e74c3c", weight: 2, fillOpacity: 0.1, dashArray: '5, 5'}};
                    }}
                }}).addTo(window.map);
                window.map.fitBounds(window.customLayer.getBounds());
            }}
            """
            self._run_map_js(script, "load-custom-layer")
            QMessageBox.information(self, "Sucesso", "Camada carregada com sucesso.")
            logger.info(f"Camada GIS carregada: {path}")
        except Exception as e:
            logger.error(f"Erro ao carregar camada GIS: {e}")
            QMessageBox.critical(self, "Erro", f"Não foi possível ler o arquivo GIS:\n{e}")
        finally:
            self.statusBar().showMessage("Pronto")

    def show_rollback_dialog(self):
        if not self.excel.path:
            QMessageBox.warning(self, "Aviso", "Abra uma planilha primeiro para ver seus backups.")
            return

        base_dir = os.path.dirname(self.excel.path)
        backup_dir = os.path.join(base_dir, "backups_historico")
        
        if not os.path.exists(backup_dir):
            QMessageBox.information(self, "Backups", "Nenhum backup encontrado ainda para este arquivo.")
            return

        import glob
        from datetime import datetime
        
        files = glob.glob(os.path.join(backup_dir, "*.xlsx"))
        files.sort(key=os.path.getmtime, reverse=True)
        
        if not files:
            QMessageBox.information(self, "Backups", "Nenhum backup encontrado ainda para este arquivo.")
            return

        # Format list for UI
        options = []
        file_map = {}
        for f in files:
            mtime = os.path.getmtime(f)
            dt_str = datetime.fromtimestamp(mtime).strftime('%d/%m/%Y %H:%M:%S')
            label = f"{dt_str} - {os.path.basename(f)}"
            options.append(label)
            file_map[label] = f

        item, ok = QInputDialog.getItem(
            self, "Máquina do Tempo", 
            "Selecione uma versão anterior para restaurar (O arquivo atual será substituído):",
            options, 0, False
        )
        
        if ok and item:
            selected_file = file_map[item]
            if msg_confirm(self, "ATENÇÃO", f"Tem certeza que deseja restaurar a versão de {item.split(' - ')[0]}? As alterações atuais serão perdidas!"):
                import shutil
                try:
                    # Fazemos um backup do estado atual just in case
                    self.excel._create_rotating_backup()
                    # Restaura o backup selecionado
                    shutil.copy2(selected_file, self.excel.path)
                    self.reload()
                    QMessageBox.information(self, "Sucesso", "Backup restaurado com sucesso!")
                    logger.info(f"Rollback executado usando arquivo {selected_file}")
                except Exception as e:
                    QMessageBox.critical(self, "Erro", f"Falha ao restaurar backup: {e}")

    def import_excel_data(self):
        if not self.excel.path:
            QMessageBox.warning(self, "Aviso", "Abra a planilha base primeiro.")
            return
            
        path, _ = QFileDialog.getOpenFileName(self, "Importar Planilha", "", "Excel (*.xlsx)")
        if not path:
            return
            
        if path == self.excel.path:
            QMessageBox.warning(self, "Aviso", "Você selecionou o mesmo arquivo já aberto.")
            return

        self.statusBar().showMessage("Analisando arquivo para importação...")
        
        try:
            temp_service = ExcelService()
            incoming_records = temp_service.load(path)
            
            # Smart Merge Logic
            current_av_tecs = {r.av_tec.strip().upper(): r for r in self.records if r.av_tec}
            current_uids = {r.uid: r for r in self.records if r.uid}
            
            to_add = []
            for inc in incoming_records:
                # Se não tiver UID ou o UID não existir na base atual, verificamos por Av Tec.
                if inc.uid in current_uids:
                    continue
                if inc.av_tec and inc.av_tec.strip().upper() in current_av_tecs:
                    continue
                to_add.append(inc)

            if not to_add:
                QMessageBox.information(self, "Importação", "Nenhum registro novo encontrado para importar.")
                self.statusBar().showMessage("Importação concluída sem adições")
                return

            msg = f"Encontrados {len(to_add)} registros novos.\nDeseja incorporá-los à sua planilha atual?"
            if msg_confirm(self, "Mesclar Dados", msg):
                self.progress_bar.setVisible(True)
                self.progress_bar.setMaximum(len(to_add))
                
                for i, r in enumerate(to_add):
                    # Forçamos a geração de novo Excel Row na base atual
                    self.excel.add_new(r)
                    self.progress_bar.setValue(i + 1)
                    QApplication.processEvents() # Mantém UI responsiva
                    
                self.progress_bar.setVisible(False)
                self.reload()
                QMessageBox.information(self, "Sucesso", f"{len(to_add)} registros importados com sucesso!")
                logger.info(f"Importados {len(to_add)} registros de {path}")
            else:
                self.statusBar().showMessage("Importação cancelada")
                
        except Exception as e:
            logger.error(f"Erro na importação de {path}: {e}")
            QMessageBox.critical(self, "Erro de Importação", f"Falha ao ler ou mesclar o arquivo: {e}")
            self.statusBar().showMessage("Falha na importação")

    def _update_form_action_buttons(self):
        has_excel = bool(self.excel.path and os.path.exists(self.excel.path))
        has_selected = self.selected is not None
        is_dirty = self._is_form_dirty()
        self.data_tab.btn_add.setEnabled(has_excel)
        self.data_tab.btn_save_edit.setEnabled(has_excel and has_selected and is_dirty)
        self.data_tab.btn_delete.setEnabled(has_excel and has_selected)
        self.data_tab.btn_ficha_pdf.setEnabled(has_excel and has_selected)

    def _on_map_loaded(self, ok):
        if ok:
            self._initial_map_sync_timer.start(500)

    def _initial_map_sync(self):
        self._apply_theme_to_map() 
        layer = self.settings.value("map_layer", "Mapa Claro")
        self._run_map_js(f"if(window.setBaseLayer) window.setBaseLayer('{layer}');", "restore-layer")
        if self.gis:
            self._load_microbacias_layer()
        self.toggle_heatmap()

    def _on_chk_sn_toggled(self, checked):
        self.data_tab.in_oficio.blockSignals(True)
        if checked:
            self.data_tab.in_oficio.setText("S/N")
            self.data_tab.in_oficio.setEnabled(False)
        else:
            if self.data_tab.in_oficio.text().upper() == "S/N":
                self.data_tab.in_oficio.clear()
            self.data_tab.in_oficio.setEnabled(True)
            self.data_tab.in_oficio.setFocus()
        self.data_tab.in_oficio.blockSignals(False)
        self.form_controller.remember_current_state()
        self._update_form_action_buttons()

    def _on_chk_arquivado_toggled(self, checked):
        self.data_tab.in_caixa.blockSignals(True)
        if checked:
            self.data_tab.in_caixa.setText("Arquivado")
            self.data_tab.in_caixa.setEnabled(False)
        else:
            if self.data_tab.in_caixa.text().upper() == "ARQUIVADO":
                self.data_tab.in_caixa.clear()
            self.data_tab.in_caixa.setEnabled(True)
            self.data_tab.in_caixa.setFocus()
        self.data_tab.in_caixa.blockSignals(False)
        self.form_controller.remember_current_state()
        self._update_form_action_buttons()

    def _load_settings(self):
        self.is_dark_mode = str(self.settings.value("dark_mode", "false")).lower() == "true"
        # Aba ativa
        tab_index = int(self.settings.value("active_tab_index", 0))
        if 0 <= tab_index < self.tabs.count():
            self.tabs.setCurrentIndex(tab_index)
            
        recents = self.settings.value("recent_files")
        if recents:
            if isinstance(recents, str):
                try:
                    self.recent_files = json.loads(recents)
                except:
                    self.recent_files = []
            elif isinstance(recents, list):
                self.recent_files = recents
        self._update_recent_files_menu()

    def _apply_startup_window_state(self):
        if self._startup_window_state_applied:
            return

        self._startup_window_state_applied = True
        self.setWindowState(self.windowState() & ~(Qt.WindowMinimized | Qt.WindowFullScreen))
        self.showNormal()
        self.showMaximized()
        self._startup_layout_pending = True

    def _finalize_startup_layout(self):
        self.data_tab.align_splitter_to_table_width()
        self.data_tab._sync_left_panel_heights()

    def _apply_theme(self):
        t = THEME_DARK if self.is_dark_mode else THEME_LIGHT
        qss = get_app_qss(t, self.scale_factor) # Passando a escala aqui
        app = QApplication.instance()
        if app:
            app.setStyleSheet(qss)
        self.setStyleSheet(qss)
        self.data_tab.table_model.set_dark_mode(self.is_dark_mode)
        self.dash_tab.apply_theme(t)
        self._apply_theme_to_map()

    def _apply_theme_to_map(self):
        self._run_map_js(f"if(window.setTheme) window.setTheme('{'dark' if self.is_dark_mode else 'light'}');", "theme")

    def toggle_theme(self):
        self.is_dark_mode = not self.is_dark_mode
        self.settings.setValue("dark_mode", str(self.is_dark_mode).lower())
        self._apply_theme()
        self.apply_filter()

    def _load_excel(self, path):
        logger.info(f"Tentando carregar planilha: {path}")
        previous_records = list(self.records)
        previous_filtered = list(self.filtered_records)
        previous_selected = self.selected
        previous_marker = self.last_marker_coords
        previous_filter_state = self._snapshot_filter_state()
        previous_service_state = self._snapshot_excel_service_state()
        previous_recent_files = list(self.recent_files)
        try:
            self.records = self.excel.load(path)
            logger.info(f"ExcelService.load retornou {len(self.records)} registros.")
            if not self.records:
                logger.warning("Atenção: A planilha foi lida mas retornou 0 registros.")
                
            self.settings.setValue("last_excel_path", path)
            
            if path in self.recent_files:
                self.recent_files.remove(path)
            self.recent_files.insert(0, path)
            self.recent_files = self.recent_files[:5]
            self.settings.setValue("recent_files", self.recent_files)
            self._update_recent_files_menu()
            
            # Atualiza todos os componentes da interface
            self._update_ui_after_load()
            
            # Restaurar ordenação
            self._load_sort_settings()
            logger.info("Interface atualizada com sucesso após carga de dados.")
            return True
        except Exception as e:
            self._restore_excel_service_state(previous_service_state)
            self.recent_files = list(previous_recent_files)
            self.settings.setValue("recent_files", self.recent_files)
            self._update_recent_files_menu()
            self.settings.remove("last_excel_path")
            self._restore_previous_state(
                previous_records,
                previous_filtered,
                previous_selected,
                previous_marker,
                previous_filter_state,
            )
            logger.error(f"Erro fatal ao carregar {path}: {e}", exc_info=True)
            QMessageBox.critical(self, "Erro", f"Falha ao carregar: {e}")
            return False

    def open_excel(self):
        path, _ = QFileDialog.getOpenFileName(self, "Abrir Excel", "", "Excel (*.xlsx)")
        if path and self._load_excel(path):
            QMessageBox.information(self, "Sucesso", f"Carregado: {len(self.records)} registros.")

    def _load_last_excel(self):
        return self.data_controller.load_last_excel()

    def _load_sort_settings(self):
        col = int(self.settings.value("sort_column", -1))
        if col >= 0:
            order = Qt.SortOrder(int(self.settings.value("sort_order", 0)))
            self.data_tab.proxy.sort(col, order)
            self.data_tab.table.horizontalHeader().setSortIndicator(col, order)
        else:
            self.data_tab.proxy.sort(-1)

    def _save_sort_settings(self):
        self.settings.setValue("sort_column", self.data_tab.proxy.sortColumn())
        self.settings.setValue("sort_order", int(self.data_tab.proxy.sortOrder().value))

    def _update_ui_after_load(self):
        self._update_filters_from_records()
        self._setup_dynamic_form_options_from_records()
        self._load_gis()
        self.apply_filter()
        self.data_tab.align_splitter_to_table_width()
        QTimer.singleShot(0, self.data_tab.align_splitter_to_table_width)
        self.data_tab.table.clearSelection()
        self.clear_form()

    def _load_gis(self):
        if os.path.isdir(MICROB_DIR):
            self.gis = GisService(MICROB_DIR, MICROB_NAME_FIELD)
            self._load_microbacias_layer()

    def _update_dashboard_view(self, metrics: Dict[str, object]):
        self._pending_dashboard_metrics = dict(metrics)
        if self.tabs.currentWidget() is self.dash_tab:
            self.dash_tab.update_dashboard(metrics, self.is_dark_mode, [r.microbacia for r in self.records])
            self._dashboard_dirty = False
        else:
            self._dashboard_dirty = True

    def _on_tab_changed(self, _index: int):
        if self.tabs.currentWidget() is self.dash_tab and self._dashboard_dirty and self._pending_dashboard_metrics is not None:
            self.dash_tab.update_dashboard(
                self._pending_dashboard_metrics,
                self.is_dark_mode,
                [r.microbacia for r in self.records],
            )
            self._dashboard_dirty = False

    def _load_microbacias_layer(self):
        if self.gis:
            geojson = self.gis.to_geojson_obj()
            self._run_map_js(f"if(window.setMicrobacias) window.setMicrobacias({json.dumps(geojson)});", "load-microbacias")

    def _run_map_js(self, script: str, context: str):
        try:
            self.data_tab.web.page().runJavaScript(script)
        except Exception as exc:
            logger.error(f"[MAP JS] Falha em {context}: {exc}")

    def apply_filter(self):
        self.filtered_records = filter_records(
            self.records,
            text=self.search.text(),
            status=self.data_tab.filter_status.currentText(),
            selected_micros=self.data_tab.filter_micro.checked_items(),
            selected_eletronicos=self.data_tab.filter_eletronico.checked_items(),
            micro_all_selected=self.data_tab.filter_micro.is_all_selected(),
            eletronico_all_selected=self.data_tab.filter_eletronico.is_all_selected(),
            selected_year=self.data_tab.filter_year.currentText()
        )
        self.data_tab.table_model.update_data(self.filtered_records)
        self.data_tab._resize_column_to_texts(
            self.data_tab.OFICIO_COLUMN_INDEX,
            [record.oficio_processo for record in self.records],
        )
        m = compute_metrics(self.filtered_records)
        self._update_dashboard_view(m)
        self.data_tab.update_totals_tables(m)
        self.data_tab.lbl_results.setText(f"{len(self.filtered_records)} registros")
        self.statusBar().showMessage(f"Filtro aplicado: {len(self.filtered_records)} registros")
        self.toggle_heatmap()
        self.data_tab._sync_left_panel_heights()
        QTimer.singleShot(0, self.data_tab._sync_left_panel_heights)

    def clear_filters(self):
        self.search.clear()
        self.data_tab.filter_status.setCurrentIndex(0)
        self.data_tab.filter_year.setCurrentIndex(0)
        self.data_tab.filter_micro.select_all()
        self.data_tab.filter_eletronico.select_all()
        self.apply_filter()
        self.statusBar().showMessage("Filtros limpos")

    def reset_sorting(self):
        self.data_tab.proxy.sort(-1)
        self.settings.setValue("sort_column", -1)

    def open_columns_dialog(self):
        visible_map = {
            index: not self.data_tab.table.isColumnHidden(index)
            for index in range(self.data_tab.table_model.columnCount())
        }
        dialog = ColumnsDialog(self, list(DISPLAY_COLUMN_LABELS), visible_map)
        if not dialog.exec():
            return

        new_map = dialog.visible_map()
        if not any(new_map.values()):
            QMessageBox.warning(self, "Aviso", "Selecione pelo menos uma coluna para exibir.")
            return

        for index, is_visible in new_map.items():
            self.data_tab.table.setColumnHidden(index, not is_visible)

    def _on_table_clicked(self, index):
        if self.selected is not None and self.form_controller.has_pending_changes():
            if not self.form_controller.confirm_discard_changes("trocar de registro"):
                return
        src_index = self.data_tab.proxy.mapToSource(index)
        self.selected = self.filtered_records[src_index.row()]
        self._fill_form(self.selected)
        self._update_form_action_buttons()
        self._update_address_search_enabled()
        
        lat = getattr(self.selected, "latitude", "")
        lon = getattr(self.selected, "longitude", "")
        if str(lat).strip() and str(lon).strip():
            self._set_map_marker(float(lat), float(lon))
            if self.selected.microbacia:
                self._highlight_microbacia(self.selected.microbacia)

    def _on_map_click(self, lat, lon):
        self.last_marker_coords = (lat, lon)
        self._set_map_marker(lat, lon)
        if self.gis:
            micro = self.gis.find_microbacia(lat, lon)
            if micro:
                self.data_tab.in_micro.setCurrentText(micro)
                self._highlight_microbacia(micro)
                self._set_map_status(f"Ponto dentro de: {micro}")
                self.statusBar().showMessage(f"Ponto capturado. Microbacia: {micro}")
            else:
                self._set_map_status("Fora de microbacia conhecida.")
                self.statusBar().showMessage(f"Ponto capturado: {lat:.5f}, {lon:.5f}")
        self._update_form_action_buttons()
        self._update_address_search_enabled()

    def _set_map_marker(self, lat, lon):
        lat = float(lat)
        lon = float(lon)
        self.last_marker_coords = (lat, lon)
        self._run_map_js(f"if(window.setMarker) window.setMarker({lat}, {lon});", "marker")
        self._update_address_search_enabled()

    def _highlight_microbacia(self, name):
        self._run_map_js(f"if(window.highlightGeoJsonByName) window.highlightGeoJsonByName('{MICROB_NAME_FIELD}', {json.dumps(name)});", "highlight")

    def _set_map_status(self, msg):
        self._run_map_js(f"if(window.setStatus) window.setStatus({json.dumps(msg)});", "status")

    def _fill_form(self, c: Compensacao):
        self.data_tab.in_oficio.blockSignals(True)
        self.data_tab.in_caixa.blockSignals(True)
        self.data_tab.in_avtec.blockSignals(True)
        self.data_tab.in_comp.blockSignals(True)
        self.data_tab.in_end.blockSignals(True)
        self.data_tab.in_end_plantio.blockSignals(True)
        self.data_tab.in_micro.blockSignals(True)
        self.data_tab.chk_sn.blockSignals(True)
        self.data_tab.chk_arquivado.blockSignals(True)
        self.data_tab.chk_compensado.blockSignals(True)

        of_val = (c.oficio_processo or "").strip()
        is_sn = of_val.upper() == "S/N"
        self.data_tab.chk_sn.setChecked(is_sn)
        self.data_tab.in_oficio.setEnabled(not is_sn)
        self.data_tab.in_oficio.setText(of_val)
        
        cx_val = (c.caixa or "").strip()
        is_arq = cx_val.upper() == "ARQUIVADO"
        self.data_tab.chk_arquivado.setChecked(is_arq)
        self.data_tab.in_caixa.setEnabled(not is_arq)
        self.data_tab.in_caixa.setText(cx_val)

        self.data_tab.in_avtec.setText(c.av_tec)
        self.data_tab.in_comp.setText(str(c.compensacao or ""))
        self.data_tab.in_end.setText(c.endereco)
        self.data_tab.in_end_plantio.setText(c.endereco_plantio)
        self.data_tab.in_micro.setCurrentText(c.microbacia)
        self.data_tab.chk_compensado.setChecked(safe_upper(c.compensado) == "SIM")
        self.data_tab.in_end_plantio.setEnabled(safe_upper(c.compensado) == "SIM")
        
        val = safe_upper(c.eletronico)
        for btn in self.data_tab.eletronico_group.buttons():
            btn.blockSignals(True)
            if safe_upper(btn.text()) == val:
                btn.setChecked(True)
            else:
                btn.setChecked(False)
            btn.blockSignals(False)

        self.data_tab.in_oficio.blockSignals(False)
        self.data_tab.in_caixa.blockSignals(False)
        self.data_tab.in_avtec.blockSignals(False)
        self.data_tab.in_comp.blockSignals(False)
        self.data_tab.in_end.blockSignals(False)
        self.data_tab.in_end_plantio.blockSignals(False)
        self.data_tab.in_micro.blockSignals(False)
        self.data_tab.chk_sn.blockSignals(False)
        self.data_tab.chk_arquivado.blockSignals(False)
        self.data_tab.chk_compensado.blockSignals(False)

    def _check_duplicate_av_tec(self, av_tec: str, current_uid: str) -> Optional[int]:
        if not av_tec: return None
        target = av_tec.strip().upper()
        for r in self.records:
            if r.uid != current_uid and r.av_tec.strip().upper() == target:
                actual = self.excel._find_row_by_uid(r.uid)
                return actual if actual else r.excel_row
        return None

    def _read_form(self) -> Compensacao:
        ele_val = ""
        checked = self.data_tab.eletronico_group.checkedButton()
        if checked:
            ele_val = checked.text()
        return Compensacao(
            excel_row=self.selected.excel_row if self.selected else -1,
            oficio_processo=self.data_tab.in_oficio.text().strip(),
            caixa=self.data_tab.in_caixa.text().strip(),
            av_tec=self.data_tab.in_avtec.text().strip(),
            compensacao=self.data_tab.in_comp.text().strip(),
            endereco=self.data_tab.in_end.text().strip(),
            endereco_plantio=self.data_tab.in_end_plantio.text().strip(),
            microbacia=self.data_tab.in_micro.currentText().strip(),
            compensado="SIM" if self.data_tab.chk_compensado.isChecked() else "",
            eletronico=ele_val,
            uid=self.selected.uid if self.selected else ""
        )

    def add_new(self):
        if not self.excel.path: return
        c = self._read_form()
        err = validate_compensacao(c)
        if err:
            QMessageBox.warning(self, "Erro", err)
            return
        dup = self._check_duplicate_av_tec(c.av_tec, "")
        if dup and not msg_confirm(self, "Duplicado", f"A Av. Tec. '{c.av_tec}' já existe na linha {dup-1}. Cadastrar mesmo assim?"):
            return
        self.excel.add_new(c)
        self.reload()
        self.clear_form()
        QMessageBox.information(self, "Sucesso", "Adicionado com sucesso.")

    def save_edit(self):
        if not self.excel.path or not self.selected: return
        c = self._read_form()
        err = validate_compensacao(c)
        if err:
            QMessageBox.warning(self, "Erro", err)
            return
        dup = self._check_duplicate_av_tec(c.av_tec, c.uid)
        if dup and not msg_confirm(self, "Duplicado", f"A Av. Tec. '{c.av_tec}' já existe na linha {dup-1}. Salvar mesmo assim?"):
            return
        self.excel.save_edit(c)
        self.reload()
        QMessageBox.information(self, "Sucesso", "Salvo com sucesso.")

    def delete_selected(self):
        if self.selected and msg_confirm(self, "Excluir", "Deseja excluir este registro?"):
            self.excel.delete_record_shift_up(self.selected.excel_row, self.selected.uid)
            self.reload()
            self.clear_form()
            self.statusBar().showMessage("Registro excluído")

    def _delete_selected_from_table_shortcut(self):
        current_index = self.data_tab.table.currentIndex()
        if current_index.isValid():
            src_index = self.data_tab.proxy.mapToSource(current_index)
            if 0 <= src_index.row() < len(self.filtered_records):
                self.selected = self.filtered_records[src_index.row()]
        self.delete_selected()

    def reload(self):
        if self.excel.path:
            self._load_excel(self.excel.path)

    def clear_form(self):
        self.selected = None
        for w in [self.data_tab.in_oficio, self.data_tab.in_avtec, self.data_tab.in_comp, 
                  self.data_tab.in_end, self.data_tab.in_end_plantio, self.data_tab.in_caixa]:
            w.clear()
        self.data_tab.in_micro.setCurrentIndex(-1)
        self.data_tab.in_micro.setEditText("")
        self.data_tab.eletronico_group.setExclusive(False)
        for btn in self.data_tab.eletronico_group.buttons():
            btn.setChecked(False)
        self.data_tab.eletronico_group.setExclusive(True)
        self.data_tab.chk_compensado.setChecked(False)
        self.data_tab.chk_sn.setChecked(False)
        self.data_tab.chk_arquivado.setChecked(False)
        self.data_tab.in_oficio.setEnabled(True)
        self.data_tab.in_caixa.setEnabled(True)
        self.data_tab.in_avtec.setStyleSheet("")
        self.data_tab.in_avtec.setToolTip("")
        self.data_tab.table.clearSelection()
        self._update_form_action_buttons()
        self._update_address_search_enabled()
        self.statusBar().showMessage("Novo registro")

    def search_on_map(self):
        addr = self.data_tab.in_end.text().strip()
        if not addr:
            QMessageBox.warning(self, "Atenção", "Digite um endereço para pesquisar.")
            return
        self.statusBar().showMessage("Pesquisando endereço...")
        self._perform_geocode(addr)

    def search_on_map_plantio(self):
        addr = self.data_tab.in_end_plantio.text().strip()
        if not addr:
            QMessageBox.warning(self, "Atenção", "Digite um endereço de plantio para pesquisar.")
            return
        self.statusBar().showMessage("Pesquisando endereço de plantio...")
        self._perform_geocode(addr)

    def _perform_geocode(self, address):
        coords = geocode_address_arcgis(address)
        if coords:
            self._set_map_marker(coords[0], coords[1])
            if self.gis:
                m = self.gis.find_microbacia(*coords)
                if m:
                    self.data_tab.in_micro.setCurrentText(m)
                    self._highlight_microbacia(m)
                    self.statusBar().showMessage(f"Localizado. Microbacia: {m}")
                else:
                    self.statusBar().showMessage("Localizado (fora de microbacia)")
            self._update_form_action_buttons()
        else:
            QMessageBox.warning(self, "Não encontrado", "Não consegui localizar esse endereço.")
            self.statusBar().showMessage("Endereço não encontrado")

    def open_map_fullscreen(self):
        path = resource_path("app", "ui", "map_leaflet.html")
        dlg = MapFullScreenDialog(self, path, self.gis.to_geojson_obj() if self.gis else None, "dark" if self.is_dark_mode else "light", self.last_marker_coords, self.gis, self.settings.value("map_layer", "Mapa Claro"), [])
        dlg.exec()

    def open_table_fullscreen(self):
        splitter = self.data_tab.splitter
        left_panel = self.data_tab.left_panel
        target_index = splitter.indexOf(left_panel)
        previous_sizes = splitter.sizes()

        def restore_panel(widget):
            splitter.insertWidget(target_index if target_index >= 0 else 0, widget)
            QTimer.singleShot(0, lambda: splitter.setSizes(previous_sizes))

        dlg = TableFullScreenDialog(self, left_panel, restore_panel)
        dlg.exec()

    def _record_needs_batch_geocode(self, record: Compensacao) -> bool:
        has_main_address = bool((record.endereco or "").strip())
        has_plantio_address = bool((record.endereco_plantio or "").strip())
        has_main_coords = bool(str(getattr(record, "latitude", "")).strip() and str(getattr(record, "longitude", "")).strip())
        has_plantio_coords = bool(str(getattr(record, "latitude_plantio", "")).strip() and str(getattr(record, "longitude_plantio", "")).strip())
        has_micro = bool((record.microbacia or "").strip())

        needs_main = has_main_address and (not has_main_coords or not has_micro)
        needs_plantio = has_plantio_address and (not has_plantio_coords or (not has_micro and not has_main_address))
        return needs_main or needs_plantio

    def _persist_batch_geocode_results(self, results: Dict[int, Dict[str, Tuple[float, float]]]) -> int:
        if not results:
            return 0

        micro_finder = build_cached_microbacia_finder(self.gis.find_microbacia) if self.gis else None
        updated_records: List[Compensacao] = []

        for excel_row, geocode_data in results.items():
            record = find_record_by_excel_row(self.records, excel_row)
            if not record:
                continue

            changed = False
            main_coords = geocode_data.get("main")
            if main_coords:
                lat, lon = float(main_coords[0]), float(main_coords[1])
                apply_geocode_to_record(record, lat, lon, micro_finder)
                changed = True

            plantio_coords = geocode_data.get("plantio")
            if plantio_coords:
                lat_p, lon_p = float(plantio_coords[0]), float(plantio_coords[1])
                record.latitude_plantio = str(lat_p)
                record.longitude_plantio = str(lon_p)
                changed = True

                if not (record.microbacia or "").strip() and not main_coords and micro_finder:
                    try:
                        micro = micro_finder(lat_p, lon_p)
                    except Exception:
                        micro = ""
                    if micro and str(micro).strip():
                        record.microbacia = str(micro).strip()

            if changed:
                updated_records.append(record)

        return self.excel.save_batch_edits(updated_records)

    def run_batch_geocode(self):
        pending = [r for r in self.records if self._record_needs_batch_geocode(r)]
        if not pending:
            QMessageBox.information(self, "Sucesso", "Tudo georreferenciado!")
            return
        if msg_confirm(self, "GPS em Lote", f"Deseja buscar coordenadas para {len(pending)} registros?"):
            self.progress_bar.setVisible(True)
            self.progress_bar.setRange(0, len(pending))
            self.progress_bar.setValue(0)
            self.statusBar().showMessage("Iniciando geocodificação em lote...")
            self.geo_worker = GeocodeWorker(pending)
            self.geo_worker.progress_update.connect(lambda i, msg: (self.progress_bar.setValue(i), self.statusBar().showMessage(msg)))
            self.geo_worker.finished_process.connect(self.on_geocode_finished)
            self.geo_worker.start()

    def on_geocode_finished(self, results):
        self.progress_bar.setVisible(False)
        self.statusBar().showMessage("Geoprocessamento concluído.")
        if not results:
            QMessageBox.information(self, "Concluído", "Nenhum endereço pôde ser processado.")
            return

        try:
            updated = self._persist_batch_geocode_results(results)
        except Exception as exc:
            logger.error(f"Falha ao salvar geocodificação em lote: {exc}", exc_info=True)
            QMessageBox.critical(self, "Erro", f"Falha ao salvar coordenadas do GPS em lote: {exc}")
            return

        if updated:
            QMessageBox.information(self, "Concluído", f"{updated} registros tiveram coordenadas salvas.")
            self.reload()
        else:
            QMessageBox.information(self, "Concluído", "Nenhuma coordenada nova foi salva.")

    def toggle_heatmap(self):
        if not self.data_tab.chk_heatmap.isChecked():
            self._run_map_js("if(window.setHeatmap) window.setHeatmap([]);", "clear-heatmap")
            return
        typ = self.data_tab.combo_heatmap_type.currentText()
        pts = []
        for r in self.filtered_records:
            point = self._build_heatmap_point(r, typ)
            if point:
                pts.append(point)
        self._run_map_js(f"if(window.setHeatmap) window.setHeatmap({json.dumps(pts)});", "update-heatmap")

    def _build_heatmap_point(self, record: Compensacao, heatmap_type: str) -> Optional[List[float]]:
        return build_heatmap_point(record, heatmap_type)

    def _update_filters_from_records(self):
        micros = unique_non_empty([r.microbacia for r in self.records])
        eles = unique_non_empty([r.eletronico for r in self.records])
        self.data_tab.filter_micro.set_items(micros)
        self.data_tab.filter_eletronico.set_items(eles)
        anos = sorted(list(set(extract_year(r.oficio_processo) for r in self.records if extract_year(r.oficio_processo))), reverse=True)
        self.data_tab.filter_year.clear()
        self.data_tab.filter_year.addItems(["Todos"] + anos)

    def _setup_dynamic_form_options_from_records(self):
        micros = unique_non_empty([r.microbacia for r in self.records])
        cur_micro = self.data_tab.in_micro.currentText()
        self.data_tab.in_micro.clear()
        self.data_tab.in_micro.addItem("")
        for m in micros:
            self.data_tab.in_micro.addItem(m)
        if cur_micro:
            self.data_tab.in_micro.setCurrentText(cur_micro)
        opcoes = unique_non_empty([r.eletronico for r in self.records])
        if not opcoes:
            opcoes = ["SIM", "NÃO"]
        while self.data_tab.eletronico_layout.count():
            item = self.data_tab.eletronico_layout.takeAt(0)
            if item.widget():
                self.data_tab.eletronico_group.removeButton(item.widget())
                item.widget().deleteLater()
        for opt in opcoes:
            rb = QRadioButton(opt)
            rb.setMinimumHeight(24)
            rb.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            self.data_tab.eletronico_group.addButton(rb)
            rb.clicked.connect(self._on_form_field_changed)
            self.data_tab.eletronico_layout.addWidget(rb)
        self.data_tab.eletronico_layout.addStretch(1)

    def save_map_layer_preference(self, layer_name):
        self.settings.setValue("map_layer", layer_name)

    def _setup_shortcuts(self):
        act_save = QAction(self)
        act_save.setShortcut("Ctrl+S")
        act_save.triggered.connect(self.save_edit)
        self.addAction(act_save)
        act_undo = QAction(self)
        act_undo.setShortcut(QKeySequence.Undo)
        act_undo.triggered.connect(self.form_controller.undo)
        self.addAction(act_undo)
        act_redo = QAction(self)
        act_redo.setShortcut(QKeySequence.Redo)
        act_redo.triggered.connect(self.form_controller.redo)
        self.addAction(act_redo)
        act_new = QAction(self)
        act_new.setShortcut("Ctrl+N")
        act_new.triggered.connect(self.clear_form)
        self.addAction(act_new)
        act_delete = QAction(self.data_tab.table)
        act_delete.setShortcut(QKeySequence(Qt.Key_Delete))
        act_delete.setShortcutContext(Qt.WidgetShortcut)
        act_delete.triggered.connect(self._delete_selected_from_table_shortcut)
        self.data_tab.table.addAction(act_delete)

    def _get_visible_column_attrs(self) -> List[str]:
        attrs = []
        header = self.data_tab.table.horizontalHeader()
        for i, attr in enumerate(DISPLAY_COLUMN_ATTRS):
            # O índice 'i' aqui é o índice lógico (do modelo)
            # isColumnHidden também espera o índice lógico
            if not self.data_tab.table.isColumnHidden(i):
                attrs.append(attr)
        return attrs

    def export_csv_clicked(self):
        path = self._get_save_path("Salvar CSV", "CSV (*.csv)")
        if path:
            try:
                export_csv(path, self.filtered_records, self._get_visible_column_attrs())
            except Exception as exc:
                logger.error(f"Falha ao exportar CSV para {path}: {exc}", exc_info=True)
                QMessageBox.critical(self, "Erro", f"Falha ao exportar CSV: {exc}")
                return
            QMessageBox.information(self, "Sucesso", "CSV exportado com sucesso.")

    def export_excel_clicked(self):
        path = self._get_save_path("Salvar Excel", "Excel (*.xlsx)")
        if path:
            metrics = compute_metrics(self.filtered_records)
            try:
                export_excel_two_sheets(
                    path,
                    self.filtered_records,
                    self._build_filter_summary(),
                    self._get_visible_column_attrs(),
                    self._metrics_to_kpi_rows(metrics),
                    metrics["pend_micro_sorted"],
                    metrics["pend_ele_sorted"],
                )
            except Exception as exc:
                logger.error(f"Falha ao exportar Excel para {path}: {exc}", exc_info=True)
                QMessageBox.critical(self, "Erro", f"Falha ao exportar Excel: {exc}")
                return
            QMessageBox.information(self, "Sucesso", "Excel exportado com sucesso.")

    def export_pdf_clicked(self):
        path = self._get_save_path("Salvar PDF", "PDF (*.pdf)")
        if path:
            metrics = compute_metrics(self.filtered_records)
            try:
                export_pdf(
                    path,
                    self.filtered_records,
                    self._build_filter_summary(),
                    self._get_visible_column_attrs(),
                    self._metrics_to_kpi_rows(metrics),
                    metrics["pend_micro_sorted"],
                )
            except Exception as exc:
                logger.error(f"Falha ao exportar PDF para {path}: {exc}", exc_info=True)
                QMessageBox.critical(self, "Erro", f"Falha ao exportar PDF: {exc}")
                return
            QMessageBox.information(self, "Sucesso", "PDF exportado com sucesso.")

    def export_ficha_pdf(self):
        if not self.selected: return
        path = self._get_save_path("Salvar Ficha PDF", "PDF (*.pdf)")
        if path:
            try:
                export_individual_pdf(path, self.selected)
            except Exception as exc:
                logger.error(f"Falha ao exportar ficha em PDF para {path}: {exc}", exc_info=True)
                QMessageBox.critical(self, "Erro", f"Falha ao exportar ficha: {exc}")
                return
            QMessageBox.information(self, "Sucesso", "Ficha PDF gerada com sucesso.")

    def export_dashboard_pdf_clicked(self):
        path = self._get_save_path("Salvar PDF", "PDF (*.pdf)")
        if path:
            metrics = compute_metrics(self.filtered_records)
            pie, bar = self.dash_tab.export_images()
            chart_images = [img for img in [pie, bar] if img]
            kpi_lines = [
                f"Total de registros: {metrics['count_total']}",
                f"Total de mudas: {metrics['total_geral']:g}",
                f"Pendentes: {metrics['total_pendente']:g}",
                f"Compensadas: {metrics['total_compensado']:g}",
            ]
            try:
                export_dashboard_pdf(
                    path,
                    "Painel Geral",
                    kpi_lines,
                    self._build_filter_summary(),
                    chart_images,
                )
            except Exception as exc:
                logger.error(f"Falha ao exportar painel em PDF para {path}: {exc}", exc_info=True)
                QMessageBox.critical(self, "Erro", f"Falha ao exportar painel: {exc}")
                return
            QMessageBox.information(self, "Sucesso", "Relatório de Painel exportado.")

    def _get_save_path(self, title, filter):
        path, _ = QFileDialog.getSaveFileName(self, title, "", filter)
        return path

    def closeEvent(self, event):
        if not self._skip_close_discard_confirmation and not self.form_controller.confirm_discard_changes("fechar a janela"):
            event.ignore()
            return

        if self._startup_window_timer.isActive():
            self._startup_window_timer.stop()
        if self._initial_map_sync_timer.isActive():
            self._initial_map_sync_timer.stop()

        self.settings_controller.save_before_close()

        if hasattr(self, "support_controller"):
            self.support_controller.shutdown()

        if getattr(self, "geo_worker", None) is not None:
            try:
                self.geo_worker.progress_update.disconnect()
            except (TypeError, RuntimeError):
                pass
            try:
                self.geo_worker.finished_process.disconnect()
            except (TypeError, RuntimeError):
                pass
            if self.geo_worker.isRunning():
                self.geo_worker.stop()
                self.geo_worker.quit()
                self.geo_worker.wait(10000)
         
        # Graceful shutdown da thread do atualizador
        if hasattr(self, "_updater") and self._updater.isRunning():
            self._updater.requestInterruption()
            self._updater.quit()
            self._updater.wait(500)
            
        super().closeEvent(event)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.showMaximized()
    sys.exit(app.exec())
