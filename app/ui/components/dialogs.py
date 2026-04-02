import json
import os
from datetime import date, datetime
from typing import Dict, List, Optional
from PySide6.QtCore import Qt, QUrl, QTimer, QDate
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton, 
    QLineEdit, QComboBox, QMessageBox, QCheckBox, QFileDialog, QDateEdit,
    QTableView, QHeaderView, QDialogButtonBox, QTableWidget, QTableWidgetItem,
    QFormLayout, QPlainTextEdit,
    QAbstractItemView
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEngineSettings
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
    PlantioRowView,
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
from app.ui.components.widgets import CheckableComboBox, MapBridge, DebugPage
from app.services.geocode_service import geocode_address_arcgis
from app.services.plantio_service import clone_plantios
from app.utils.logger import get_logger

map_dialog_logger = get_logger("UI.MapDialog")


class ImportPreviewDialog(QDialog):
    def __init__(self, parent, analysis):
        super().__init__(parent)
        self.analysis = analysis
        self.presenter = ImportPreviewPresenter()
        self.presentation: ImportPreviewPresentation = self.presenter.build_presentation(analysis)
        self._rows: tuple[ImportPreviewRowView, ...] = self.presentation.rows
        self._visible_rows: list[ImportPreviewRowView] = []
        self.setWindowTitle("Preflight de Importacao")
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
        self.filter_status = QComboBox(self)
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

        self.button_box = QDialogButtonBox(self)
        if analysis.total_invalid:
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

    def _insert_table_row(self, row_data: ImportPreviewRowView):
        row = self.table.rowCount()
        self.table.insertRow(row)
        values = [
            row_data.line_number,
            row_data.uid,
            row_data.av_tec,
            row_data.status,
            row_data.detail,
        ]
        for column, value in enumerate(values):
            self.table.setItem(row, column, QTableWidgetItem(value))

    def _apply_filters(self, *_args):
        current_key = None
        current_row = self.table.currentRow()
        if 0 <= current_row < len(self._visible_rows):
            current_key = self._visible_rows[current_row].key()

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

        target_index = 0
        if current_key is not None:
            for index, row_data in enumerate(self._visible_rows):
                if row_data.key() == current_key:
                    target_index = index
                    break
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
        self.filter_action = QComboBox(self)
        self.filter_action.addItems(list(self.presenter.build_action_items(self.events)))
        self.filter_backup = QComboBox(self)
        self.filter_backup.addItems(["Todos", "Com backup", "Sem backup"])
        self.filter_period = QComboBox(self)
        self.filter_period.addItems(["Todos", "Hoje", "Ultimos 7 dias", "Ultimos 30 dias", "Personalizado"])
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

        target_index = 0
        if current_event_id:
            for index, event in enumerate(self.visible_events):
                if getattr(event, "event_id", "") == current_event_id:
                    target_index = index
                    break
        self.table.setCurrentCell(target_index, 0)
        self._persist_filter_state()

    def _current_event(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self.visible_events):
            return None
        return self.visible_events[row]

    def _resolve_default_date_range(self) -> tuple[QDate, QDate]:
        from_date, to_date = self.presenter.resolve_default_date_range(self.events)
        return QDate(from_date.year, from_date.month, from_date.day), QDate(to_date.year, to_date.month, to_date.day)

    def _update_summary_label(self):
        self.lbl_summary.setText(
            self.presenter.build_summary_text(
                visible_events=self.visible_events,
                state=self._filter_state(),
            )
        )

    @staticmethod
    def _backup_path(event) -> str:
        return str(getattr(event, "backup_path", "") or "").strip()

    def _backup_available(self, event) -> bool:
        return self.presenter.backup_status_label(event) == "Disponivel"

    def _backup_status_label(self, event) -> str:
        return self.presenter.backup_status_label(event)

    def _settings_store(self):
        settings = getattr(self.parent(), "settings", None)
        if settings is None:
            return None
        if hasattr(settings, "operation_history_filter_state") and hasattr(settings, "set_operation_history_filter_state"):
            return settings
        if hasattr(settings, "value") and hasattr(settings, "setValue"):
            return settings
        return None

    def _persist_filter_state(self):
        settings = self._settings_store()
        if settings is None or self._restoring_filters:
            return
        state = {
            "action": self.filter_action.currentText(),
            "backup": self.filter_backup.currentText(),
            "period": self.filter_period.currentText(),
            "date_from": self.date_from.date().toString(Qt.DateFormat.ISODate),
            "date_to": self.date_to.date().toString(Qt.DateFormat.ISODate),
            "search": self.search_input.text(),
        }
        if hasattr(settings, "set_operation_history_filter_state"):
            settings.set_operation_history_filter_state(state)
        else:
            settings.setValue("operation_history_filter_state", state)

    def _restore_filter_state(self):
        settings = self._settings_store()
        if settings is None:
            return
        if hasattr(settings, "operation_history_filter_state"):
            state = settings.operation_history_filter_state()
        else:
            raw_state = settings.value("operation_history_filter_state", {})
            state = dict(raw_state) if isinstance(raw_state, dict) else {}

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
        parent = self.parent()
        initial_dir = ""
        if parent is not None and hasattr(parent, "settings_controller"):
            initial_dir = parent.settings_controller.preferred_export_dir()
        filename = f"historico_operacoes_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        if initial_dir:
            return os.path.join(initial_dir, filename)
        return filename

    def export_history(self):
        if not self.visible_events:
            QMessageBox.information(self, "Historico de Operacoes", "Nao ha operacoes visiveis para exportar.")
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

        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=True, indent=2)

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
        event = self._current_event()
        self.selected_event = event
        if event is None:
            self.btn_open_backup.setEnabled(False)
            self.btn_restore.setEnabled(False)
            self.details.clear()
            return

        backup_available = self._backup_available(event)
        self.btn_open_backup.setEnabled(backup_available)
        self.btn_restore.setEnabled(backup_available)
        self.details.setPlainText(self.presenter.build_details_text(event))

    def _open_selected_backup(self):
        event = self._current_event()
        if event is None or not self._backup_available(event):
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(self._backup_path(event)))

    def _request_restore(self):
        event = self._current_event()
        if event is None or not self._backup_available(event):
            return
        self.selected_event = event
        self.restore_requested = True
        self.accept()

    def _filter_state(self) -> OperationHistoryFilterState:
        return OperationHistoryFilterState(
            action=self.filter_action.currentText(),
            backup=self.filter_backup.currentText(),
            period=self.filter_period.currentText(),
            date_from=self._qdate_to_date(self.date_from.date()),
            date_to=self._qdate_to_date(self.date_to.date()),
            search=self.search_input.text(),
        )

    @staticmethod
    def _qdate_to_date(value: QDate) -> date | None:
        if not value.isValid():
            return None
        return date(value.year(), value.month(), value.day())


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

        form.addRow("Endereco de Plantio:", self.in_endereco)
        form.addRow("Qtd. mudas:", self.in_qtd_mudas)
        layout.addLayout(form)

        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def values(self):
        return self.in_endereco.text().strip(), self.in_qtd_mudas.text().strip()


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
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(str(endereco or "")))
        self.table.setItem(row, 1, QTableWidgetItem(str(qtd_mudas or "")))

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

        row = self.table.currentRow()
        if row < 0:
            row = self.table.rowCount() - 1

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
        endereco_item.setText(normalized_row.endereco)
        qtd_item.setText(normalized_row.qtd_mudas)
        self.table.setCurrentCell(row, 0)
        self._refresh_totals()

    def remove_selected_row(self):
        row = self.table.currentRow()
        if row < 0:
            row = self.table.rowCount() - 1
        if row < 0:
            return
        self.table.removeRow(row)
        if self.table.rowCount() == 0:
            self.add_empty_row(start_edit=False)
            return
        next_row = min(row, self.table.rowCount() - 1)
        self.table.setCurrentCell(next_row, 0)
        self._refresh_totals()
        self._refresh_row_actions()

    def _refresh_row_actions(self):
        has_rows = self.table.rowCount() > 0
        self.btn_edit_row.setEnabled(has_rows)
        self.btn_remove_row.setEnabled(has_rows)

    def _rows_from_table(self) -> list[PlantioRowView]:
        rows: list[PlantioRowView] = []
        for row in range(self.table.rowCount()):
            endereco_item = self.table.item(row, 0)
            qtd_item = self.table.item(row, 1)
            rows.append(
                PlantioRowView(
                    endereco=endereco_item.text().strip() if endereco_item else "",
                    qtd_mudas=qtd_item.text().strip() if qtd_item else "",
                )
            )
        return rows

    def _refresh_totals(self, *_args):
        rows = self._rows_from_table()
        self.lbl_total.setText(self.presenter.total_text(rows, self._compensacao_total))

    def _accept_with_validation(self):
        rows = self._rows_from_table()
        validation = self.presenter.validate_rows(rows, previous_plantios=self._previous_plantios)
        if not validation.is_valid:
            QMessageBox.warning(self, "Aviso", validation.message)
            return

        self._result_plantios = list(validation.plantios)
        self.accept()

