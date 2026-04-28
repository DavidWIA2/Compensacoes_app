from datetime import date, datetime
from typing import Dict, List, Optional
from PySide6.QtCore import Qt, QUrl, QTimer, QDate, QUrlQuery
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton, 
    QLineEdit, QComboBox, QMessageBox, QCheckBox, QFileDialog, QDateEdit,
    QHeaderView, QDialogButtonBox, QTableWidget, QTableWidgetItem,
    QFormLayout, QPlainTextEdit,
    QAbstractItemView, QWidget
)
from app.application.use_cases.import_preview_presenter import (
    ImportPreviewPresentation,
    ImportPreviewPresenter,
    ImportPreviewRowView,
)
from app.application.use_cases.map_fullscreen_operations import MapFullscreenOperationsUseCases
from app.application.use_cases.map_interactions import MapInteractionsUseCases
from app.application.use_cases.operation_history_presenter import (
    OperationHistoryFilterState,
    OperationHistoryPresenter,
)
from app.application.use_cases.plantios_dialog_presenter import (
    PlantiosDialogPresenter,
)
from app.application.use_cases.table_fullscreen_filters import (
    TableFullscreenFilterState,
    TableFullscreenFiltersUseCases,
)
from app.application.use_cases.table_fullscreen_layout import (
    TableHeaderLayoutSnapshot,
    TableFullscreenLayoutUseCases,
)
from app.application.use_cases.map_rendering import MapRenderingUseCases
from app.models.display_columns import display_column_index
from app.services.tcra_excel_service import TcraWorkbookAnalysis
from app.services.tile_proxy_service import TileProxyService
from app.services.records_service import STANDARD_TIPO_OPTIONS
from app.services.tcra_report_service import TcraPdfExportOptions
from app.services.tcra_records_service import (
    STATUS_ARQUIVADO,
    STATUS_CUMPRIDO,
    STATUS_EM_ACOMPANHAMENTO,
    STATUS_PRAZO_VENCIDO,
    STATUS_RELATORIO_PENDENTE,
    normalize_status_label,
)
from app.ui.components.import_preview_dialog_support import (
    build_import_preview_button_plan,
    build_import_preview_row_values,
    resolve_import_preview_current_key,
    resolve_import_preview_target_index,
)
from app.ui.components.map_fullscreen_dialog_support import (
    build_fullscreen_current_points,
    build_fullscreen_heatmap_sync_view,
    run_fullscreen_map_script,
)
from app.ui.components.timer_utils import schedule_owned_single_shot
from app.ui.components.operation_history_dialog_support import (
    BACKUP_FILTER_OPTIONS,
    PERIOD_FILTER_OPTIONS,
    build_operation_history_filter_state_payload,
    build_operation_history_selection_state,
    date_to_qdate,
    load_operation_history_filter_state,
    persist_operation_history_filter_state,
    qdate_to_date,
    resolve_operation_history_current_event,
    resolve_operation_history_default_export_path,
    resolve_operation_history_target_index,
    write_operation_history_export,
)
from app.ui.components.plantios_dialog_support import (
    append_plantio_row,
    apply_plantio_row_view,
    build_plantios_row_action_state,
    read_plantio_rows_from_table,
    resolve_plantio_next_row_after_removal,
    resolve_plantio_selected_row,
    update_plantios_total_label,
)
from app.ui.components.table_fullscreen_dialog_support import (
    apply_fullscreen_filter_state_to_dialog,
    apply_fullscreen_filter_state_to_main,
    apply_fullscreen_preferred_widths,
    blocked_qt_signals,
    build_fullscreen_filter_state_from_dialog,
    build_fullscreen_filter_state_from_main,
    build_fullscreen_header_widths,
    capture_fullscreen_table_layout,
    resolve_fullscreen_primary_table,
    resolve_fullscreen_visible_columns,
    restore_fullscreen_table_layout,
)
from app.ui.components.widgets import CheckableComboBox, ClickableComboBox, MapBridge, DebugPage
from app.services.geocode_service import geocode_address
from app.services.mapbox_config import read_mapbox_usage, resolve_mapbox_access_token
from app.services.map_engine import resolve_map_engine_resource
from app.config import MAP_DEFAULT_BASE_LAYER
from app.services.plantio_service import clone_plantios
from app.utils.logger import get_logger

map_dialog_logger = get_logger("UI.MapDialog")


def _load_map_webengine_classes():
    from PySide6.QtWebChannel import QWebChannel
    from PySide6.QtWebEngineCore import QWebEngineSettings
    from PySide6.QtWebEngineWidgets import QWebEngineView

    return QWebEngineView, QWebChannel, QWebEngineSettings

TCRA_EVENT_PRESETS = (
    {
        "key": "personalizado",
        "label": "Personalizado",
        "tipo_evento": "",
        "status_resultante": "",
        "descricao": "",
    },
    {
        "key": "relatorio_entregue",
        "label": "Relatório entregue",
        "tipo_evento": "Relatório entregue",
        "status_resultante": STATUS_EM_ACOMPANHAMENTO,
        "descricao": "Relatório periódico protocolado e anexado ao acompanhamento.",
    },
    {
        "key": "vistoria",
        "label": "Vistoria",
        "tipo_evento": "Vistoria",
        "status_resultante": STATUS_EM_ACOMPANHAMENTO,
        "descricao": "Vistoria tecnica realizada no local do termo.",
    },
    {
        "key": "despacho",
        "label": "Despacho",
        "tipo_evento": "Despacho",
        "status_resultante": STATUS_EM_ACOMPANHAMENTO,
        "descricao": "Despacho ou manifestacao administrativa registrado.",
    },
    {
        "key": "prorrogacao",
        "label": "Prorrogacao",
        "tipo_evento": "Prorrogacao",
        "status_resultante": STATUS_EM_ACOMPANHAMENTO,
        "descricao": "Prazo do termo prorrogado por novo despacho.",
    },
    {
        "key": "cumprimento",
        "label": "Cumprimento",
        "tipo_evento": "Cumprimento",
        "status_resultante": STATUS_CUMPRIDO,
        "descricao": "Termo marcado como cumprido apos validacao administrativa.",
    },
    {
        "key": "arquivamento",
        "label": "Arquivamento",
        "tipo_evento": "Arquivamento",
        "status_resultante": STATUS_ARQUIVADO,
        "descricao": "Termo arquivado administrativamente.",
    },
)


