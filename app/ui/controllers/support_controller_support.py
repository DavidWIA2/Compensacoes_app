from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox, QProgressDialog

from app.ui.components.job_specs import BackgroundJobSpec


@dataclass(frozen=True)
class DiagnosticsExportDialogSpec:
    title: str
    default_path: str
    name_filter: str


def build_diagnostics_export_dialog_spec(
    *,
    preferred_export_dir: str,
    fallback_dir: str,
    default_path_builder: Any,
) -> DiagnosticsExportDialogSpec:
    initial_dir = preferred_export_dir or fallback_dir
    return DiagnosticsExportDialogSpec(
        title="Exportar Diagnostico",
        default_path=default_path_builder(initial_dir),
        name_filter="JSON (*.json)",
    )


def build_diagnostics_success_message(path: str) -> str:
    return f"Diagnostico exportado para:\n{path}"


def create_update_progress_dialog(parent: Any, cancel_callback: Any) -> QProgressDialog:
    dialog = QProgressDialog("Baixando atualizacao...", "Cancelar", 0, 100, parent)
    dialog.setWindowTitle("Atualizacao Automatica")
    dialog.setWindowModality(Qt.WindowModal)
    dialog.setMinimumDuration(0)
    dialog.setAutoClose(False)
    dialog.setAutoReset(False)
    dialog.canceled.connect(cancel_callback)
    return dialog


def start_window_background_job(window: Any, spec: BackgroundJobSpec) -> object:
    starter = getattr(window, "start_background_job", None)
    if callable(starter):
        return starter(spec)

    worker = window.track_background_worker(
        spec.name,
        spec.worker,
        disconnect_callbacks=spec.disconnect_callbacks,
        stop_callback=spec.stop_callback,
        wait_ms=spec.wait_ms,
    )
    if spec.on_tracked is not None:
        spec.on_tracked(worker)
    if spec.busy_message:
        window.begin_busy_operation(
            spec.busy_message,
            total=spec.total,
            cancellable=spec.cancellable,
            cancel_callback=spec.cancel_callback,
        )
    if spec.auto_start and hasattr(worker, "start"):
        worker.start()
    return worker


def mark_window_job_state(window: Any, name: str, status: str, message: str) -> None:
    marker_name = {
        "completed": "mark_job_completed",
        "failed": "mark_job_failed",
        "cancelled": "mark_job_cancelled",
    }.get(str(status or "").strip().lower(), "")
    if not marker_name:
        return
    marker = getattr(window, marker_name, None)
    if callable(marker):
        marker(name, message)


def present_support_dialog(parent: Any, kind: str, title: str, message: str) -> None:
    if not title or not message:
        return
    if kind == "warning":
        QMessageBox.warning(parent, title, message)
        return
    if kind == "information":
        QMessageBox.information(parent, title, message)


def apply_support_job_outcome(window: Any, name: str, outcome: Any, *, dialog_kind: str = "") -> None:
    runtime_status = str(getattr(outcome, "runtime_status", "") or "").strip().lower()
    runtime_message = str(getattr(outcome, "runtime_message", "") or "").strip()
    status_bar_message = str(getattr(outcome, "status_bar_message", "") or "").strip()
    dialog_title = str(getattr(outcome, "dialog_title", "") or "").strip()
    dialog_message = str(getattr(outcome, "dialog_message", "") or "").strip()

    if runtime_status:
        mark_window_job_state(window, name, runtime_status, runtime_message or "Pronto")
    present_support_dialog(window, dialog_kind, dialog_title, dialog_message)
    if status_bar_message:
        window.statusBar().showMessage(status_bar_message)
