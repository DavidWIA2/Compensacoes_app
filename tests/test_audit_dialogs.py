import os
import json
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QWidget

from app.application.use_cases.workbook_session import (
    ImportConflictDetail,
    ImportValidationIssue,
    ImportWorkbookAnalysis,
)
from app.services.app_settings import AppSettings
from app.models.compensacao import Compensacao
from app.services.audit_service import AuditEvent
from app.ui.components.dialogs import ImportPreviewDialog, OperationHistoryDialog


def make_record(**overrides) -> Compensacao:
    base = {
        "excel_row": 3,
        "oficio_processo": "123/2026",
        "eletronico": "SIM",
        "caixa": "CX-1",
        "av_tec": "AT-1",
        "compensacao": "10",
        "endereco": "Rua A",
        "microbacia": "Gregorio",
        "compensado": "",
        "uid": "uid-1",
    }
    base.update(overrides)
    return Compensacao(**base)


class MemorySettings:
    def __init__(self):
        self._data = {}

    def value(self, key, default=None):
        return self._data.get(key, default)

    def setValue(self, key, value):
        self._data[key] = value

    def remove(self, key):
        self._data.pop(key, None)


def test_import_preview_dialog_filters_rows_by_status_and_search(qt_app):
    analysis = ImportWorkbookAnalysis(
        import_path="importar.xlsx",
        incoming_records=[
            make_record(excel_row=2, uid="novo-1", av_tec="AT-NEW"),
            make_record(excel_row=3, uid="dup-uid", av_tec="AT-UID"),
            make_record(excel_row=4, uid="dup-av", av_tec="AT-DUP"),
            make_record(excel_row=5, uid="bad-1", av_tec="AT-BAD"),
        ],
        records_to_add=[make_record(excel_row=2, uid="novo-1", av_tec="AT-NEW")],
        skipped_by_uid=1,
        skipped_by_av_tec=1,
        skipped_uid_details=[
            ImportConflictDetail(import_row=3, uid="dup-uid", av_tec="AT-UID", matched_row=10),
        ],
        skipped_av_tec_details=[
            ImportConflictDetail(import_row=4, uid="dup-av", av_tec="AT-DUP", matched_row=11),
        ],
        invalid_issues=[
            ImportValidationIssue(import_row=5, uid="bad-1", av_tec="AT-BAD", message="Preencha Oficio/ Processo."),
        ],
    )

    dialog = ImportPreviewDialog(None, analysis)

    assert dialog.table.rowCount() == 4
    assert dialog.lbl_visible.text() == "Mostrando 4 de 4 itens"
    assert "Conflitos por UID: 1" in dialog.lbl_breakdown.text()
    assert "Conflitos por Av. Tec.: 1" in dialog.lbl_breakdown.text()
    assert "1x Preencha Oficio/ Processo." in dialog.lbl_breakdown.text()

    dialog.filter_status.setCurrentText("Invalido")

    assert dialog.table.rowCount() == 1
    assert dialog.table.item(0, 3).text() == "Invalido"
    assert dialog.lbl_visible.text() == "Mostrando 1 de 4 itens"

    dialog.filter_status.setCurrentText("Todos")
    dialog.search_input.setText("AT-DUP")

    assert dialog.table.rowCount() == 1
    assert dialog.table.item(0, 2).text() == "AT-DUP"
    assert dialog.lbl_visible.text() == "Mostrando 1 de 4 itens"

    dialog.close()


def test_operation_history_dialog_filters_by_action_backup_and_search(qt_app, monkeypatch, tmp_path):
    add_backup = tmp_path / "add.xlsx"
    add_backup.write_text("add", encoding="utf-8")
    edit_backup = tmp_path / "edit.xlsx"
    edit_backup.write_text("edit", encoding="utf-8")

    opened = []
    monkeypatch.setattr(
        "app.ui.components.dialogs.QDesktopServices.openUrl",
        lambda url: opened.append(url.toLocalFile()),
    )

    events = [
        AuditEvent(
            event_id="evt-1",
            timestamp="2026-03-30T10:00:00+00:00",
            workbook_path="C:/tmp/base.xlsx",
            action="add",
            summary="Registro cadastrado: AT-1",
            backup_path=str(add_backup),
            metadata={"uid": "uid-1"},
        ),
        AuditEvent(
            event_id="evt-2",
            timestamp="2026-03-30T11:00:00+00:00",
            workbook_path="C:/tmp/base.xlsx",
            action="import",
            summary="2 registro(s) importado(s)",
            backup_path="",
            metadata={"source_path": "importar.xlsx"},
        ),
        AuditEvent(
            event_id="evt-3",
            timestamp="2026-03-30T12:00:00+00:00",
            workbook_path="C:/tmp/base.xlsx",
            action="edit",
            summary="Registro alterado: AT-99",
            backup_path=str(edit_backup),
            metadata={"uid": "uid-99"},
        ),
        AuditEvent(
            event_id="evt-4",
            timestamp="2026-03-30T13:00:00+00:00",
            workbook_path="C:/tmp/base.xlsx",
            action="delete",
            summary="Registro excluido: AT-77",
            backup_path=str(tmp_path / "missing.xlsx"),
            metadata={"uid": "uid-77"},
        ),
    ]

    dialog = OperationHistoryDialog(None, events)

    assert dialog.table.rowCount() == 4
    assert dialog.lbl_visible.text() == "Mostrando 4 de 4 operacoes | 2 backups disponiveis"
    assert dialog.table.item(0, 0).text() == "30/03/2026 10:00:00"
    assert dialog.table.item(3, 3).text() == "Indisponivel"
    assert "Resumo visivel: 4 operacoes | 2 backups disponiveis | Periodo: Todos" in dialog.lbl_summary.text()

    dialog.filter_backup.setCurrentText("Com backup")

    assert dialog.table.rowCount() == 3
    assert dialog.lbl_visible.text() == "Mostrando 3 de 4 operacoes | 2 backups disponiveis"

    dialog.filter_action.setCurrentText("EDIT")

    assert dialog.table.rowCount() == 1
    assert dialog.selected_event.event_id == "evt-3"
    assert dialog.btn_restore.isEnabled() is True
    assert dialog.btn_open_backup.isEnabled() is True

    dialog.btn_open_backup.click()

    assert [os.path.normcase(os.path.normpath(path)) for path in opened] == [
        os.path.normcase(os.path.normpath(str(edit_backup)))
    ]

    dialog.filter_action.setCurrentText("Todas")
    dialog.filter_backup.setCurrentText("Todos")
    dialog.search_input.setText("importar.xlsx")

    assert dialog.table.rowCount() == 1
    assert dialog.selected_event.event_id == "evt-2"
    assert dialog.btn_restore.isEnabled() is False
    assert dialog.btn_open_backup.isEnabled() is False

    dialog.close()


