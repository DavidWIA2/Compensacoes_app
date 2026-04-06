from types import SimpleNamespace

from app.application.use_cases.support_operations import UpdateJobOutcome
from app.ui.controllers.support_controller_support import (
    apply_support_job_outcome,
    build_diagnostics_export_dialog_spec,
)


class DummyStatusBar:
    def __init__(self):
        self.messages = []

    def showMessage(self, message):
        self.messages.append(message)


class DummyWindow:
    def __init__(self):
        self.status_bar = DummyStatusBar()
        self.completed = []
        self.failed = []
        self.cancelled = []

    def statusBar(self):
        return self.status_bar

    def mark_job_completed(self, name, message):
        self.completed.append((name, message))

    def mark_job_failed(self, name, message):
        self.failed.append((name, message))

    def mark_job_cancelled(self, name, message):
        self.cancelled.append((name, message))


def test_build_diagnostics_export_dialog_spec_uses_preferred_dir():
    spec = build_diagnostics_export_dialog_spec(
        preferred_export_dir="C:/exports",
        fallback_dir="C:/logs",
        default_path_builder=lambda initial_dir: f"{initial_dir}/diag.json",
    )

    assert spec.title == "Exportar Diagnostico"
    assert spec.default_path == "C:/exports/diag.json"
    assert spec.name_filter == "JSON (*.json)"


def test_apply_support_job_outcome_marks_window_and_updates_status(monkeypatch):
    window = DummyWindow()
    info_calls = []
    monkeypatch.setattr(
        "app.ui.controllers.support_controller_support.QMessageBox.information",
        lambda *args, **kwargs: info_calls.append((args[1], args[2])),
    )
    outcome = UpdateJobOutcome(
        runtime_status="completed",
        runtime_message="Operacao concluida",
        status_bar_message="Tudo certo",
        dialog_title="Atualizacoes",
        dialog_message="Nenhuma atualizacao encontrada.",
    )

    apply_support_job_outcome(window, "manual_update_check", outcome, dialog_kind="information")

    assert window.completed == [("manual_update_check", "Operacao concluida")]
    assert window.statusBar().messages == ["Tudo certo"]
    assert info_calls == [("Atualizacoes", "Nenhuma atualizacao encontrada.")]