class MapFullScreenDialog(QDialog):
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

        self.web = QWebEngineView()
        self.web.setPage(DebugPage(self.web))
        s = self.web.page().settings()
        s.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
        s.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
        
        self.channel = QWebChannel(self.web.page())
        self.bridge = MapBridge(self._on_map_click_fs, self._on_layer_changed_fs)
        self.channel.registerObject("bridge", self.bridge)
        self.web.page().setWebChannel(self.channel)
        
        url = QUrl.fromLocalFile(str(html_path))
        url.setQuery("tileScheme=compmap")
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

    def _sync_heatmap_to_main(self):
        if self._syncing: return
        self._syncing = True
        try:
            self.parent_window.data_tab.chk_heatmap.setChecked(self.chk_fs_heatmap.isChecked())
            self.parent_window.data_tab.combo_heatmap_type.setCurrentText(self.combo_fs_heatmap.currentText())
            result = self.fullscreen_use_cases.build_heatmap_sync_result(
                records=self.parent_window.filtered_records,
                mode=self.combo_fs_heatmap.currentText(),
                enabled=self.chk_fs_heatmap.isChecked(),
            )
            pts = [list(point) for point in result.points]
            self.heatmap_points = pts
            self.parent_window.toggle_heatmap()
            self._run_map_js(result.command.script, result.command.context)
        finally:
            self._syncing = False

    def _get_current_points_fs(self) -> list:
        fullscreen_use_cases = getattr(self, "fullscreen_use_cases", MapFullscreenOperationsUseCases())
        result = fullscreen_use_cases.build_heatmap_sync_result(
            records=self.parent_window.filtered_records,
            mode=self.combo_fs_heatmap.currentText(),
            enabled=bool(hasattr(self, "chk_fs_heatmap") and self.chk_fs_heatmap.isChecked()),
        )
        return [list(point) for point in result.points]

    def _on_map_click_fs(self, lat, lng):
        result = self.fullscreen_use_cases.build_click_result(lat, lng)
        self.marker_coords = result.marker_coords
        self._run_map_js(result.command.script, result.command.context)
        self.lbl_status.setText(result.status_message)

    def _on_layer_changed_fs(self, name):
        if self.parent_window: self.parent_window.save_map_layer_preference(name)

    def _on_loaded(self, ok):
        if not ok: return
        QTimer.singleShot(500, self._initial_sync_fs)

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
        try:
            self.web.page().runJavaScript(script)
        except Exception as exc:
            map_dialog_logger.error("[FS MAP JS] Falha em %s: %s", context, exc)

    def perform_search(self):
        addr = self.in_search.text().strip()
        result = self.fullscreen_use_cases.search_address(
            address=addr,
            geocode_address=geocode_address_arcgis,
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
        self._table = self._find_primary_table()
        self._layout_use_cases = TableFullscreenLayoutUseCases()
        self._filter_use_cases = TableFullscreenFiltersUseCases()
        self._table_layout_snapshot: Optional[TableHeaderLayoutSnapshot] = None
        self._syncing_filters = False
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
        self.btn_clear_filters_fs = None

        if self._has_filter_source:
            self.filter_status_fs = QComboBox()
            self.filter_year_fs = QComboBox()
            self.filter_micro_fs = CheckableComboBox(parent.data_tab.filter_micro._all_label)
            self.filter_eletronico_fs = CheckableComboBox(parent.data_tab.filter_eletronico._all_label)
            self.btn_clear_filters_fs = QPushButton("Limpar Filtros")
            self.btn_clear_filters_fs.setProperty("kind", "secondary")

            self.filter_micro_fs.setMinimumWidth(int(220 * sf))
            self.filter_eletronico_fs.setMinimumWidth(int(140 * sf))
            self.filter_status_fs.setMinimumWidth(int(130 * sf))
            self.filter_year_fs.setMinimumWidth(int(110 * sf))

            row2.addWidget(QLabel("Microbacia:"))
            row2.addWidget(self.filter_micro_fs)
            row2.addWidget(QLabel("Tipo:"))
            row2.addWidget(self.filter_eletronico_fs)
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
        QTimer.singleShot(0, self._expand_table_to_fullscreen)
        self.showMaximized()

    def _find_primary_table(self):
        tables = self._content.findChildren(QTableView)
        if not tables:
            return None
        return max(
            tables,
            key=lambda table: table.model().columnCount() if table.model() else 0
        )

    def _capture_table_layout(self):
        if not self._table:
            return
        header = self._table.horizontalHeader()
        self._table_layout_snapshot = self._layout_use_cases.capture_header_layout(
            stretch_last_section=header.stretchLastSection(),
            resize_modes=[header.sectionResizeMode(i) for i in range(header.count())],
            section_sizes=[header.sectionSize(i) for i in range(header.count())],
        )

    def _fullscreen_visible_columns(self) -> List[int]:
        if not self._table:
            return []
        hidden_columns = [
            self._table.isColumnHidden(index)
            for index in range(self._table.horizontalHeader().count())
        ]
        return self._layout_use_cases.visible_columns(hidden_columns)

    def _preferred_fullscreen_column_widths(self) -> Optional[Dict[int, int]]:
        if not self._table:
            return None

        header = self._table.horizontalHeader()
        visible_columns = self._fullscreen_visible_columns()
        available_width = self._table.viewport().width()
        header_widths = {
            index: header.fontMetrics().horizontalAdvance(
                str(
                    self._table.model().headerData(
                        index,
                        Qt.Orientation.Horizontal,
                        Qt.ItemDataRole.DisplayRole,
                    )
                    or ""
                )
            )
            for index in visible_columns
        }
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

    @staticmethod
    def _combo_items(combo: QComboBox) -> List[str]:
        return [combo.itemText(index) for index in range(combo.count())]

    @staticmethod
    def _checkable_items(combo: CheckableComboBox) -> List[str]:
        model = combo.model()
        item_getter = getattr(model, "item", None)
        if not callable(item_getter):
            return []
        return [
            item.text()
            for index in range(1, model.rowCount())
            if (item := item_getter(index)) is not None
        ]

    def _build_filter_state_from_main(self) -> TableFullscreenFilterState:
        return self._filter_use_cases.build_state(
            search_text=self._mw.search.text(),
            status_options=self._combo_items(self._mw.data_tab.filter_status),
            status_current_text=self._mw.data_tab.filter_status.currentText(),
            year_options=self._combo_items(self._mw.data_tab.filter_year),
            year_current_text=self._mw.data_tab.filter_year.currentText(),
            micro_items=self._checkable_items(self._mw.data_tab.filter_micro),
            micro_checked_items=self._mw.data_tab.filter_micro.checked_items(),
            micro_all_selected=self._mw.data_tab.filter_micro.is_all_selected(),
            eletronico_items=self._checkable_items(self._mw.data_tab.filter_eletronico),
            eletronico_checked_items=self._mw.data_tab.filter_eletronico.checked_items(),
            eletronico_all_selected=self._mw.data_tab.filter_eletronico.is_all_selected(),
        )

    def _build_filter_state_from_dialog(self) -> TableFullscreenFilterState:
        return self._filter_use_cases.build_state(
            search_text=self.search_fs.text(),
            status_options=self._combo_items(self.filter_status_fs),
            status_current_text=self.filter_status_fs.currentText(),
            year_options=self._combo_items(self.filter_year_fs),
            year_current_text=self.filter_year_fs.currentText(),
            micro_items=self._checkable_items(self.filter_micro_fs),
            micro_checked_items=self.filter_micro_fs.checked_items(),
            micro_all_selected=self.filter_micro_fs.is_all_selected(),
            eletronico_items=self._checkable_items(self.filter_eletronico_fs),
            eletronico_checked_items=self.filter_eletronico_fs.checked_items(),
            eletronico_all_selected=self.filter_eletronico_fs.is_all_selected(),
        )

    def _apply_filter_state_to_dialog(self, state: TableFullscreenFilterState):
        self.search_fs.setText(state.search_text)
        self.filter_status_fs.clear()
        self.filter_status_fs.addItems(list(state.status.options))
        self.filter_status_fs.setCurrentText(state.status.current_text)
        self.filter_year_fs.clear()
        self.filter_year_fs.addItems(list(state.year.options))
        self.filter_year_fs.setCurrentText(state.year.current_text)
        self.filter_micro_fs.set_items(list(state.micro.items))
        self.filter_micro_fs.set_checked_items(
            list(state.micro.checked_items),
            all_selected=state.micro.all_selected,
        )
        self.filter_eletronico_fs.set_items(list(state.eletronico.items))
        self.filter_eletronico_fs.set_checked_items(
            list(state.eletronico.checked_items),
            all_selected=state.eletronico.all_selected,
        )

    def _apply_filter_state_to_main(self, state: TableFullscreenFilterState):
        self._mw.search.setText(state.search_text)
        self._mw.data_tab.filter_status.setCurrentText(state.status.current_text)
        self._mw.data_tab.filter_year.setCurrentText(state.year.current_text)
        self._mw.data_tab.filter_micro.set_checked_items(
            list(state.micro.checked_items),
            all_selected=state.micro.all_selected,
        )
        self._mw.data_tab.filter_eletronico.set_checked_items(
            list(state.eletronico.checked_items),
            all_selected=state.eletronico.all_selected,
        )

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

        self._mw.search.blockSignals(True)
        self._mw.data_tab.filter_status.blockSignals(True)
        self._mw.data_tab.filter_year.blockSignals(True)
        self._mw.data_tab.filter_micro.blockSignals(True)
        self._mw.data_tab.filter_eletronico.blockSignals(True)
        try:
            self._apply_filter_state_to_main(self._build_filter_state_from_dialog())
        finally:
            self._mw.search.blockSignals(False)
            self._mw.data_tab.filter_status.blockSignals(False)
            self._mw.data_tab.filter_year.blockSignals(False)
            self._mw.data_tab.filter_micro.blockSignals(False)
            self._mw.data_tab.filter_eletronico.blockSignals(False)
        self._mw.apply_filter()

    def _expand_table_to_fullscreen(self):
        if not self._table:
            return
        header = self._table.horizontalHeader()
        header.setStretchLastSection(False)
        preferred_widths = self._preferred_fullscreen_column_widths()
        if not preferred_widths:
            for i in range(header.count()):
                header.setSectionResizeMode(i, QHeaderView.Stretch)
            return

        for i in range(header.count()):
            header.setSectionResizeMode(i, QHeaderView.Interactive)
        for index, width in preferred_widths.items():
            header.resizeSection(index, width)

    def _restore_table_layout(self):
        if not self._table or self._table_layout_snapshot is None:
            return
        header = self._table.horizontalHeader()
        interactive_mode = int(getattr(QHeaderView.Interactive, "value", QHeaderView.Interactive))
        header.setStretchLastSection(self._table_layout_snapshot.stretch_last_section)
        for i, mode in enumerate(self._table_layout_snapshot.resize_modes):
            header.setSectionResizeMode(i, QHeaderView.ResizeMode(mode))
        for i, size in enumerate(self._table_layout_snapshot.section_sizes):
            if self._table_layout_snapshot.resize_modes[i] == interactive_mode:
                header.resizeSection(i, size)

    def closeEvent(self, event):
        if self._on_close_callback:
            self._on_close_callback(self._content)
        QTimer.singleShot(0, self._restore_table_layout)
        super().closeEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._table:
            QTimer.singleShot(0, self._expand_table_to_fullscreen)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Escape, Qt.Key_F11): self.close()
        super().keyPressEvent(event)