def test_operation_history_dialog_persists_filters_and_exports_visible_events(qt_app, monkeypatch, tmp_path):
    parent = QWidget()
    parent.settings = AppSettings(MemorySettings())
    saved_export_paths = []
    parent.settings_controller = SimpleNamespace(
        preferred_export_dir=lambda: str(tmp_path),
        save_last_export_dir=lambda path: saved_export_paths.append(path),
    )

    events = [
        AuditEvent(
            event_id="evt-1",
            timestamp="2026-03-28T10:00:00+00:00",
            workbook_path="C:/tmp/base.xlsx",
            action="add",
            summary="Registro cadastrado: AT-1",
            backup_path="C:/tmp/add.xlsx",
            metadata={"uid": "uid-1"},
        ),
        AuditEvent(
            event_id="evt-2",
            timestamp="2026-03-30T11:00:00+00:00",
            workbook_path="C:/tmp/base.xlsx",
            action="edit",
            summary="Registro alterado: AT-99",
            backup_path="C:/tmp/edit.xlsx",
            metadata={"uid": "uid-99"},
        ),
    ]

    export_path = tmp_path / "historico.json"
    monkeypatch.setattr(
        "app.ui.components.dialogs.QFileDialog.getSaveFileName",
        lambda *args, **kwargs: (str(export_path), "JSON (*.json)"),
    )
    monkeypatch.setattr(
        "app.ui.components.dialogs.QMessageBox.information",
        lambda *args, **kwargs: None,
    )

    dialog = OperationHistoryDialog(parent, events)
    dialog.filter_action.setCurrentText("EDIT")
    dialog.filter_period.setCurrentText("Personalizado")
    dialog.date_from.setDate(QDate(2026, 3, 30))
    dialog.date_to.setDate(QDate(2026, 3, 30))
    dialog.search_input.setText("uid-99")

    dialog.export_history()
    dialog.close()

    with open(export_path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)

    assert payload["filters"] == {
        "action": "EDIT",
        "backup": "Todos",
        "period": "Personalizado",
        "date_from": "2026-03-30",
        "date_to": "2026-03-30",
        "search": "uid-99",
    }
    assert "Periodo: 30/03/2026 a 30/03/2026" in payload["summary"]
    assert payload["visible_events"] == 1
    assert [event["event_id"] for event in payload["events"]] == ["evt-2"]
    assert saved_export_paths == [str(export_path)]
    assert parent.settings.operation_history_filter_state() == {
        "action": "EDIT",
        "backup": "Todos",
        "period": "Personalizado",
        "date_from": "2026-03-30",
        "date_to": "2026-03-30",
        "search": "uid-99",
    }

    reopened = OperationHistoryDialog(parent, events)

    assert reopened.filter_action.currentText() == "EDIT"
    assert reopened.filter_backup.currentText() == "Todos"
    assert reopened.filter_period.currentText() == "Personalizado"
    assert reopened.date_from.date().toString("yyyy-MM-dd") == "2026-03-30"
    assert reopened.date_to.date().toString("yyyy-MM-dd") == "2026-03-30"
    assert reopened.search_input.text() == "uid-99"
    assert reopened.table.rowCount() == 1
    assert reopened.selected_event.event_id == "evt-2"

    reopened.btn_clear_filters.click()

    assert reopened.filter_action.currentText() == "Todas"
    assert reopened.filter_backup.currentText() == "Todos"
    assert reopened.filter_period.currentText() == "Todos"
    assert reopened.search_input.text() == ""
    assert reopened.table.rowCount() == 2

    reopened.close()
    parent.close()
