import json
from typing import Optional, Sequence

from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.application.use_cases.persistence_monitoring import (
    PersistenceRecordOverviewReport,
    PersistenceStatusReport,
)
from app.application.use_cases.local_record_queries import LocalRecordReadStatus
from app.application.use_cases.runtime_monitoring import RuntimeJobOverviewReport
from app.services.audit_service import (
    AuditEvent,
    AuditOverview,
    audit_backup_available,
    audit_backup_path,
    build_audit_overview,
    format_audit_timestamp,
)
from app.ui.components.widgets import KPICard
from app.ui.tabs.operations_tab_support import (
    build_authoritative_write_text,
    build_backup_status_text,
    build_context_text,
    build_mutation_sync_text,
    build_persistence_status_text,
    build_read_source_text,
    build_record_overview_text,
    build_runtime_overview_texts,
    build_session_source_text,
    build_visible_counter_text,
    build_visible_summary_text,
)


class OperationsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = parent
        self.sf = getattr(parent, "scale_factor", 1.0)
        self.all_events: list[AuditEvent] = []
        self.events: list[AuditEvent] = []
        self.selected_event: Optional[AuditEvent] = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(int(10 * self.sf), int(10 * self.sf), int(10 * self.sf), int(10 * self.sf))
        layout.setSpacing(int(10 * self.sf))

        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(int(10 * self.sf))
        self.card_total = KPICard("Operações", "0", "#2176ff")
        self.card_today = KPICard("Hoje", "0", "#ff9800")
        self.card_backups = KPICard("Backups", "0", "#2e7d32")
        self.card_latest = KPICard("Última Ação", "--", "#8e24aa")
        for card in [self.card_total, self.card_today, self.card_backups, self.card_latest]:
            cards_layout.addWidget(card)
        layout.addLayout(cards_layout)

        self.lbl_context = QLabel("Abra uma sessão para acompanhar as operações recentes.")
        self.lbl_context.setWordWrap(True)
        layout.addWidget(self.lbl_context)

        self.lbl_summary = QLabel("Sem dados operacionais no momento.")
        self.lbl_summary.setWordWrap(True)
        self.lbl_summary.setObjectName("FormStateLabel")
        layout.addWidget(self.lbl_summary)

        self.lbl_persistence = QLabel("Espelho local (SQLite): aguardando sincronização.")
        self.lbl_persistence.setWordWrap(True)
        self.lbl_persistence.setObjectName("FormStateLabel")
        layout.addWidget(self.lbl_persistence)

        self.lbl_records_overview = QLabel(
            "Resumo local (SQLite): aguardando dados dos registros espelhados."
        )
        self.lbl_records_overview.setWordWrap(True)
        self.lbl_records_overview.setObjectName("FormStateLabel")
        layout.addWidget(self.lbl_records_overview)
        self.lbl_session_source = QLabel("Sessão carregada: aguardando leitura inicial da sessão.")
        self.lbl_session_source.setWordWrap(True)
        self.lbl_session_source.setObjectName("FormStateLabel")
        layout.addWidget(self.lbl_session_source)
        self.lbl_authoritative_write = QLabel("Escrita autoritativa: aguardando mutações da sessão.")
        self.lbl_authoritative_write.setWordWrap(True)
        self.lbl_authoritative_write.setObjectName("FormStateLabel")
        layout.addWidget(self.lbl_authoritative_write)
        self.lbl_mutation_sync = QLabel("Escrita local (SQLite): aguardando mutações da sessão.")
        self.lbl_mutation_sync.setWordWrap(True)
        self.lbl_mutation_sync.setObjectName("FormStateLabel")
        layout.addWidget(self.lbl_mutation_sync)
        self.lbl_read_source = QLabel("Leitura operacional atual: aguardando aplicação dos filtros.")
        self.lbl_read_source.setWordWrap(True)
        self.lbl_read_source.setObjectName("FormStateLabel")
        layout.addWidget(self.lbl_read_source)

        self.lbl_runtime_summary = QLabel("Jobs da sessão: nenhuma operação executada ainda.")
        self.lbl_runtime_summary.setWordWrap(True)
        self.lbl_runtime_summary.setObjectName("FormStateLabel")
        layout.addWidget(self.lbl_runtime_summary)

        self.lbl_runtime_active = QLabel("Jobs ativos: nenhum.")
        self.lbl_runtime_active.setWordWrap(True)
        self.lbl_runtime_active.setObjectName("FormStateLabel")
        layout.addWidget(self.lbl_runtime_active)

        self.lbl_runtime_recent = QLabel("Jobs recentes: nenhum.")
        self.lbl_runtime_recent.setWordWrap(True)
        self.lbl_runtime_recent.setObjectName("FormStateLabel")
        layout.addWidget(self.lbl_runtime_recent)

        filters_layout = QHBoxLayout()
        filters_layout.setSpacing(int(8 * self.sf))
        self.filter_action = QComboBox(self)
        self.filter_action.addItem("Todas")
        self.filter_backup = QComboBox(self)
        self.filter_backup.addItems(["Todos", "Com backup disponível", "Com backup configurado", "Sem backup"])
        self.search_input = QLineEdit(self)
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setPlaceholderText("Filtrar por resumo, ação, UID ou metadados...")
        self.btn_clear_filters = QPushButton("Limpar Filtros")
        self.btn_clear_filters.setProperty("kind", "secondary")
        self.lbl_visible = QLabel("Mostrando 0 de 0 operações")
        self.lbl_visible.setObjectName("FormStateLabel")
        filters_layout.addWidget(QLabel("Ação:"))
        filters_layout.addWidget(self.filter_action)
        filters_layout.addWidget(QLabel("Backup:"))
        filters_layout.addWidget(self.filter_backup)
        filters_layout.addWidget(QLabel("Busca:"))
        filters_layout.addWidget(self.search_input, 1)
        filters_layout.addWidget(self.btn_clear_filters)
        filters_layout.addWidget(self.lbl_visible)
        layout.addLayout(filters_layout)

        actions_layout = QHBoxLayout()
        actions_layout.setSpacing(int(8 * self.sf))
        self.btn_refresh = QPushButton("Atualizar")
        self.btn_history = QPushButton("Histórico Completo")
        self.btn_rollback = QPushButton("Máquina do Tempo")
        self.btn_open_backup = QPushButton("Abrir Backup")
        self.btn_cancel_runtime = QPushButton("Cancelar Operação Ativa")
        for button in [
            self.btn_refresh,
            self.btn_history,
            self.btn_rollback,
            self.btn_open_backup,
            self.btn_cancel_runtime,
        ]:
            button.setProperty("kind", "secondary")
            button.setMinimumHeight(int(28 * self.sf))
            actions_layout.addWidget(button)
        actions_layout.addStretch(1)
        layout.addLayout(actions_layout)

        content_layout = QHBoxLayout()
        content_layout.setSpacing(int(10 * self.sf))

        self.table = QTableWidget(0, 4, self)
        self.table.setHorizontalHeaderLabels(["Data/Hora", "Ação", "Resumo", "Backup"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        content_layout.addWidget(self.table, 3)

        details_frame = QFrame(self)
        details_layout = QVBoxLayout(details_frame)
        details_layout.setContentsMargins(0, 0, 0, 0)
        details_layout.setSpacing(int(6 * self.sf))
        self.lbl_details_title = QLabel("Detalhes")
        self.lbl_details_title.setObjectName("FormStateLabel")
        self.details = QPlainTextEdit(self)
        self.details.setReadOnly(True)
        self.details.setPlaceholderText("Selecione uma operação para ver os detalhes.")
        details_layout.addWidget(self.lbl_details_title)
        details_layout.addWidget(self.details, 1)
        content_layout.addWidget(details_frame, 2)

        layout.addLayout(content_layout, 1)

        self.table.itemSelectionChanged.connect(self._refresh_selection)
        self.filter_action.currentTextChanged.connect(self._apply_filters)
        self.filter_backup.currentTextChanged.connect(self._apply_filters)
        self.search_input.textChanged.connect(self._apply_filters)
        self.btn_clear_filters.clicked.connect(self._clear_filters)
        self.btn_open_backup.setEnabled(False)
        self.btn_cancel_runtime.setEnabled(False)
        self.btn_cancel_runtime.clicked.connect(self.main_window.cancel_active_operation)

    def apply_theme(self, theme: dict):
        for card in [self.card_total, self.card_today, self.card_backups, self.card_latest]:
            card.update_style(theme)

    def clear_overview(self, message: str = "Abra uma sessão para acompanhar as operações recentes."):
        self.all_events = []
        self.events = []
        self.selected_event = None
        self.card_total.update_value("0")
        self.card_today.update_value("0")
        self.card_backups.update_value("0")
        self.card_latest.update_value("--")
        self.lbl_context.setText(message)
        self.lbl_summary.setText("Sem dados operacionais no momento.")
        self.lbl_persistence.setText("Espelho local (SQLite): nenhuma sessão ativa.")
        self.lbl_records_overview.setText("Resumo local (SQLite): nenhuma sessão ativa.")
        self.lbl_session_source.setText("Sessão carregada: nenhuma sessão ativa.")
        self.lbl_authoritative_write.setText("Escrita autoritativa: nenhuma sessão ativa.")
        self.lbl_mutation_sync.setText("Escrita local (SQLite): nenhuma sessão ativa.")
        self.lbl_read_source.setText("Leitura operacional atual: nenhuma sessão ativa.")
        self.clear_runtime_overview()
        self.lbl_visible.setText(build_visible_counter_text(0, 0))
        self.filter_action.blockSignals(True)
        self.filter_action.clear()
        self.filter_action.addItem("Todas")
        self.filter_action.blockSignals(False)
        self.filter_backup.setCurrentText("Todos")
        self.search_input.clear()
        self.table.setRowCount(0)
        self.details.clear()
        self.btn_open_backup.setEnabled(False)

    def update_overview(
        self,
        workbook_path: str,
        events: Sequence[AuditEvent],
        overview: AuditOverview,
        persistence_report: Optional[PersistenceStatusReport] = None,
        record_overview_report: Optional[PersistenceRecordOverviewReport] = None,
        session_source_status: object | None = None,
        authoritative_write_status: object | None = None,
        mutation_sync_status: object | None = None,
        record_read_status: Optional[LocalRecordReadStatus] = None,
    ):
        self.all_events = list(events)
        self.events = list(events)
        self.selected_event = None
        self._sync_action_filter()
        self.lbl_context.setText(build_context_text(workbook_path, overview))
        self.lbl_persistence.setText(build_persistence_status_text(persistence_report))
        self.lbl_records_overview.setText(build_record_overview_text(record_overview_report))
        self.lbl_session_source.setText(build_session_source_text(session_source_status))
        self.lbl_authoritative_write.setText(build_authoritative_write_text(authoritative_write_status))
        self.lbl_mutation_sync.setText(build_mutation_sync_text(mutation_sync_status))
        self.lbl_read_source.setText(build_read_source_text(record_read_status))
        self._apply_filters()

    def update_runtime_overview(self, report: RuntimeJobOverviewReport):
        payload = build_runtime_overview_texts(report)
        self.lbl_runtime_summary.setText(payload.summary)
        self.lbl_runtime_active.setText(payload.active)
        self.lbl_runtime_recent.setText(payload.recent)
        self.btn_cancel_runtime.setEnabled(payload.cancel_enabled)

    def clear_runtime_overview(self):
        payload = build_runtime_overview_texts(None)
        self.lbl_runtime_summary.setText(payload.summary)
        self.lbl_runtime_active.setText(payload.active)
        self.lbl_runtime_recent.setText(payload.recent)
        self.btn_cancel_runtime.setEnabled(payload.cancel_enabled)

    def _sync_action_filter(self):
        current_text = self.filter_action.currentText()
        actions = sorted(
            {
                str(event.action or "").strip().upper()
                for event in self.all_events
                if str(event.action or "").strip()
            }
        )
        self.filter_action.blockSignals(True)
        self.filter_action.clear()
        self.filter_action.addItems(["Todas"] + actions)
        index = self.filter_action.findText(current_text)
        self.filter_action.setCurrentIndex(index if index >= 0 else 0)
        self.filter_action.blockSignals(False)

    def _matches_filters(self, event: AuditEvent) -> bool:
        selected_action = self.filter_action.currentText()
        event_action = str(event.action or "").strip().upper()
        if selected_action != "Todas" and event_action != selected_action:
            return False

        backup_filter = self.filter_backup.currentText()
        has_backup = bool(audit_backup_path(event))
        backup_available = audit_backup_available(event)
        if backup_filter == "Com backup disponível" and not backup_available:
            return False
        if backup_filter == "Com backup configurado" and not has_backup:
            return False
        if backup_filter == "Sem backup" and has_backup:
            return False

        query = (self.search_input.text() or "").strip().lower()
        if not query:
            return True

        payload = json.dumps(
            {
                "timestamp": event.timestamp,
                "action": event.action,
                "summary": event.summary,
                "backup_path": event.backup_path,
                "metadata": event.metadata,
                "before": event.before,
                "after": event.after,
            },
            ensure_ascii=False,
            sort_keys=True,
        ).lower()
        return query in payload

    def _apply_filters(self, *_args):
        current_event_id = getattr(self.selected_event, "event_id", "")
        self.events = [event for event in self.all_events if self._matches_filters(event)]
        self._render_table(current_event_id=current_event_id)
        self._update_overview_cards_and_summary()

    def _render_table(self, *, current_event_id: str = ""):
        self.table.setRowCount(0)
        for event in self.events:
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = [
                format_audit_timestamp(event.timestamp),
                str(event.action or "").strip().upper(),
                str(event.summary or ""),
                build_backup_status_text(event),
            ]
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))

        self.lbl_visible.setText(build_visible_counter_text(len(self.events), len(self.all_events)))

        if not self.events:
            self.selected_event = None
            self.details.setPlainText("Nenhuma operação encontrada para os filtros atuais.")
            self.btn_open_backup.setEnabled(False)
            return

        target_row = 0
        if current_event_id:
            for index, event in enumerate(self.events):
                if event.event_id == current_event_id:
                    target_row = index
                    break
        self.table.setCurrentCell(target_row, 0)

    def _update_overview_cards_and_summary(self):
        overview = build_audit_overview(self.events)
        self.card_total.update_value(str(overview.total_events))
        self.card_today.update_value(str(overview.events_today))
        self.card_backups.update_value(str(overview.available_backups))
        latest_value = "--"
        if self.events:
            latest_value = str(self.events[0].action or "").strip().upper() or "--"
        self.card_latest.update_value(latest_value)
        self.lbl_summary.setText(build_visible_summary_text(overview))

    def _clear_filters(self):
        self.filter_action.setCurrentText("Todas")
        self.filter_backup.setCurrentText("Todos")
        self.search_input.clear()

    def _current_event(self) -> Optional[AuditEvent]:
        row = self.table.currentRow()
        if row < 0 or row >= len(self.events):
            return None
        return self.events[row]

    def _refresh_selection(self):
        event = self._current_event()
        self.selected_event = event
        if event is None:
            self.details.clear()
            self.btn_open_backup.setEnabled(False)
            return

        payload = {
            "event_id": getattr(event, "event_id", ""),
            "timestamp": getattr(event, "timestamp", ""),
            "action": getattr(event, "action", ""),
            "summary": getattr(event, "summary", ""),
            "backup_path": getattr(event, "backup_path", ""),
            "backup_available": audit_backup_available(event),
            "metadata": getattr(event, "metadata", {}),
            "before": getattr(event, "before", None),
            "after": getattr(event, "after", None),
        }
        self.details.setPlainText(json.dumps(payload, ensure_ascii=False, indent=2))
        self.btn_open_backup.setEnabled(audit_backup_available(event))