class TcraPdfExportDialog(QDialog):
    def __init__(
        self,
        parent=None,
        *,
        options: TcraPdfExportOptions | None = None,
    ):
        super().__init__(parent)
        self._options = options if options is not None else TcraPdfExportOptions.empty_selection()
        self.setWindowTitle("Exportar PDF de TCRAs")
        self.resize(480, 410)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        title = QLabel("Escolha os blocos do relat\u00f3rio")
        title.setProperty("role", "section-title")
        layout.addWidget(title)

        subtitle = QLabel(
            "O cabe\u00e7alho e o rodap\u00e9 institucionais ser\u00e3o inclu\u00eddos automaticamente. "
            "Nenhum bloco vem pr\u00e9-selecionado para evitar um PDF polu\u00eddo."
        )
        subtitle.setWordWrap(True)
        subtitle.setObjectName("FormStateLabel")
        layout.addWidget(subtitle)

        checks_frame = QFrame(self)
        checks_layout = QVBoxLayout(checks_frame)
        checks_layout.setContentsMargins(10, 10, 10, 10)
        checks_layout.setSpacing(8)

        self.chk_summary = QCheckBox("Resumo executivo")
        self.chk_summary.setChecked(self._options.include_summary)
        checks_layout.addWidget(self.chk_summary)

        self.chk_current_records = QCheckBox("Recorte atual da tabela")
        self.chk_current_records.setChecked(self._options.include_current_records)
        checks_layout.addWidget(self.chk_current_records)

        self.chk_upcoming_reports = QCheckBox("Pr\u00f3ximos relat\u00f3rios")
        self.chk_upcoming_reports.setChecked(self._options.include_upcoming_reports)
        checks_layout.addWidget(self.chk_upcoming_reports)

        self.chk_quality_queue = QCheckBox("Qualidade cadastral")
        self.chk_quality_queue.setChecked(self._options.include_quality_queue)
        checks_layout.addWidget(self.chk_quality_queue)

        self.chk_critical_agenda = QCheckBox("Pend\u00eancias cr\u00edticas")
        self.chk_critical_agenda.setChecked(self._options.include_critical_agenda)
        checks_layout.addWidget(self.chk_critical_agenda)

        self.chk_agenda_7d = QCheckBox("Agenda de trabalho - 7 dias")
        self.chk_agenda_7d.setChecked(self._options.include_agenda_7d)
        checks_layout.addWidget(self.chk_agenda_7d)

        self.chk_agenda_30d = QCheckBox("Agenda de trabalho - 30 dias")
        self.chk_agenda_30d.setChecked(self._options.include_agenda_30d)
        checks_layout.addWidget(self.chk_agenda_30d)

        self.chk_inbox = QCheckBox("Inbox operacional")
        self.chk_inbox.setChecked(self._options.include_inbox)
        checks_layout.addWidget(self.chk_inbox)

        self._checkboxes = (
            self.chk_summary,
            self.chk_current_records,
            self.chk_upcoming_reports,
            self.chk_quality_queue,
            self.chk_critical_agenda,
            self.chk_agenda_7d,
            self.chk_agenda_30d,
            self.chk_inbox,
        )

        layout.addWidget(checks_frame)

        quick_actions = QHBoxLayout()
        quick_actions.setSpacing(6)
        self.btn_select_recommended = QPushButton("Resumo + tabela")
        self.btn_select_recommended.setProperty("kind", "chip-quiet")
        self.btn_select_all = QPushButton("Selecionar tudo")
        self.btn_select_all.setProperty("kind", "chip-quiet")
        self.btn_clear_selection = QPushButton("Limpar seleção")
        self.btn_clear_selection.setProperty("kind", "secondary")
        quick_actions.addWidget(self.btn_select_recommended)
        quick_actions.addWidget(self.btn_select_all)
        quick_actions.addWidget(self.btn_clear_selection)
        quick_actions.addStretch(1)
        layout.addLayout(quick_actions)

        self.warning_label = QLabel("")
        self.warning_label.setWordWrap(True)
        self.warning_label.setObjectName("FormStateLabel")
        self.warning_label.setStyleSheet("color: #C44747;")
        layout.addWidget(self.warning_label)

        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        ok_button = self.button_box.button(QDialogButtonBox.Ok)
        if ok_button is not None:
            ok_button.setText("Gerar PDF")
        cancel_button = self.button_box.button(QDialogButtonBox.Cancel)
        if cancel_button is not None:
            cancel_button.setText("Cancelar")
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        for checkbox in self._checkboxes:
            checkbox.toggled.connect(self._refresh_accept_state)
        self.btn_select_recommended.clicked.connect(self._select_recommended)
        self.btn_select_all.clicked.connect(self._select_all)
        self.btn_clear_selection.clicked.connect(self._clear_selection)

        self._refresh_accept_state()

    def _apply_options(self, options: TcraPdfExportOptions) -> None:
        for checkbox, checked in zip(
            self._checkboxes,
            (
                options.include_summary,
                options.include_current_records,
                options.include_upcoming_reports,
                options.include_quality_queue,
                options.include_critical_agenda,
                options.include_agenda_7d,
                options.include_agenda_30d,
                options.include_inbox,
            ),
        ):
            checkbox.blockSignals(True)
            checkbox.setChecked(checked)
            checkbox.blockSignals(False)
        self._refresh_accept_state()

    def _select_recommended(self) -> None:
        self._apply_options(
            TcraPdfExportOptions(
                include_summary=True,
                include_current_records=True,
                include_upcoming_reports=False,
                include_quality_queue=False,
                include_critical_agenda=False,
                include_agenda_7d=False,
                include_agenda_30d=False,
                include_inbox=False,
            )
        )

    def _select_all(self) -> None:
        self._apply_options(
            TcraPdfExportOptions(
                include_summary=True,
                include_current_records=True,
                include_upcoming_reports=True,
                include_quality_queue=True,
                include_critical_agenda=True,
                include_agenda_7d=True,
                include_agenda_30d=True,
                include_inbox=True,
            )
        )

    def _clear_selection(self) -> None:
        self._apply_options(TcraPdfExportOptions.empty_selection())

    def _refresh_accept_state(self) -> None:
        has_any = self.selected_options().has_any_section()
        ok_button = self.button_box.button(QDialogButtonBox.Ok)
        if ok_button is not None:
            ok_button.setEnabled(has_any)
        self.warning_label.setText("" if has_any else "Selecione ao menos um bloco para montar o PDF.")

    def selected_options(self) -> TcraPdfExportOptions:
        return TcraPdfExportOptions(
            include_summary=self.chk_summary.isChecked(),
            include_current_records=self.chk_current_records.isChecked(),
            include_upcoming_reports=self.chk_upcoming_reports.isChecked(),
            include_quality_queue=self.chk_quality_queue.isChecked(),
            include_critical_agenda=self.chk_critical_agenda.isChecked(),
            include_agenda_7d=self.chk_agenda_7d.isChecked(),
            include_agenda_30d=self.chk_agenda_30d.isChecked(),
            include_inbox=self.chk_inbox.isChecked(),
        )


