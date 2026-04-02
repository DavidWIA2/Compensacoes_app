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

        self.lbl_context = QLabel("Abra uma planilha para acompanhar as operações recentes.")
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
        self.lbl_session_source = QLabel("Sessao carregada: aguardando leitura inicial da planilha.")
        self.lbl_session_source.setWordWrap(True)
        self.lbl_session_source.setObjectName("FormStateLabel")
        layout.addWidget(self.lbl_session_source)
        self.lbl_mutation_sync = QLabel("Escrita local (SQLite): aguardando mutacoes da sessao.")
        self.lbl_mutation_sync.setWordWrap(True)
        self.lbl_mutation_sync.setObjectName("FormStateLabel")
        layout.addWidget(self.lbl_mutation_sync)
        self.lbl_read_source = QLabel("Leitura operacional atual: aguardando aplicacao dos filtros.")
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

    def clear_overview(self, message: str = "Abra uma planilha para acompanhar as operações recentes."):
        self.all_events = []
        self.events = []
        self.selected_event = None
        self.card_total.update_value("0")
        self.card_today.update_value("0")
        self.card_backups.update_value("0")
        self.card_latest.update_value("--")
        self.lbl_context.setText(message)
        self.lbl_summary.setText("Sem dados operacionais no momento.")
        self.lbl_persistence.setText("Espelho local (SQLite): nenhuma planilha ativa.")
        self.lbl_records_overview.setText("Resumo local (SQLite): nenhuma planilha ativa.")
        self.lbl_session_source.setText("Sessao carregada: nenhuma planilha ativa.")
        self.lbl_mutation_sync.setText("Escrita local (SQLite): nenhuma planilha ativa.")
        self.lbl_read_source.setText("Leitura operacional atual: nenhuma planilha ativa.")
        self.clear_runtime_overview()
        self.lbl_visible.setText("Mostrando 0 de 0 operações")
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
        mutation_sync_status: object | None = None,
        record_read_status: Optional[LocalRecordReadStatus] = None,
    ):
        self.all_events = list(events)
        self.events = list(events)
        self.selected_event = None
        self._sync_action_filter()

        workbook_label = workbook_path or "nenhuma"
        self.lbl_context.setText(
            "\n".join(
                [
                    f"Planilha monitorada: {workbook_label}",
                    (
                        f"Última operação: {overview.latest_timestamp or '--'} | "
                        f"{overview.latest_summary or 'Nenhuma operação registrada.'}"
                    ),
                ]
            )
        )
        self._update_persistence_status(persistence_report)
        self._update_record_overview(record_overview_report)
        self._update_session_source(session_source_status)
        self._update_mutation_sync(mutation_sync_status)
        self._update_read_source(record_read_status)
        self._apply_filters()

    def update_runtime_overview(self, report: RuntimeJobOverviewReport):
        if report.total_jobs <= 0:
            self.clear_runtime_overview()
            return

        status_map = {
            "running": "Em execução",
            "completed": "Concluído",
            "failed": "Falhou",
            "cancelled": "Cancelado",
        }
        latest_status = status_map.get(report.latest_status, report.latest_status or "--")
        self.lbl_runtime_summary.setText(
            "\n".join(
                [
                    (
                        f"Jobs da sessão: {report.total_jobs} | "
                        f"{report.running_jobs} em execução | "
                        f"{report.completed_jobs} concluídos | "
                        f"{report.failed_jobs} falharam | "
                        f"{report.cancelled_jobs} cancelados"
                    ),
                    (
                        f"Último job: {latest_status} | "
                        f"{report.latest_label or '--'} | "
                        f"{report.latest_detail_message or 'Sem detalhes adicionais.'}"
                    ),
                ]
            )
        )

        if report.active_jobs:
            active_lines = []
            for job in report.active_jobs:
                progress_suffix = f" ({job.progress_value}/{job.total})" if job.total > 0 else ""
                active_lines.append(f"{job.label}{progress_suffix}: {job.detail_message or 'Em andamento'}")
            self.lbl_runtime_active.setText("Jobs ativos: " + " | ".join(active_lines))
        else:
            self.lbl_runtime_active.setText("Jobs ativos: nenhum.")

        recent_lines = []
        for job in report.recent_jobs[:3]:
            status_text = status_map.get(job.status, job.status or "--")
            recent_lines.append(f"[{status_text}] {job.label} - {job.detail_message or 'Sem detalhes'}")
        self.lbl_runtime_recent.setText(
            "Jobs recentes: " + (" | ".join(recent_lines) if recent_lines else "nenhum.")
        )
        self.btn_cancel_runtime.setEnabled(report.cancellable_jobs > 0)

    def clear_runtime_overview(self):
        self.lbl_runtime_summary.setText("Jobs da sessão: nenhuma operação executada ainda.")
        self.lbl_runtime_active.setText("Jobs ativos: nenhum.")
        self.lbl_runtime_recent.setText("Jobs recentes: nenhum.")
        self.btn_cancel_runtime.setEnabled(False)

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
            status = (
                "Disponível"
                if audit_backup_available(event)
                else ("Configurado" if audit_backup_path(event) else "Sem backup")
            )
            values = [
                format_audit_timestamp(event.timestamp),
                str(event.action or "").strip().upper(),
                str(event.summary or ""),
                status,
            ]
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))

        self.lbl_visible.setText(f"Mostrando {len(self.events)} de {len(self.all_events)} operações")

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

        if overview.action_counts:
            actions_text = " | ".join(f"{action}: {count}" for action, count in overview.action_counts)
        else:
            actions_text = "Nenhuma operação corresponde aos filtros atuais."
        self.lbl_summary.setText(
            "\n".join(
                [
                    (
                        f"Resumo visível: {overview.total_events} operações | "
                        f"{overview.events_today} hoje | "
                        f"{overview.available_backups}/{overview.configured_backups} backups disponíveis"
                    ),
                    f"Ações visíveis: {actions_text}",
                ]
            )
        )

    def _update_persistence_status(self, report: Optional[PersistenceStatusReport]):
        if report is None:
            self.lbl_persistence.setText("Espelho local (SQLite): indisponível nesta sessão.")
            return

        status_map = {
            "sincronizado": "Sincronizado",
            "atencao": "Em atenção",
            "ausente": "Ainda não sincronizado",
            "indisponivel": "Indisponível",
        }
        status_text = status_map.get(report.status, report.status.title())
        synced_at = format_audit_timestamp(report.synced_at) if report.synced_at else "--"
        lines = [
            f"Espelho local (SQLite): {status_text} | Última sincronização: {synced_at}",
            (
                f"Registros espelhados: {report.mirrored_records}/{report.expected_records} | "
                f"Eventos auditados: {report.mirrored_audit_events}/{report.expected_audit_events} | "
                f"Plantios espelhados: {report.mirrored_plantios}"
            ),
        ]
        if report.issues:
            lines.append("Pendências: " + " | ".join(report.issues))
        self.lbl_persistence.setText("\n".join(lines))

    def _update_record_overview(self, report: Optional[PersistenceRecordOverviewReport]):
        if report is None:
            self.lbl_records_overview.setText("Resumo local (SQLite): indisponível nesta sessão.")
            return

        if report.status == "indisponivel":
            self.lbl_records_overview.setText(
                "Resumo local (SQLite): o espelho local não está disponível nesta sessão."
            )
            return

        if report.status == "ausente":
            self.lbl_records_overview.setText(
                "Resumo local (SQLite): a planilha ainda não foi sincronizada para consultas locais."
            )
            return

        lines = [
            (
                f"Resumo local (SQLite): {report.total_records} registros | "
                f"{report.compensados_count} compensados | "
                f"{report.pendentes_count} pendentes | "
                f"{report.records_with_plantios_count} com plantios"
            ),
            (
                f"Qualidade do espelho: {report.records_without_microbacia_count} sem microbacia | "
                f"{report.records_without_coordinates_count} sem coordenadas"
            ),
        ]
        if report.top_microbacias:
            lines.append(
                "Microbacias em destaque: "
                + " | ".join(f"{label}: {count}" for label, count in report.top_microbacias)
            )
        if report.sample_records:
            lines.append(
                "Amostra do espelho: "
                + " | ".join(self._format_sample_record(sample) for sample in report.sample_records)
            )
        self.lbl_records_overview.setText("\n".join(lines))

    def _update_read_source(self, status: Optional[LocalRecordReadStatus]):
        if status is None or status.status == "indisponivel":
            self.lbl_read_source.setText("Leitura operacional atual: sessao em memoria.")
            return

        if status.uses_sqlite:
            lines = [
                (
                    f"Leitura operacional atual: espelho local (SQLite) | "
                    f"{status.filtered_records} registro(s) no recorte"
                )
            ]
            if status.strategy == "sqlite_query":
                lines.append("Modo de leitura local: consulta indexada.")
            if status.synced_at:
                lines.append(
                    f"Ultima sincronizacao valida: {format_audit_timestamp(status.synced_at)}"
                )
            self.lbl_read_source.setText("\n".join(lines))
            return

        lines = [
            (
                f"Leitura operacional atual: sessao em memoria | "
                f"{status.filtered_records} registro(s) no recorte"
            )
        ]
        if status.issues:
            lines.append("Motivos do fallback: " + " | ".join(status.issues))
        self.lbl_read_source.setText("\n".join(lines))

    def _update_session_source(self, status: object | None):
        if status is None:
            self.lbl_session_source.setText("Sessao carregada: aguardando leitura inicial da planilha.")
            return

        source = str(getattr(status, "source", "") or "").strip()
        strategy = str(getattr(status, "strategy", "") or "").strip()
        synced_at = str(getattr(status, "synced_at", "") or "").strip()
        filtered_records = int(getattr(status, "filtered_records", 0) or 0)
        issues = tuple(getattr(status, "issues", ()) or ())

        if source == "sqlite":
            lines = [f"Sessao carregada: espelho local (SQLite) com {filtered_records} registro(s)."]
            if strategy == "sqlite_snapshot":
                lines.append("Modo de carga da sessao: snapshot local validado.")
            if synced_at:
                lines.append(f"Ultima sincronizacao usada na carga: {format_audit_timestamp(synced_at)}")
            self.lbl_session_source.setText("\n".join(lines))
            return

        lines = [f"Sessao carregada: memoria da sessao com {filtered_records} registro(s)."]
        if issues:
            lines.append("Motivos do fallback: " + " | ".join(str(issue) for issue in issues))
        self.lbl_session_source.setText("\n".join(lines))

    def _update_mutation_sync(self, status: object | None):
        if status is None:
            self.lbl_mutation_sync.setText("Escrita local (SQLite): nenhuma mutacao registrada nesta sessao.")
            return

        sync_status = str(getattr(status, "status", "") or "").strip()
        operation = str(getattr(status, "operation", "") or "").strip() or "mutacao"
        strategy = str(getattr(status, "strategy", "") or "").strip()
        record_count = int(getattr(status, "record_count", 0) or 0)
        synced_at = str(getattr(status, "synced_at", "") or "").strip()
        issues = tuple(getattr(status, "issues", ()) or ())

        if sync_status == "sqlite":
            lines = [f"Escrita local (SQLite): {operation} sincronizada com {record_count} registro(s)."]
            if strategy == "incremental":
                lines.append("Modo de escrita local: sincronizacao incremental.")
            elif strategy == "snapshot_rebuild":
                lines.append("Modo de escrita local: reconstrucao completa do snapshot.")
            if synced_at:
                lines.append(f"Ultima sincronizacao de escrita: {format_audit_timestamp(synced_at)}")
            if issues:
                lines.append("Observacoes: " + " | ".join(str(issue) for issue in issues))
            self.lbl_mutation_sync.setText("\n".join(lines))
            return

        if sync_status == "falha":
            lines = [f"Escrita local (SQLite): falha na sincronizacao da operacao {operation}."]
            if issues:
                lines.append("Detalhes: " + " | ".join(str(issue) for issue in issues))
            self.lbl_mutation_sync.setText("\n".join(lines))
            return

        if sync_status == "indisponivel":
            lines = [f"Escrita local (SQLite): indisponivel para a operacao {operation}."]
            if issues:
                lines.append("Detalhes: " + " | ".join(str(issue) for issue in issues))
            self.lbl_mutation_sync.setText("\n".join(lines))
            return

        self.lbl_mutation_sync.setText("Escrita local (SQLite): aguardando mutacoes da sessao.")

    @staticmethod
    def _format_sample_record(sample) -> str:
        status = str(sample.compensado or "").strip().upper() or "PENDENTE"
        return (
            f"Linha {int(sample.excel_row)} | {sample.av_tec or '--'} | "
            f"{sample.uid or '--'} | {sample.microbacia or '(sem microbacia)'} | "
            f"{status} | plantios {int(sample.plantio_count)}"
        )

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
