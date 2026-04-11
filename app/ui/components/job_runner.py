from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app.application.use_cases.runtime_monitoring import RuntimeJobSnapshot
from app.ui.components.job_specs import (
    BackgroundJobSpec,
    BlockingJobSpec,
    DisconnectCallback,
    StopCallback,
)


@dataclass
class TrackedWorker:
    worker: object
    disconnect_callbacks: list[DisconnectCallback]
    stop_callback: Optional[StopCallback]
    wait_ms: int


@dataclass
class RuntimeJobState:
    name: str
    kind: str
    status: str
    label: str
    detail_message: str
    total: int
    progress_value: int
    cancellable: bool
    started_at: str
    finished_at: str = ""

    def to_snapshot(self) -> RuntimeJobSnapshot:
        return RuntimeJobSnapshot(
            name=self.name,
            kind=self.kind,
            status=self.status,
            label=self.label,
            detail_message=self.detail_message,
            total=self.total,
            progress_value=self.progress_value,
            cancellable=self.cancellable,
            started_at=self.started_at,
            finished_at=self.finished_at,
        )


class WindowJobRunner:
    def __init__(self, window):
        self.window = window
        self._busy_depth = 0
        self._busy_job_stack: list[str] = []
        self._cancel_callback: Optional[Callable[[], None]] = None
        self._tracked_workers: dict[str, TrackedWorker] = {}
        self._runtime_jobs: list[RuntimeJobState] = []
        self._active_runtime_jobs: dict[str, RuntimeJobState] = {}
        self._runtime_observers: list[Callable[[], None]] = []

    def begin_busy_operation(
        self,
        message: str,
        *,
        total: Optional[int] = None,
        cancellable: bool = False,
        cancel_callback: Optional[Callable[[], None]] = None,
        job_name: Optional[str] = None,
    ) -> None:
        self._busy_depth += 1
        if job_name:
            self._busy_job_stack.append(job_name)
        if self._busy_depth == 1 and QApplication.overrideCursor() is None:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)

        self.window.progress_bar.setVisible(True)
        if total is None:
            self.window.progress_bar.setRange(0, 0)
        else:
            self.window.progress_bar.setRange(0, max(int(total), 0))
            self.window.progress_bar.setValue(0)

        self._cancel_callback = cancel_callback if cancellable else None
        self.window.progress_cancel_button.setVisible(bool(cancellable and cancel_callback))
        self.window.statusBar().showMessage(message)

    def update_busy_operation(self, value: int, message: Optional[str] = None) -> None:
        if self.window.progress_bar.maximum() != 0:
            self.window.progress_bar.setValue(int(value))
        if message:
            self.window.statusBar().showMessage(message)
        if self._busy_job_stack:
            self._update_runtime_job(
                self._busy_job_stack[-1],
                progress_value=int(value),
                detail_message=message,
            )

    def end_busy_operation(self, message: str = "Pronto", *, job_name: Optional[str] = None) -> None:
        self._busy_depth = max(self._busy_depth - 1, 0)
        resolved_job_name = job_name
        if resolved_job_name is None and self._busy_job_stack:
            resolved_job_name = self._busy_job_stack.pop()
        elif resolved_job_name is not None and resolved_job_name in self._busy_job_stack:
            self._busy_job_stack = [name for name in self._busy_job_stack if name != resolved_job_name]
        if self._busy_depth == 0:
            self.window.progress_bar.setVisible(False)
            self.window.progress_cancel_button.setVisible(False)
            self._cancel_callback = None
            if QApplication.overrideCursor() is not None:
                QApplication.restoreOverrideCursor()
        self.window.statusBar().showMessage(message)

    def cancel_active_operation(self) -> None:
        if self._cancel_callback is not None:
            self._cancel_callback()

    def run_blocking(
        self,
        busy_message: str,
        operation: Callable[[], object],
        *,
        job_name: Optional[str] = None,
        total: Optional[int] = None,
        cancellable: bool = False,
        cancel_callback: Optional[Callable[[], None]] = None,
        success_message: str = "Pronto",
        failure_message: str = "Operacao interrompida.",
    ):
        self.begin_busy_operation(
            busy_message,
            total=total,
            cancellable=cancellable,
            cancel_callback=cancel_callback,
            job_name=job_name or busy_message,
        )
        self._register_runtime_job(
            name=job_name or busy_message,
            kind="blocking",
            label=busy_message,
            total=total,
            cancellable=bool(cancellable and cancel_callback),
            detail_message=busy_message,
        )
        try:
            result = operation()
        except Exception:
            self.mark_job_failed(job_name or busy_message, failure_message)
            self.end_busy_operation(failure_message, job_name=job_name or busy_message)
            raise

        self.mark_job_completed(job_name or busy_message, success_message)
        self.end_busy_operation(success_message, job_name=job_name or busy_message)
        return result

    def run_blocking_spec(self, spec: BlockingJobSpec):
        return self.run_blocking(
            spec.busy_message,
            spec.operation,
            job_name=spec.name or spec.busy_message,
            total=spec.total,
            cancellable=spec.cancellable,
            cancel_callback=spec.cancel_callback,
            success_message=spec.success_message,
            failure_message=spec.failure_message,
        )

    def track_worker(
        self,
        name: str,
        worker: object,
        *,
        disconnect_callbacks: Optional[list[DisconnectCallback]] = None,
        stop_callback: Optional[StopCallback] = None,
        wait_ms: int = 1000,
    ) -> object:
        self.shutdown_worker(name)
        disconnectors = list(disconnect_callbacks or [])

        finished_signal = getattr(worker, "finished", None)
        if finished_signal is not None and hasattr(finished_signal, "connect"):
            def _release_finished_worker():
                if name in self._active_runtime_jobs:
                    self.mark_job_completed(name, "Pronto")
                self.release_worker(name)

            def _disconnect_finished_handler():
                finished_signal.disconnect(_release_finished_worker)

            try:
                finished_signal.connect(_release_finished_worker)
                disconnectors.append(_disconnect_finished_handler)
            except Exception:
                pass

        self._tracked_workers[name] = TrackedWorker(
            worker=worker,
            disconnect_callbacks=disconnectors,
            stop_callback=stop_callback,
            wait_ms=wait_ms,
        )
        return worker

    def start_background_job(self, spec: BackgroundJobSpec) -> object:
        self._register_runtime_job(
            name=spec.name,
            kind="background",
            label=spec.busy_message or spec.name,
            total=spec.total,
            cancellable=bool(spec.cancellable and spec.cancel_callback),
            detail_message=spec.busy_message or spec.name,
        )
        worker = self.track_worker(
            spec.name,
            spec.worker,
            disconnect_callbacks=spec.disconnect_callbacks,
            stop_callback=spec.stop_callback,
            wait_ms=spec.wait_ms,
        )

        if spec.on_tracked is not None:
            spec.on_tracked(worker)

        if spec.busy_message:
            self.begin_busy_operation(
                spec.busy_message,
                total=spec.total,
                cancellable=spec.cancellable,
                cancel_callback=spec.cancel_callback,
                job_name=spec.name,
            )

        if spec.auto_start and hasattr(worker, "start"):
            try:
                worker.start()
            except Exception:
                if spec.busy_message:
                    self.end_busy_operation("Operacao interrompida.", job_name=spec.name)
                self.mark_job_failed(spec.name, "Operacao interrompida.")
                self.shutdown_worker(spec.name)
                raise
        return worker

    def release_worker(self, name: str) -> None:
        self._tracked_workers.pop(name, None)

    def shutdown_worker(self, name: str) -> None:
        tracked = self._tracked_workers.pop(name, None)
        if tracked is None:
            return

        for disconnect in tracked.disconnect_callbacks:
            try:
                disconnect()
            except (TypeError, RuntimeError):
                pass

        worker = tracked.worker
        is_running = getattr(worker, "isRunning", None)
        if callable(is_running) and is_running():
            if tracked.stop_callback is not None:
                try:
                    tracked.stop_callback()
                except Exception:
                    pass
            elif hasattr(worker, "requestInterruption"):
                try:
                    worker.requestInterruption()
                except Exception:
                    pass

            if hasattr(worker, "quit"):
                try:
                    worker.quit()
                except Exception:
                    pass
            if hasattr(worker, "wait"):
                try:
                    worker.wait(tracked.wait_ms)
                except Exception:
                    pass

    def shutdown_all_workers(self) -> None:
        for name in list(self._tracked_workers):
            self.shutdown_worker(name)

    def mark_job_completed(self, name: str, message: str = "Pronto") -> None:
        self._finalize_runtime_job(name, "completed", message)

    def mark_job_failed(self, name: str, message: str) -> None:
        self._finalize_runtime_job(name, "failed", message)

    def mark_job_cancelled(self, name: str, message: str) -> None:
        self._finalize_runtime_job(name, "cancelled", message)

    def list_runtime_jobs(self, *, limit: int = 20) -> list[RuntimeJobSnapshot]:
        jobs = [state.to_snapshot() for state in reversed(self._runtime_jobs)]
        return jobs[: max(limit, 0)]

    def subscribe_runtime_updates(self, callback: Callable[[], None]) -> None:
        if callback not in self._runtime_observers:
            self._runtime_observers.append(callback)

    def _register_runtime_job(
        self,
        *,
        name: str,
        kind: str,
        label: str,
        total: Optional[int],
        cancellable: bool,
        detail_message: str,
    ) -> None:
        state = RuntimeJobState(
            name=name,
            kind=kind,
            status="running",
            label=label,
            detail_message=detail_message,
            total=int(total or 0),
            progress_value=0,
            cancellable=bool(cancellable),
            started_at=self._utc_timestamp(),
        )
        self._runtime_jobs.append(state)
        self._active_runtime_jobs[name] = state
        self._notify_runtime_observers()

    def _update_runtime_job(
        self,
        name: str,
        *,
        progress_value: Optional[int] = None,
        detail_message: Optional[str] = None,
    ) -> None:
        state = self._active_runtime_jobs.get(name)
        if state is None:
            return
        if progress_value is not None:
            state.progress_value = int(progress_value)
        if detail_message:
            state.detail_message = detail_message
        self._notify_runtime_observers()

    def _finalize_runtime_job(self, name: str, status: str, message: str) -> None:
        state = self._active_runtime_jobs.pop(name, None)
        if state is None:
            return
        state.status = status
        state.detail_message = message or state.detail_message
        if not state.finished_at:
            state.finished_at = self._utc_timestamp()
        self._notify_runtime_observers()

    def _notify_runtime_observers(self) -> None:
        for callback in list(self._runtime_observers):
            try:
                callback()
            except Exception:
                continue

    @staticmethod
    def _utc_timestamp() -> str:
        return datetime.now(timezone.utc).isoformat()