class ImportPreviewDialog(QDialog):
    def __init__(self, parent, analysis):
        super().__init__(parent)
        self.analysis = analysis
        self.presenter = ImportPreviewPresenter()
        self.presentation: ImportPreviewPresentation = self.presenter.build_presentation(analysis)
        self._rows: tuple[ImportPreviewRowView, ...] = self.presentation.rows
        self._visible_rows: list[ImportPreviewRowView] = []
        self.setWindowTitle("Preflight de Importação")
        self.resize(960, 540)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self.lbl_summary = QLabel(self.presentation.summary_text)
        self.lbl_summary.setWordWrap(True)
        layout.addWidget(self.lbl_summary)

        self.lbl_hint = QLabel(self.presentation.hint_text)
        self.lbl_hint.setWordWrap(True)
        self.lbl_hint.setObjectName("FormStateLabel")
        layout.addWidget(self.lbl_hint)

        self.lbl_breakdown = QLabel(self.presentation.breakdown_text)
        self.lbl_breakdown.setWordWrap(True)
        self.lbl_breakdown.setObjectName("FormStateLabel")
        layout.addWidget(self.lbl_breakdown)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        self.filter_status = ClickableComboBox(self)
        self.filter_status.addItems(list(self.presentation.status_options))
        self.search_input = QLineEdit(self)
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setPlaceholderText("Filtrar por UID, Av. Tec. ou detalhe...")
        self.lbl_visible = QLabel(self)
        self.lbl_visible.setObjectName("FormStateLabel")
        filter_row.addWidget(QLabel("Status:"))
        filter_row.addWidget(self.filter_status)
        filter_row.addWidget(QLabel("Busca:"))
        filter_row.addWidget(self.search_input, 1)
        filter_row.addWidget(self.lbl_visible)
        layout.addLayout(filter_row)

        self.table = QTableWidget(0, 5, self)
        self.table.setHorizontalHeaderLabels(["Linha", "UID", "Av. Tec.", "Status", "Detalhe"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        layout.addWidget(self.table, 1)

        self.filter_status.currentTextChanged.connect(self._apply_filters)
        self.search_input.textChanged.connect(self._apply_filters)
        self._apply_filters()

        button_plan = build_import_preview_button_plan(total_invalid=analysis.total_invalid)
        self.button_box = QDialogButtonBox(self)
        if not button_plan.allows_import:
            self.button_box.setStandardButtons(QDialogButtonBox.Close)
            self.button_box.rejected.connect(self.reject)
        else:
            self.button_box.setStandardButtons(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            ok_button = self.button_box.button(QDialogButtonBox.Ok)
            if ok_button is not None:
                ok_button.setText(button_plan.accept_label)
            self.button_box.accepted.connect(self.accept)
            self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def _insert_table_row(self, row_data: ImportPreviewRowView):
        row = self.table.rowCount()
        self.table.insertRow(row)
        values = build_import_preview_row_values(row_data)
        for column, value in enumerate(values):
            self.table.setItem(row, column, QTableWidgetItem(value))

    def _apply_filters(self, *_args):
        current_key = resolve_import_preview_current_key(
            self._visible_rows,
            current_row=self.table.currentRow(),
        )

        self.table.setRowCount(0)
        self._visible_rows = self.presenter.filter_rows(
            self._rows,
            selected_status=self.filter_status.currentText(),
            search_text=self.search_input.text(),
        )
        for row_data in self._visible_rows:
            self._insert_table_row(row_data)

        self.lbl_visible.setText(
            self.presenter.visible_label(visible_count=len(self._visible_rows), total_count=len(self._rows))
        )
        if not self._visible_rows:
            return

        target_index = resolve_import_preview_target_index(
            self._visible_rows,
            current_key=current_key,
        )
        self.table.setCurrentCell(target_index, 0)


class OperationHistoryDialog(QDialog):
    def __init__(self, parent, events):
        super().__init__(parent)
        self.events = list(events)
        self.presenter = OperationHistoryPresenter()
        self.visible_events = []
        self.selected_event = None
        self.restore_requested = False
        self._restoring_filters = False
        self._default_from_date, self._default_to_date = self._resolve_default_date_range()

        self.setWindowTitle("Historico de Operacoes")
        self.resize(980, 560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self.lbl_hint = QLabel(
            "Revise as operacoes registradas para esta planilha. Voce pode inspecionar os detalhes e restaurar um snapshot anterior."
        )
        self.lbl_hint.setWordWrap(True)
        layout.addWidget(self.lbl_hint)

        self.lbl_summary = QLabel(self)
        self.lbl_summary.setWordWrap(True)
        self.lbl_summary.setObjectName("FormStateLabel")
        layout.addWidget(self.lbl_summary)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        self.filter_action = ClickableComboBox(self)
        self.filter_action.addItems(list(self.presenter.build_action_items(self.events)))
        self.filter_backup = ClickableComboBox(self)
        self.filter_backup.addItems(list(BACKUP_FILTER_OPTIONS))
        self.filter_period = ClickableComboBox(self)
        self.filter_period.addItems(list(PERIOD_FILTER_OPTIONS))
        self.search_input = QLineEdit(self)
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setPlaceholderText("Filtrar por resumo, acao, UID ou metadados...")
        filter_row.addWidget(QLabel("Acao:"))
        filter_row.addWidget(self.filter_action)
        filter_row.addWidget(QLabel("Backup:"))
        filter_row.addWidget(self.filter_backup)
        filter_row.addWidget(QLabel("Periodo:"))
        filter_row.addWidget(self.filter_period)
        filter_row.addWidget(QLabel("Busca:"))
        filter_row.addWidget(self.search_input, 1)
        layout.addLayout(filter_row)

        range_row = QHBoxLayout()
        range_row.setSpacing(8)
        self.date_from = QDateEdit(self)
        self.date_from.setCalendarPopup(True)
        self.date_from.setDisplayFormat("dd/MM/yyyy")
        self.date_from.setDate(self._default_from_date)
        self.date_to = QDateEdit(self)
        self.date_to.setCalendarPopup(True)
        self.date_to.setDisplayFormat("dd/MM/yyyy")
        self.date_to.setDate(self._default_to_date)
        self.btn_clear_filters = QPushButton("Limpar")
        self.btn_clear_filters.setProperty("kind", "secondary")
        self.lbl_visible = QLabel(self)
        self.lbl_visible.setObjectName("FormStateLabel")
        range_row.addWidget(QLabel("De:"))
        range_row.addWidget(self.date_from)
        range_row.addWidget(QLabel("Ate:"))
        range_row.addWidget(self.date_to)
        range_row.addWidget(self.btn_clear_filters)
        range_row.addWidget(self.lbl_visible, 1)
        layout.addLayout(range_row)

        self.table = QTableWidget(0, 4, self)
        self.table.setHorizontalHeaderLabels(["Data/Hora", "Acao", "Resumo", "Backup"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        layout.addWidget(self.table, 1)

        self.details = QPlainTextEdit(self)
        self.details.setReadOnly(True)
        self.details.setPlaceholderText("Selecione uma operacao para ver os detalhes.")
        layout.addWidget(self.details, 1)

        buttons_row = QHBoxLayout()
        buttons_row.addStretch(1)
        self.btn_export = QPushButton("Exportar Historico")
        self.btn_export.setProperty("kind", "secondary")
        self.btn_open_backup = QPushButton("Abrir Backup")
        self.btn_open_backup.setProperty("kind", "secondary")
        self.btn_restore = QPushButton("Restaurar Selecionado")
        self.btn_restore.setProperty("kind", "danger")
        self.btn_close = QPushButton("Fechar")
        self.btn_close.setProperty("kind", "secondary")
        buttons_row.addWidget(self.btn_export)
        buttons_row.addWidget(self.btn_open_backup)
        buttons_row.addWidget(self.btn_restore)
        buttons_row.addWidget(self.btn_close)
        layout.addLayout(buttons_row)

        self.btn_export.clicked.connect(self.export_history)
        self.btn_open_backup.clicked.connect(self._open_selected_backup)
        self.btn_restore.clicked.connect(self._request_restore)
        self.btn_close.clicked.connect(self.reject)
        self.btn_clear_filters.clicked.connect(self._clear_filters)
        self.table.itemSelectionChanged.connect(self._refresh_selection)
        self.filter_action.currentTextChanged.connect(self._apply_filters)
        self.filter_backup.currentTextChanged.connect(self._apply_filters)
        self.filter_period.currentTextChanged.connect(self._on_period_filter_changed)
        self.search_input.textChanged.connect(self._apply_filters)
        self.date_from.dateChanged.connect(self._apply_filters)
        self.date_to.dateChanged.connect(self._apply_filters)

        self._restore_filter_state()
        self._on_period_filter_changed(self.filter_period.currentText())
        self._apply_filters()
        self._refresh_selection()

    def _insert_event_row(self, event):
        row = self.table.rowCount()
        self.table.insertRow(row)
        row_view = self.presenter.build_row_view(event)
        values = [row_view.timestamp, row_view.action, row_view.summary, row_view.backup_status]
        for column, value in enumerate(values):
            self.table.setItem(row, column, QTableWidgetItem(value))

    def _apply_filters(self, *_args):
        current_event_id = getattr(self.selected_event, "event_id", "")
        self.table.setRowCount(0)
        self.visible_events = self.presenter.filter_events(self.events, state=self._filter_state())
        for event in self.visible_events:
            self._insert_event_row(event)

        self.lbl_visible.setText(
            self.presenter.build_visible_label(visible_events=self.visible_events, total_events=len(self.events))
        )
        self._update_summary_label()

        if not self.visible_events:
            self.selected_event = None
            self._refresh_selection()
            return

        target_index = resolve_operation_history_target_index(
            self.visible_events,
            current_event_id=current_event_id,
        )
        self.table.setCurrentCell(target_index, 0)
        self._persist_filter_state()

    def _current_event(self):
        return resolve_operation_history_current_event(
            self.visible_events,
            current_row=self.table.currentRow(),
        )

    def _resolve_default_date_range(self) -> tuple[QDate, QDate]:
        from_date, to_date = self.presenter.resolve_default_date_range(self.events)
        return date_to_qdate(from_date), date_to_qdate(to_date)

    def _update_summary_label(self):
        self.lbl_summary.setText(
            self.presenter.build_summary_text(
                visible_events=self.visible_events,
                state=self._filter_state(),
            )
        )

    def _persist_filter_state(self):
        if self._restoring_filters:
            return
        persist_operation_history_filter_state(
            self.parent(),
            build_operation_history_filter_state_payload(self._filter_state()),
        )

    def _restore_filter_state(self):
        state = load_operation_history_filter_state(self.parent())
        action = str(state.get("action", "Todas") or "Todas")
        backup = str(state.get("backup", "Todos") or "Todos")
        period = str(state.get("period", "Todos") or "Todos")
        date_from = QDate.fromString(
            str(state.get("date_from", "") or ""),
            Qt.DateFormat.ISODate,
        )
        date_to = QDate.fromString(
            str(state.get("date_to", "") or ""),
            Qt.DateFormat.ISODate,
        )
        search = str(state.get("search", "") or "")

        self._restoring_filters = True
        try:
            action_index = self.filter_action.findText(action)
            if action_index >= 0:
                self.filter_action.setCurrentIndex(action_index)
            backup_index = self.filter_backup.findText(backup)
            if backup_index >= 0:
                self.filter_backup.setCurrentIndex(backup_index)
            period_index = self.filter_period.findText(period)
            if period_index >= 0:
                self.filter_period.setCurrentIndex(period_index)
            if date_from.isValid():
                self.date_from.setDate(date_from)
            if date_to.isValid():
                self.date_to.setDate(date_to)
            self.search_input.setText(search)
        finally:
            self._restoring_filters = False

    def _clear_filters(self):
        self.filter_action.setCurrentText("Todas")
        self.filter_backup.setCurrentText("Todos")
        self.filter_period.setCurrentText("Todos")
        self.date_from.setDate(self._default_from_date)
        self.date_to.setDate(self._default_to_date)
        self.search_input.clear()

    def _current_filter_state(self) -> dict:
        return self._filter_state().to_dict()

    def _serialize_event(self, event) -> dict:
        return self.presenter.serialize_event(event)

    def _default_export_path(self) -> str:
        return resolve_operation_history_default_export_path(self.parent())

    def export_history(self):
        if not self.visible_events:
            QMessageBox.information(self, "Histórico de Operações", "Não há operações visíveis para exportar.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Exportar Historico de Operacoes",
            self._default_export_path(),
            "JSON (*.json)",
        )
        if not path:
            return

        payload = self.presenter.build_export_payload(
            exported_at=datetime.now().isoformat(),
            filter_state=self._filter_state(),
            total_events=len(self.events),
            visible_events=self.visible_events,
            summary_text=self.lbl_summary.text(),
        )

        write_operation_history_export(path, payload)

        parent = self.parent()
        if parent is not None and hasattr(parent, "settings_controller"):
            parent.settings_controller.save_last_export_dir(path)

        QMessageBox.information(
            self,
            "Historico de Operacoes",
            f"Historico exportado com sucesso para:\n{path}",
        )

    def closeEvent(self, event):
        self._persist_filter_state()
        super().closeEvent(event)

    def _on_period_filter_changed(self, _value: str):
        is_custom = self.filter_period.currentText() == "Personalizado"
        self.date_from.setEnabled(is_custom)
        self.date_to.setEnabled(is_custom)
        self._apply_filters()

    def _refresh_selection(self):
        selection_state = build_operation_history_selection_state(self.presenter, self._current_event())
        self.selected_event = selection_state.event
        self.btn_open_backup.setEnabled(selection_state.can_open_backup)
        self.btn_restore.setEnabled(selection_state.can_restore)
        self.details.setPlainText(selection_state.details_text)

    def _open_selected_backup(self):
        event = self._current_event()
        selection_state = build_operation_history_selection_state(self.presenter, event)
        if selection_state.event is None or not selection_state.can_open_backup:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(getattr(selection_state.event, "backup_path", "") or "")))

    def _request_restore(self):
        event = self._current_event()
        selection_state = build_operation_history_selection_state(self.presenter, event)
        if selection_state.event is None or not selection_state.can_restore:
            return
        self.selected_event = selection_state.event
        self.restore_requested = True
        self.accept()

    def _filter_state(self) -> OperationHistoryFilterState:
        return OperationHistoryFilterState(
            action=self.filter_action.currentText(),
            backup=self.filter_backup.currentText(),
            period=self.filter_period.currentText(),
            date_from=qdate_to_date(self.date_from.date()),
            date_to=qdate_to_date(self.date_to.date()),
            search=self.search_input.text(),
        )


class PlantioRowEditorDialog(QDialog):
    def __init__(self, parent, endereco="", qtd_mudas=""):
        super().__init__(parent)
        self.setWindowTitle("Editar Plantio")
        self.resize(520, 170)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)

        self.in_endereco = QLineEdit(str(endereco or ""))
        self.in_qtd_mudas = QLineEdit(str(qtd_mudas or ""))

        form.addRow("Endereço de Plantio:", self.in_endereco)
        form.addRow("Qtd. mudas:", self.in_qtd_mudas)
        layout.addLayout(form)

        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def values(self):
        return self.in_endereco.text().strip(), self.in_qtd_mudas.text().strip()


class TcraEventoEditorDialog(QDialog):
    def __init__(
        self,
        parent,
        *,
        data_evento: str = "",
        tipo_evento: str = "",
        descricao: str = "",
        prazo_resultante: str = "",
        status_resultante: str = "",
        protocolo: str = "",
        documento_ref: str = "",
        preset_key: str = "",
        apply_preset_on_start: bool = False,
    ):
        super().__init__(parent)
        self.setWindowTitle("Editar Evento do TCRA")
        self.resize(620, 320)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)

        self.combo_preset = QComboBox(self)
        for preset in TCRA_EVENT_PRESETS:
            self.combo_preset.addItem(str(preset["label"]), str(preset["key"]))
        self.chk_apply_preset = QCheckBox("Preencher automaticamente os campos do preset")
        self.chk_apply_preset.setChecked(True)
        self.in_data_evento = QLineEdit(str(data_evento or ""))
        self.in_data_evento.setPlaceholderText("dd/mm/aaaa")
        self.in_tipo_evento = QLineEdit(str(tipo_evento or ""))
        self.in_status_resultante = QLineEdit(str(status_resultante or ""))
        self.in_prazo_resultante = QLineEdit(str(prazo_resultante or ""))
        self.in_prazo_resultante.setPlaceholderText("dd/mm/aaaa")
        self.in_protocolo = QLineEdit(str(protocolo or ""))
        self.in_protocolo.setPlaceholderText("Número de protocolo, SEI ou referência administrativa")
        self.in_documento_ref = QLineEdit(str(documento_ref or ""))
        self.in_documento_ref.setPlaceholderText("Caminho, link ou identificação do documento")
        document_row = QHBoxLayout()
        document_row.setContentsMargins(0, 0, 0, 0)
        self.btn_choose_document = QPushButton("Escolher arquivo")
        self.btn_choose_document.setProperty("kind", "chip-quiet")
        document_row.addWidget(self.in_documento_ref, 1)
        document_row.addWidget(self.btn_choose_document)
        self.in_descricao = QPlainTextEdit(str(descricao or ""))
        self.in_descricao.setTabChangesFocus(True)
        self.in_descricao.setMinimumHeight(120)

        form.addRow("Preset:", self.combo_preset)
        form.addRow("", self.chk_apply_preset)
        form.addRow("Data do evento:", self.in_data_evento)
        form.addRow("Tipo do evento:", self.in_tipo_evento)
        form.addRow("Status resultante:", self.in_status_resultante)
        form.addRow("Prazo resultante:", self.in_prazo_resultante)
        form.addRow("Protocolo:", self.in_protocolo)
        form.addRow("Documento/link:", document_row)
        form.addRow("Descricao:", self.in_descricao)
        layout.addLayout(form)

        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        resolved_preset_key = str(preset_key or self._resolve_preset_key(tipo_evento=tipo_evento, status_resultante=status_resultante))
        preset_index = self.combo_preset.findData(resolved_preset_key)
        if preset_index >= 0:
            self.combo_preset.setCurrentIndex(preset_index)
        self.combo_preset.currentIndexChanged.connect(self._apply_selected_preset)
        self.btn_choose_document.clicked.connect(self._choose_document_ref)
        if apply_preset_on_start and resolved_preset_key and resolved_preset_key != "personalizado":
            self._apply_selected_preset()

    @staticmethod
    def _resolve_preset_key(*, tipo_evento: str, status_resultante: str) -> str:
        normalized_tipo = str(tipo_evento or "").strip().upper()
        normalized_status = normalize_status_label(status_resultante)
        if "RELATORIO" in normalized_tipo:
            return "relatorio_entregue"
        if "VISTOR" in normalized_tipo:
            return "vistoria"
        if "DESPACH" in normalized_tipo:
            return "despacho"
        if "PRORROG" in normalized_tipo:
            return "prorrogacao"
        if "ARQUIV" in normalized_tipo or normalized_status == STATUS_ARQUIVADO:
            return "arquivamento"
        if "CUMPR" in normalized_tipo or normalized_status == STATUS_CUMPRIDO:
            return "cumprimento"
        return "personalizado"

    def _apply_selected_preset(self):
        if not self.chk_apply_preset.isChecked():
            return
        preset = next(
            (item for item in TCRA_EVENT_PRESETS if str(item["key"]) == str(self.combo_preset.currentData() or "")),
            None,
        )
        if not preset or str(preset["key"]) == "personalizado":
            return
        if not self.in_data_evento.text().strip():
            self.in_data_evento.setText(date.today().strftime("%d/%m/%Y"))
        self.in_tipo_evento.setText(str(preset["tipo_evento"]))
        self.in_status_resultante.setText(str(preset["status_resultante"]))
        self.in_descricao.setPlainText(str(preset["descricao"]))

    def _choose_document_ref(self):
        path, _selected_filter = QFileDialog.getOpenFileName(self, "Selecionar documento do evento", "", "Todos os arquivos (*.*)")
        if path:
            self.in_documento_ref.setText(path)

    def values(self):
        return {
            "preset_key": str(self.combo_preset.currentData() or ""),
            "data_evento": self.in_data_evento.text().strip(),
            "tipo_evento": self.in_tipo_evento.text().strip(),
            "descricao": self.in_descricao.toPlainText().strip(),
            "prazo_resultante": self.in_prazo_resultante.text().strip(),
            "status_resultante": self.in_status_resultante.text().strip(),
            "protocolo": self.in_protocolo.text().strip(),
            "documento_ref": self.in_documento_ref.text().strip(),
        }


class TcraBulkActionDialog(QDialog):
    def __init__(self, parent, *, selected_count: int, today: date | None = None):
        super().__init__(parent)
        self.setWindowTitle("Acao em lote para TCRAs")
        self.resize(560, 280)
        self._today = today or date.today()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self.lbl_hint = QLabel(
            f"Aplicar a mesma acao em {int(selected_count)} TCRA(s) selecionado(s)."
        )
        self.lbl_hint.setWordWrap(True)
        layout.addWidget(self.lbl_hint)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)

        self.combo_action = QComboBox(self)
        self.combo_action.addItem("Atualizar status", "status")
        self.combo_action.addItem("Definir responsavel", "responsavel")
        self.combo_action.addItem("Definir orgao", "orgao")
        self.combo_action.addItem("Definir proximo relatorio", "proximo_relatorio")
        self.combo_action.addItem("Registrar evento rapido", "evento")

        self.combo_status = QComboBox(self)
        self.combo_status.setEditable(True)
        self.combo_status.addItems(
            [
                STATUS_EM_ACOMPANHAMENTO,
                STATUS_RELATORIO_PENDENTE,
                STATUS_PRAZO_VENCIDO,
                STATUS_CUMPRIDO,
                STATUS_ARQUIVADO,
            ]
        )

        self.in_text = QLineEdit(self)
        self.in_text.setPlaceholderText("Informe o novo valor")

        self.in_date = QLineEdit(self)
        self.in_date.setPlaceholderText("dd/mm/aaaa")

        self.combo_event_preset = QComboBox(self)
        for preset in TCRA_EVENT_PRESETS:
            if str(preset.get("key") or "") == "personalizado":
                continue
            self.combo_event_preset.addItem(str(preset.get("label") or ""), str(preset.get("key") or ""))

        self.in_event_date = QLineEdit(self._today.strftime("%d/%m/%Y"))
        self.in_event_date.setPlaceholderText("dd/mm/aaaa")
        self.in_event_deadline = QLineEdit(self)
        self.in_event_deadline.setPlaceholderText("dd/mm/aaaa")
        self.in_event_protocol = QLineEdit(self)
        self.in_event_protocol.setPlaceholderText("Opcional")
        self.in_event_document = QLineEdit(self)
        self.in_event_document.setPlaceholderText("Opcional")

        form.addRow("Acao:", self.combo_action)
        form.addRow("Status:", self.combo_status)
        form.addRow("Valor textual:", self.in_text)
        form.addRow("Data:", self.in_date)
        form.addRow("Preset de evento:", self.combo_event_preset)
        form.addRow("Data do evento:", self.in_event_date)
        form.addRow("Prazo resultante:", self.in_event_deadline)
        form.addRow("Protocolo:", self.in_event_protocol)
        form.addRow("Documento/link:", self.in_event_document)
        layout.addLayout(form)

        self.lbl_mode_hint = QLabel(self)
        self.lbl_mode_hint.setWordWrap(True)
        self.lbl_mode_hint.setObjectName("FormStateLabel")
        layout.addWidget(self.lbl_mode_hint)

        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        self.combo_action.currentIndexChanged.connect(self._refresh_mode)
        self._refresh_mode()

    def _refresh_mode(self):
        action = str(self.combo_action.currentData() or "")
        self.combo_status.setVisible(action == "status")
        self.in_text.setVisible(action in {"responsavel", "orgao"})
        self.in_date.setVisible(action == "proximo_relatorio")
        self.combo_event_preset.setVisible(action == "evento")
        self.in_event_date.setVisible(action == "evento")
        self.in_event_deadline.setVisible(action == "evento")
        self.in_event_protocol.setVisible(action == "evento")
        self.in_event_document.setVisible(action == "evento")

        if action == "status":
            self.lbl_mode_hint.setText("Atualiza o status operacional informado dos termos selecionados.")
        elif action == "responsavel":
            self.lbl_mode_hint.setText("Define o mesmo responsavel de execucao para todos os termos selecionados.")
        elif action == "orgao":
            self.lbl_mode_hint.setText("Define o mesmo orgao de acompanhamento para todos os termos selecionados.")
        elif action == "proximo_relatorio":
            self.lbl_mode_hint.setText("Substitui a data do proximo relatorio do grupo selecionado.")
        else:
            self.lbl_mode_hint.setText(
                "Registra o mesmo evento rapido em todos os termos selecionados, atualizando status e prazos quando o preset indicar."
            )

    def values(self) -> dict[str, str]:
        return {
            "action": str(self.combo_action.currentData() or ""),
            "status": self.combo_status.currentText().strip(),
            "text_value": self.in_text.text().strip(),
            "date_value": self.in_date.text().strip(),
            "event_preset": str(self.combo_event_preset.currentData() or ""),
            "event_date": self.in_event_date.text().strip(),
            "event_deadline": self.in_event_deadline.text().strip(),
            "event_protocol": self.in_event_protocol.text().strip(),
            "event_document": self.in_event_document.text().strip(),
        }


class CompensacaoBulkActionDialog(QDialog):
    def __init__(self, parent, *, selected_count: int, microbacia_options: list[str] | None = None):
        super().__init__(parent)
        self.setWindowTitle("Ação em lote para Compensações")
        self.resize(540, 260)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self.lbl_hint = QLabel(
            f"Aplicar a mesma ação em {int(selected_count)} registro(s) selecionado(s)."
        )
        self.lbl_hint.setWordWrap(True)
        layout.addWidget(self.lbl_hint)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)

        self.combo_action = QComboBox(self)
        self.combo_action.addItem("Definir tipo", "tipo")
        self.combo_action.addItem("Definir microbacia", "microbacia")
        self.combo_action.addItem("Definir caixa", "caixa")
        self.combo_action.addItem("Marcar compensado", "compensado_true")
        self.combo_action.addItem("Desmarcar compensado", "compensado_false")
        self.combo_action.addItem("Marcar arquivado", "arquivado_true")
        self.combo_action.addItem("Desmarcar arquivado", "arquivado_false")

        self.combo_tipo = QComboBox(self)
        self.combo_tipo.addItems(list(STANDARD_TIPO_OPTIONS))

        self.combo_microbacia = QComboBox(self)
        self.combo_microbacia.setEditable(True)
        self.combo_microbacia.addItem("")
        for option in microbacia_options or []:
            text = str(option or "").strip()
            if text and self.combo_microbacia.findText(text) < 0:
                self.combo_microbacia.addItem(text)

        self.in_caixa = QLineEdit(self)
        self.in_caixa.setClearButtonEnabled(True)
        self.in_caixa.setPlaceholderText("Informe a caixa desejada")

        self.action_label = QLabel("Ação:")
        self.tipo_label = QLabel("Tipo:")
        self.microbacia_label = QLabel("Microbacia:")
        self.caixa_label = QLabel("Caixa:")
        form.addRow(self.action_label, self.combo_action)
        form.addRow(self.tipo_label, self.combo_tipo)
        form.addRow(self.microbacia_label, self.combo_microbacia)
        form.addRow(self.caixa_label, self.in_caixa)
        layout.addLayout(form)

        self.lbl_mode_hint = QLabel(self)
        self.lbl_mode_hint.setWordWrap(True)
        self.lbl_mode_hint.setObjectName("FormStateLabel")
        layout.addWidget(self.lbl_mode_hint)

        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        self.combo_action.currentIndexChanged.connect(self._refresh_mode)
        self._refresh_mode()

    def _refresh_mode(self):
        action = str(self.combo_action.currentData() or "")
        show_tipo = action == "tipo"
        show_microbacia = action == "microbacia"
        show_caixa = action == "caixa"
        self.tipo_label.setVisible(show_tipo)
        self.combo_tipo.setVisible(show_tipo)
        self.microbacia_label.setVisible(show_microbacia)
        self.combo_microbacia.setVisible(show_microbacia)
        self.caixa_label.setVisible(show_caixa)
        self.in_caixa.setVisible(show_caixa)

        if action == "tipo":
            self.lbl_mode_hint.setText("Atualiza o tipo do grupo selecionado e aplica a regra automática de caixa para Ofício.")
        elif action == "microbacia":
            self.lbl_mode_hint.setText("Preenche a mesma microbacia para todos os registros selecionados.")
        elif action == "caixa":
            self.lbl_mode_hint.setText("Substitui a caixa atual do recorte selecionado pelo valor informado.")
        elif action == "compensado_true":
            self.lbl_mode_hint.setText("Marca todos os registros selecionados como compensados.")
        elif action == "compensado_false":
            self.lbl_mode_hint.setText("Remove a marcação de compensado do grupo selecionado.")
        elif action == "arquivado_true":
            self.lbl_mode_hint.setText("Marca todos os registros selecionados como arquivados.")
        else:
            self.lbl_mode_hint.setText("Remove o status Arquivado do grupo selecionado quando a caixa atual estiver nesse estado.")

    def values(self) -> dict[str, object]:
        action = str(self.combo_action.currentData() or "")
        if action == "compensado_true":
            return {"action": "compensado", "checked": True}
        if action == "compensado_false":
            return {"action": "compensado", "checked": False}
        if action == "arquivado_true":
            return {"action": "arquivado", "checked": True}
        if action == "arquivado_false":
            return {"action": "arquivado", "checked": False}
        return {
            "action": action,
            "tipo": self.combo_tipo.currentText().strip(),
            "microbacia": self.combo_microbacia.currentText().strip(),
            "caixa": self.in_caixa.text().strip(),
        }


class TcraImportPreviewDialog(QDialog):
    def __init__(self, parent, analysis: TcraWorkbookAnalysis):
        super().__init__(parent)
        self.analysis = analysis
        self._visible_issues = list(analysis.issues)
        self.setWindowTitle("Revisão da Importação de TCRAs")
        self.resize(920, 520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self.lbl_summary = QLabel("\n".join(analysis.summary_lines()))
        self.lbl_summary.setWordWrap(True)
        layout.addWidget(self.lbl_summary)

        self.lbl_hint = QLabel(
            "Revise as linhas com aviso antes de substituir o conjunto atual de TCRAs no banco local."
        )
        self.lbl_hint.setWordWrap(True)
        self.lbl_hint.setObjectName("FormStateLabel")
        layout.addWidget(self.lbl_hint)

        filters_layout = QHBoxLayout()
        filters_layout.setSpacing(8)
        self.filter_severity = ClickableComboBox(self)
        self.filter_severity.addItems(["Todas", "warning", "info"])
        self.search_input = QLineEdit(self)
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setPlaceholderText("Filtrar por codigo ou mensagem do aviso...")
        self.lbl_visible = QLabel(self)
        self.lbl_visible.setObjectName("FormStateLabel")
        filters_layout.addWidget(QLabel("Severidade:"))
        filters_layout.addWidget(self.filter_severity)
        filters_layout.addWidget(QLabel("Busca:"))
        filters_layout.addWidget(self.search_input, 1)
        filters_layout.addWidget(self.lbl_visible)
        layout.addLayout(filters_layout)

        self.table = QTableWidget(0, 4, self)
        self.table.setHorizontalHeaderLabels(["Linha", "Severidade", "Codigo", "Mensagem"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        layout.addWidget(self.table, 1)

        self.filter_severity.currentTextChanged.connect(self._apply_filters)
        self.search_input.textChanged.connect(self._apply_filters)
        self._apply_filters()

        self.button_box = QDialogButtonBox(self)
        if analysis.importable_count <= 0:
            self.button_box.setStandardButtons(QDialogButtonBox.Close)
            self.button_box.rejected.connect(self.reject)
        else:
            self.button_box.setStandardButtons(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            ok_button = self.button_box.button(QDialogButtonBox.Ok)
            if ok_button is not None:
                ok_button.setText("Importar")
            self.button_box.accepted.connect(self.accept)
            self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def _matches_filters(self, issue) -> bool:
        selected_severity = str(self.filter_severity.currentText() or "Todas").strip().lower()
        if selected_severity != "todas" and str(issue.severity or "").strip().lower() != selected_severity:
            return False

        query = str(self.search_input.text() or "").strip().lower()
        if not query:
            return True
        payload = " ".join([str(issue.code or ""), str(issue.message or "")]).lower()
        return query in payload

    def _apply_filters(self, *_args):
        self._visible_issues = [issue for issue in self.analysis.issues if self._matches_filters(issue)]
        self.table.setRowCount(0)
        for issue in self._visible_issues:
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = [
                str(issue.row_index),
                str(issue.severity or "").strip() or "--",
                str(issue.code or "").strip() or "--",
                str(issue.message or "").strip() or "--",
            ]
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))
        self.lbl_visible.setText(
            f"Mostrando {len(self._visible_issues)} de {len(self.analysis.issues)} aviso(s)"
        )


class PlantiosDialog(QDialog):
    def __init__(self, parent, plantios, compensacao_total=""):
        super().__init__(parent)
        self.presenter = PlantiosDialogPresenter()
        self.setWindowTitle("Plantios da Compensação")
        self.resize(760, 420)
        self._previous_plantios = clone_plantios(plantios)
        self._result_plantios = clone_plantios(plantios)
        self._compensacao_total = str(compensacao_total or "").strip()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self.lbl_hint = QLabel(
            "Cadastre cada endereço de plantio com a quantidade de mudas usada naquela área."
        )
        self.lbl_total = QLabel("")
        self.lbl_total.setObjectName("FormStateLabel")

        layout.addWidget(self.lbl_hint)
        layout.addWidget(self.lbl_total)

        self.table = QTableWidget(0, 2, self)
        self.table.setHorizontalHeaderLabels(["Endereço de Plantio", "Qtd. mudas"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table, 1)

        buttons_row = QHBoxLayout()
        buttons_row.setSpacing(8)
        self.btn_add_row = QPushButton("Adicionar Linha")
        self.btn_edit_row = QPushButton("Editar Linha")
        self.btn_remove_row = QPushButton("Remover Linha")
        self.btn_add_row.setProperty("kind", "secondary")
        self.btn_edit_row.setProperty("kind", "secondary")
        self.btn_remove_row.setProperty("kind", "secondary")
        buttons_row.addWidget(self.btn_add_row)
        buttons_row.addWidget(self.btn_edit_row)
        buttons_row.addWidget(self.btn_remove_row)
        buttons_row.addStretch(1)
        layout.addLayout(buttons_row)

        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        layout.addWidget(self.button_box)

        self.btn_add_row.clicked.connect(self.add_empty_row)
        self.btn_edit_row.clicked.connect(self.edit_selected_row)
        self.btn_remove_row.clicked.connect(self.remove_selected_row)
        self.button_box.accepted.connect(self._accept_with_validation)
        self.button_box.rejected.connect(self.reject)
        self.table.itemChanged.connect(self._refresh_totals)
        self.table.itemSelectionChanged.connect(self._refresh_row_actions)

        for plantio_row in self.presenter.build_initial_rows(self._previous_plantios):
            self._append_row(plantio_row.endereco, plantio_row.qtd_mudas)
        if self.table.rowCount() == 0:
            self.add_empty_row(start_edit=False)
        else:
            self.table.setCurrentCell(0, 0)
        self._refresh_totals()
        self._refresh_row_actions()

    @property
    def plantios(self):
        return clone_plantios(self._result_plantios)

    def _append_row(self, endereco="", qtd_mudas=""):
        append_plantio_row(self.table, endereco, qtd_mudas)

    def add_empty_row(self, start_edit: bool = True):
        empty_row = self.presenter.empty_row()
        self._append_row(empty_row.endereco, empty_row.qtd_mudas)
        self.table.setCurrentCell(self.table.rowCount() - 1, 0)
        self._refresh_totals()
        self._refresh_row_actions()
        if start_edit:
            self.edit_selected_row()

    def edit_selected_row(self):
        if self.table.rowCount() == 0:
            self.add_empty_row(start_edit=False)

        row = resolve_plantio_selected_row(self.table)

        column = self.table.currentColumn()
        if column < 0:
            column = 0

        self.table.setCurrentCell(row, column)
        self._edit_row_at(row)

    def _edit_row_at(self, row: int):
        endereco_item = self.table.item(row, 0)
        qtd_item = self.table.item(row, 1)
        editor = PlantioRowEditorDialog(
            self,
            endereco=endereco_item.text() if endereco_item else "",
            qtd_mudas=qtd_item.text() if qtd_item else "",
        )
        if not editor.exec():
            return

        endereco, qtd_mudas = editor.values()
        if endereco_item is None:
            endereco_item = QTableWidgetItem("")
            self.table.setItem(row, 0, endereco_item)
        if qtd_item is None:
            qtd_item = QTableWidgetItem("")
            self.table.setItem(row, 1, qtd_item)

        normalized_row = self.presenter.normalize_editor_values(endereco, qtd_mudas)
        apply_plantio_row_view(self.table, row, normalized_row)
        self.table.setCurrentCell(row, 0)
        self._refresh_totals()

    def remove_selected_row(self):
        row = resolve_plantio_selected_row(self.table)
        if row < 0:
            return
        self.table.removeRow(row)
        if self.table.rowCount() == 0:
            self.add_empty_row(start_edit=False)
            return
        next_row = resolve_plantio_next_row_after_removal(row, self.table.rowCount())
        self.table.setCurrentCell(next_row, 0)
        self._refresh_totals()
        self._refresh_row_actions()

    def _refresh_row_actions(self):
        actions_state = build_plantios_row_action_state(self.table)
        self.btn_edit_row.setEnabled(actions_state.has_rows)
        self.btn_remove_row.setEnabled(actions_state.has_rows)

    def _refresh_totals(self, *_args):
        self.lbl_total.setText(
            update_plantios_total_label(
                self.presenter,
                self.table,
                compensacao_total=self._compensacao_total,
            )
        )

    def _accept_with_validation(self):
        rows = read_plantio_rows_from_table(self.table)
        validation = self.presenter.validate_rows(rows, previous_plantios=self._previous_plantios)
        if not validation.is_valid:
            QMessageBox.warning(self, "Aviso", validation.message)
            return

        self._result_plantios = list(validation.plantios)
        self.accept()

class MapFullScreenDialog(QDialog):
    @staticmethod
    def _build_map_url(html_path, tile_proxy=None, *, engine: str = "", fallback_html_path: str = "") -> QUrl:
        url = QUrl.fromLocalFile(str(html_path))
        query = QUrlQuery()
        normalized_engine = str(engine or "").strip().lower()
        if not normalized_engine:
            normalized_engine = "maplibre" if str(html_path).lower().endswith("map_maplibre.html") else "leaflet"
        query.addQueryItem("mapEngine", normalized_engine)
        query.addQueryItem("defaultBaseLayer", MAP_DEFAULT_BASE_LAYER)
        if fallback_html_path:
            query.addQueryItem("fallbackUrl", QUrl.fromLocalFile(str(fallback_html_path)).toString())
        proxy_base = ""
        if tile_proxy is not None:
            try:
                proxy_base = str(tile_proxy.start() or "").strip()
            except Exception as exc:
                map_dialog_logger.warning("Falha ao iniciar proxy de tiles da tela cheia: %s", exc)
        if proxy_base:
            query.addQueryItem("tileProxy", proxy_base)
        elif normalized_engine == "leaflet":
            query.addQueryItem("tileScheme", "compmap")
        mapbox_token = resolve_mapbox_access_token()
        if mapbox_token and normalized_engine == "leaflet":
            mapbox_usage = read_mapbox_usage()
            query.addQueryItem("mapboxToken", mapbox_token)
            query.addQueryItem("mapboxUsageMonth", mapbox_usage.month)
            query.addQueryItem("mapboxTileUsed", str(mapbox_usage.tiles_used))
            query.addQueryItem("mapboxTileLimit", str(mapbox_usage.monthly_limit))
        url.setQuery(query)
        return url

    def __init__(self, parent, html_path, geojson_data, theme, marker_coords, gis_service, current_layer, heatmap_points):
        super().__init__(parent)
        self.setWindowFlags(Qt.Window)
        self.setWindowTitle("Mapa - Tela Cheia")
        self.resize(1200, 800)
        self.geojson_data = geojson_data
        self.theme = theme
        self.marker_coords = marker_coords
        self.gis = gis_service
        self.current_layer = current_layer
        self.heatmap_points = heatmap_points
        self.parent_window = parent
        self._syncing = False
        self._tile_proxy = TileProxyService(cache_size=1800, startup_wait_sec=0.8)
        self.map_rendering_use_cases = MapRenderingUseCases()
        self.map_interactions_use_cases = MapInteractionsUseCases()
        self.fullscreen_use_cases = MapFullscreenOperationsUseCases(
            rendering_use_cases=self.map_rendering_use_cases,
            interactions_use_cases=self.map_interactions_use_cases,
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        top_bar = QFrame()
        top_bar.setObjectName("TopBar")
        top_layout = QVBoxLayout(top_bar)
        top_layout.setContentsMargins(10, 8, 10, 8)
        top_layout.setSpacing(6)
        
        # Linha 1: Busca
        row1 = QHBoxLayout()
        row1.setSpacing(8)
        self.in_search = QLineEdit()
        self.in_search.setPlaceholderText("Pesquisar endereço no mapa...")
        self.in_search.setMinimumWidth(300)
        self.btn_search = QPushButton("Ir para")
        self.btn_search.setProperty("kind", "primary")
        self.btn_fs_batch = QPushButton("GPS em Lote")
        btn_close = QPushButton("Sair")
        btn_close.setProperty("kind", "secondary")
        row1.addWidget(self.in_search)
        row1.addWidget(self.btn_search)
        row1.addSpacing(10)
        row1.addWidget(self.btn_fs_batch)
        row1.addStretch(1)
        row1.addWidget(btn_close)

        # Linha 2: Calor e Status
        row2 = QHBoxLayout()
        row2.setSpacing(8)
        self.chk_fs_heatmap = QCheckBox("Mapa de Calor")
        self.chk_fs_heatmap.setChecked(parent.data_tab.chk_heatmap.isChecked())
        self.combo_fs_heatmap = QComboBox()
        self.combo_fs_heatmap.addItems(["Pendentes", "Realizadas", "Tudo"])
        self.combo_fs_heatmap.setCurrentText(parent.data_tab.combo_heatmap_type.currentText())
        self.combo_fs_heatmap.setMinimumWidth(150)
        self.lbl_status = QLabel("")
        self.lbl_status.setObjectName("MapStatus")
        row2.addWidget(self.chk_fs_heatmap)
        row2.addWidget(self.combo_fs_heatmap)
        row2.addSpacing(15)
        row2.addWidget(self.lbl_status, 1)

        top_layout.addLayout(row1); top_layout.addLayout(row2)
        layout.addWidget(top_bar)

        QWebEngineView, QWebChannel, QWebEngineSettings = _load_map_webengine_classes()

        self.web = QWebEngineView()
        self.web.setPage(DebugPage(self.web))
        s = self.web.page().settings()
        s.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
        s.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
        
        self.channel = QWebChannel(self.web.page())
        self.bridge = MapBridge(
            self._on_map_click_fs,
            self._on_layer_changed_fs,
            getattr(self.parent_window, "_on_mapbox_tiles_requested", None),
        )
        self.channel.registerObject("bridge", self.bridge)
        self.web.page().setWebChannel(self.channel)
        
        map_resource = resolve_map_engine_resource()
        url = self._build_map_url(
            html_path,
            self._tile_proxy,
            engine=map_resource.engine if str(html_path) == str(map_resource.html_path) else "",
            fallback_html_path=map_resource.fallback_html_path,
        )
        self.web.setUrl(url)
        self.web.loadFinished.connect(self._on_loaded)
        layout.addWidget(self.web, 1)

        btn_close.clicked.connect(self.close)
        self.btn_search.clicked.connect(self.perform_search)
        self.in_search.returnPressed.connect(self.perform_search)
        self.btn_fs_batch.clicked.connect(self.parent_window.run_batch_geocode)
        
        # Sincronização Calor (FS -> Main)
        self.chk_fs_heatmap.toggled.connect(self._sync_heatmap_to_main)
        self.combo_fs_heatmap.currentTextChanged.connect(self._sync_heatmap_to_main)
        
        self.showMaximized()

    def closeEvent(self, event):
        try:
            tile_proxy = getattr(self, "_tile_proxy", None)
            if tile_proxy is not None:
                tile_proxy.stop()
        finally:
            super().closeEvent(event)

    def _sync_heatmap_to_main(self):
        if self._syncing: return
        self._syncing = True
        try:
            self.parent_window.data_tab.chk_heatmap.setChecked(self.chk_fs_heatmap.isChecked())
            self.parent_window.data_tab.combo_heatmap_type.setCurrentText(self.combo_fs_heatmap.currentText())
            sync_view = build_fullscreen_heatmap_sync_view(
                use_cases=self.fullscreen_use_cases,
                records=self.parent_window.filtered_records,
                mode=self.combo_fs_heatmap.currentText(),
                enabled=self.chk_fs_heatmap.isChecked(),
            )
            self.heatmap_points = sync_view.points
            self.parent_window.toggle_heatmap()
            self._run_map_js(sync_view.script, sync_view.context)
        finally:
            self._syncing = False

    def _get_current_points_fs(self) -> list:
        fullscreen_use_cases = getattr(self, "fullscreen_use_cases", MapFullscreenOperationsUseCases())
        return build_fullscreen_current_points(
            use_cases=fullscreen_use_cases,
            records=self.parent_window.filtered_records,
            mode=self.combo_fs_heatmap.currentText(),
            enabled=bool(hasattr(self, "chk_fs_heatmap") and self.chk_fs_heatmap.isChecked()),
        )

    def _on_map_click_fs(self, lat, lng):
        result = self.fullscreen_use_cases.build_click_result(lat, lng)
        self.marker_coords = result.marker_coords
        self._run_map_js(result.command.script, result.command.context)
        self.lbl_status.setText(result.status_message)

    def _on_layer_changed_fs(self, name):
        if self.parent_window: self.parent_window.save_map_layer_preference(name)

    def _on_loaded(self, ok):
        if not ok: return
        schedule_owned_single_shot(self, 500, self._initial_sync_fs)

    def _initial_sync_fs(self):
        commands = self.fullscreen_use_cases.build_initial_sync_commands(
            theme=self.theme,
            geojson_data=self.geojson_data,
            current_layer=self.current_layer,
            marker_coords=self.marker_coords,
            heatmap_enabled=self.chk_fs_heatmap.isChecked(),
            heatmap_points=self.heatmap_points,
        )
        for command in commands:
            self._run_map_js(command.script, command.context)

    def _run_map_js(self, script: str, context: str):
        run_fullscreen_map_script(
            self.web.page(),
            script=script,
            context=context,
            logger=map_dialog_logger,
        )

    def perform_search(self):
        addr = self.in_search.text().strip()
        result = self.fullscreen_use_cases.search_address(
            address=addr,
            geocode_address=geocode_address,
        )
        if result.command is not None:
            self._run_map_js(result.command.script, result.command.context)
        if result.marker_coords is not None:
            self.marker_coords = result.marker_coords
        if result.status_message:
            self.lbl_status.setText(result.status_message)

class TableFullScreenDialog(QDialog):
    _FULLSCREEN_COLUMN_BASE_WIDTHS = {
        display_column_index("oficio_processo"): 180,
        display_column_index("eletronico"): 115,
        display_column_index("caixa"): 110,
        display_column_index("av_tec"): 120,
        display_column_index("compensacao"): 110,
        display_column_index("endereco"): 300,
        display_column_index("microbacia"): 150,
        display_column_index("compensado"): 120,
        display_column_index("endereco_plantio"): 330,
    }
    _FULLSCREEN_COLUMN_EXTRA_WEIGHTS = {
        display_column_index("oficio_processo"): 0.9,
        display_column_index("eletronico"): 0.3,
        display_column_index("caixa"): 0.25,
        display_column_index("av_tec"): 0.35,
        display_column_index("compensacao"): 0.25,
        display_column_index("endereco"): 1.8,
        display_column_index("microbacia"): 0.5,
        display_column_index("compensado"): 0.3,
        display_column_index("endereco_plantio"): 2.1,
    }

    def __init__(self, parent, content_widget, on_close_callback):
        super().__init__(parent)
        self.setWindowFlags(Qt.Window)
        self.setWindowTitle("Planilha - Tela Cheia")
        self._mw = parent
        self._content = content_widget
        self._on_close_callback = on_close_callback
        self._table = resolve_fullscreen_primary_table(self._content)
        self._layout_use_cases = TableFullscreenLayoutUseCases()
        self._filter_use_cases = TableFullscreenFiltersUseCases()
        self._table_layout_snapshot: Optional[TableHeaderLayoutSnapshot] = None
        self._syncing_filters = False
        self._table_layout_timer = QTimer(self)
        self._table_layout_timer.setSingleShot(True)
        self._table_layout_timer.timeout.connect(self._expand_table_to_fullscreen)
        self._table_late_layout_timer = QTimer(self)
        self._table_late_layout_timer.setSingleShot(True)
        self._table_late_layout_timer.timeout.connect(self._expand_table_to_fullscreen)
        self._has_filter_source = all(
            hasattr(parent, attr) for attr in ("data_tab", "search", "apply_filter")
        )
         
        sf = getattr(parent, "scale_factor", 1.0)
         
        layout = QVBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(0)
        top = QFrame(); top.setObjectName("TopBar")
        top_layout = QVBoxLayout(top); top_layout.setContentsMargins(10, 10, 10, 10); top_layout.setSpacing(8)
         
        # Adiciona busca exclusiva para a tela cheia
        self.search_fs = QLineEdit()
        self.search_fs.setPlaceholderText("Filtrar planilha (Ofício, Av. Técnica, Endereço...)")
        self.search_fs.setClearButtonEnabled(True)
        self.search_fs.setMinimumWidth(int(400 * sf))
         
        self.btn_exit = QPushButton("Sair da Tela Cheia")
        self.btn_exit.setProperty("kind", "secondary"); self.btn_exit.clicked.connect(self.close)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Busca:"))
        row1.addWidget(self.search_fs)
        row1.addStretch(1)
        row1.addWidget(self.btn_exit)

        row2 = QHBoxLayout()
        row2.setSpacing(8)
        self.filter_status_fs = None
        self.filter_year_fs = None
        self.filter_micro_fs = None
        self.filter_eletronico_fs = None
        self.filter_caixa_fs = None
        self.btn_clear_filters_fs = None

        if self._has_filter_source:
            self.filter_status_fs = ClickableComboBox()
            self.filter_year_fs = ClickableComboBox()
            self.filter_micro_fs = CheckableComboBox(parent.data_tab.filter_micro._all_label)
            self.filter_eletronico_fs = CheckableComboBox(parent.data_tab.filter_eletronico._all_label)
            self.filter_caixa_fs = CheckableComboBox(parent.data_tab.filter_caixa._all_label)
            self.btn_clear_filters_fs = QPushButton("Limpar Filtros")
            self.btn_clear_filters_fs.setProperty("kind", "secondary")

            self.filter_micro_fs.setMinimumWidth(int(220 * sf))
            self.filter_eletronico_fs.setMinimumWidth(int(140 * sf))
            self.filter_caixa_fs.setMinimumWidth(int(150 * sf))
            self.filter_status_fs.setMinimumWidth(int(130 * sf))
            self.filter_year_fs.setMinimumWidth(int(110 * sf))

            row2.addWidget(QLabel("Microbacia:"))
            row2.addWidget(self.filter_micro_fs)
            row2.addWidget(QLabel("Tipo:"))
            row2.addWidget(self.filter_eletronico_fs)
            row2.addWidget(QLabel("Caixa:"))
            row2.addWidget(self.filter_caixa_fs)
            row2.addWidget(QLabel("Status:"))
            row2.addWidget(self.filter_status_fs)
            row2.addWidget(QLabel("Ano:"))
            row2.addWidget(self.filter_year_fs)
            row2.addWidget(self.btn_clear_filters_fs)
            row2.addStretch(1)
         
        top_layout.addLayout(row1)
        if self._has_filter_source:
            top_layout.addLayout(row2)
         
        layout.addWidget(top); layout.addWidget(self._content, 1)
        if self._has_filter_source:
            self._copy_filters_from_main()
            self._connect_filter_signals()
        self._capture_table_layout()
        self.showMaximized()
        self._expand_table_to_fullscreen()
        self._queue_table_layout_refresh()
        self._table_late_layout_timer.start(80)

    def _capture_table_layout(self):
        if not self._table:
            return
        self._table_layout_snapshot = capture_fullscreen_table_layout(
            self._table,
            self._layout_use_cases.capture_header_layout,
        )

    def _fullscreen_visible_columns(self) -> List[int]:
        if not self._table:
            return []
        return resolve_fullscreen_visible_columns(self._table, self._layout_use_cases.visible_columns)

    def _preferred_fullscreen_column_widths(self) -> Optional[Dict[int, int]]:
        if not self._table:
            return None

        visible_columns = self._fullscreen_visible_columns()
        available_width = self._table.viewport().width()
        header_widths = build_fullscreen_header_widths(self._table, visible_columns)
        width_plan = self._layout_use_cases.build_width_plan(
            visible_columns=visible_columns,
            header_widths=header_widths,
            available_width=available_width,
            scale_factor=getattr(self._mw, "scale_factor", 1.0),
            base_widths=self._FULLSCREEN_COLUMN_BASE_WIDTHS,
            extra_weights=self._FULLSCREEN_COLUMN_EXTRA_WEIGHTS,
        )
        return None if width_plan.use_stretch_fallback else width_plan.widths

    def _copy_combo_items(self, source: QComboBox, target: QComboBox):
        target.clear()
        for index in range(source.count()):
            target.addItem(source.itemText(index))

    def _copy_checkable_items(self, source: CheckableComboBox, target: CheckableComboBox):
        model = source.model()
        items = []
        item_getter = getattr(model, "item", None)
        if callable(item_getter):
            for index in range(1, model.rowCount()):
                item = item_getter(index)
                if item is not None:
                    items.append(item.text())
        target.set_items(items)

    def _build_filter_state_from_main(self) -> TableFullscreenFilterState:
        return build_fullscreen_filter_state_from_main(self._mw, self._filter_use_cases)

    def _build_filter_state_from_dialog(self) -> TableFullscreenFilterState:
        return build_fullscreen_filter_state_from_dialog(self, self._filter_use_cases)

    def _apply_filter_state_to_dialog(self, state: TableFullscreenFilterState):
        apply_fullscreen_filter_state_to_dialog(self, state)

    def _apply_filter_state_to_main(self, state: TableFullscreenFilterState):
        apply_fullscreen_filter_state_to_main(self._mw, state)

    def _copy_filters_from_main(self):
        if not self._has_filter_source:
            return
        self._apply_filter_state_to_dialog(self._build_filter_state_from_main())

    def _sync_filters_from_main(self):
        if not self._has_filter_source:
            return
        self._syncing_filters = True
        try:
            self._apply_filter_state_to_dialog(self._build_filter_state_from_main())
        finally:
            self._syncing_filters = False

    def _connect_filter_signals(self):
        if not self._has_filter_source:
            return
        self.search_fs.textChanged.connect(self._apply_filters_to_main)
        self.filter_status_fs.currentTextChanged.connect(self._apply_filters_to_main)
        self.filter_year_fs.currentTextChanged.connect(self._apply_filters_to_main)
        self.filter_micro_fs.currentTextChanged.connect(self._apply_filters_to_main)
        self.filter_eletronico_fs.currentTextChanged.connect(self._apply_filters_to_main)
        self.filter_caixa_fs.currentTextChanged.connect(self._apply_filters_to_main)
        self.btn_clear_filters_fs.clicked.connect(self._clear_filters)

    def _clear_filters(self):
        if not self._has_filter_source:
            return
        self._syncing_filters = True
        try:
            self._apply_filter_state_to_dialog(
                self._filter_use_cases.build_cleared_state(self._build_filter_state_from_dialog())
            )
        finally:
            self._syncing_filters = False
        self._apply_filters_to_main()

    def _apply_filters_to_main(self, *_args):
        if not self._has_filter_source or self._syncing_filters:
            return

        with blocked_qt_signals(
            self._mw.search,
            self._mw.data_tab.filter_status,
            self._mw.data_tab.filter_year,
            self._mw.data_tab.filter_micro,
            self._mw.data_tab.filter_eletronico,
            self._mw.data_tab.filter_caixa,
        ):
            self._apply_filter_state_to_main(self._build_filter_state_from_dialog())
        self._mw.apply_filter()

    def _expand_table_to_fullscreen(self):
        if not self._table:
            return
        try:
            self._reserve_footer_space_for_fullscreen_table()
            apply_fullscreen_preferred_widths(self._table, self._preferred_fullscreen_column_widths())
        except RuntimeError:
            return

    def _queue_table_layout_refresh(self):
        if self._table_layout_timer.isActive():
            self._table_layout_timer.stop()
        self._table_layout_timer.start(0)

    def _reserve_footer_space_for_fullscreen_table(self):
        footer = self._content.findChild(QWidget, "TableFullscreenTotals") if self._content is not None else None
        if footer is None:
            return

        dialog_layout = self.layout()
        content_layout = self._content.layout() if self._content is not None else None
        dialog_margins = dialog_layout.contentsMargins() if dialog_layout is not None else None
        content_margins = content_layout.contentsMargins() if content_layout is not None else None
        dialog_spacing = dialog_layout.spacing() if dialog_layout is not None else 0
        content_spacing = content_layout.spacing() if content_layout is not None else 0
        footer_height = footer.height() if footer.height() > 0 else footer.sizeHint().height()
        content_height = self._content.height() if self._content is not None else 0
        if content_height > 0:
            reserved_inside_content = (
                footer_height
                + max(content_spacing, 0)
                + 28
            )
            if content_margins is not None:
                reserved_inside_content += content_margins.top() + content_margins.bottom()
            available = max(content_height - reserved_inside_content, 160)
            self._table.setMinimumHeight(0)
            self._table.setMaximumHeight(available)
            return

        top_bar = self.findChild(QWidget, "TopBar")
        top_height = top_bar.height() if top_bar is not None and top_bar.height() > 0 else 0
        reserved = (
            top_height
            + footer_height
            + max(dialog_spacing, 0)
            + max(content_spacing, 0)
            + 36
        )
        if dialog_margins is not None:
            reserved += dialog_margins.top() + dialog_margins.bottom()
        if content_margins is not None:
            reserved += content_margins.top() + content_margins.bottom()
        available = max(self.height() - reserved, 160)
        self._table.setMinimumHeight(0)
        self._table.setMaximumHeight(available)

    def _restore_table_layout(self):
        if not self._table or self._table_layout_snapshot is None:
            return
        try:
            restore_fullscreen_table_layout(self._table, self._table_layout_snapshot)
        except RuntimeError:
            return

    def closeEvent(self, event):
        self._table_layout_timer.stop()
        self._table_late_layout_timer.stop()
        if self._on_close_callback:
            self._on_close_callback(self._content)
        schedule_owned_single_shot(self, 0, self._restore_table_layout)
        super().closeEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._table:
            self._queue_table_layout_refresh()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Escape, Qt.Key_F11): self.close()
        super().keyPressEvent(event)
