import os

import pytest

from app.ui.components.job_specs import BackgroundJobSpec, BlockingJobSpec

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class FakeSignal:
    def __init__(self):
        self._handlers = []

    def connect(self, handler):
        self._handlers.append(handler)

    def disconnect(self, handler=None):
        if handler is None:
            self._handlers.clear()
            return
        self._handlers = [item for item in self._handlers if item is not handler]

    def emit(self, *args, **kwargs):
        for handler in list(self._handlers):
            handler(*args, **kwargs)


def test_run_blocking_spec_executes_operation_and_restores_busy_state(ui_window_factory):
    window = ui_window_factory()
    calls = []

    result = window.run_blocking_spec(
        BlockingJobSpec(
            busy_message="Executando...",
            operation=lambda: calls.append("ran") or 42,
            total=3,
            success_message="Concluido",
        )
    )

    assert result == 42
    assert calls == ["ran"]
    assert window.progress_bar.isHidden() is True
    assert window.statusBar().currentMessage() == "Concluido"
    window.close()


def test_start_background_job_tracks_worker_and_routes_cancel_callback(ui_window_factory):
    window = ui_window_factory()
    calls = []
    tracked = []

    class FakeWorker:
        def __init__(self):
            self.finished = FakeSignal()
            self._running = False

        def start(self):
            self._running = True
            calls.append("start")

        def isRunning(self):
            return self._running

    worker = FakeWorker()
    window.start_background_job(
        BackgroundJobSpec(
            name="spec-job",
            worker=worker,
            busy_message="Processando...",
            cancellable=True,
            cancel_callback=lambda: calls.append("cancel"),
            on_tracked=lambda current: tracked.append(current),
        )
    )

    assert calls == ["start"]
    assert tracked == [worker]
    assert window.progress_bar.isHidden() is False
    assert window.progress_cancel_button.isHidden() is False

    window.cancel_active_operation()
    worker.finished.emit()
    window.end_busy_operation("Encerrado")

    assert calls == ["start", "cancel"]
    assert "spec-job" not in window.job_runner._tracked_workers
    assert window.progress_bar.isHidden() is True
    assert window.progress_cancel_button.isHidden() is True
    window.close()


def test_busy_operation_does_not_force_nested_qt_event_processing(ui_window_factory, monkeypatch):
    import app.ui.components.job_runner as job_runner_module

    window = ui_window_factory()
    calls = []
    monkeypatch.setattr(job_runner_module.QApplication, "processEvents", lambda *args, **kwargs: calls.append("process"))

    window.begin_busy_operation("Processando...", total=2, cancellable=True, cancel_callback=lambda: None)
    window.update_busy_operation(1, "Metade")
    window.end_busy_operation("Pronto")

    assert calls == []
    assert window.progress_bar.isHidden() is True
    window.close()


def test_start_background_job_cleans_up_when_worker_start_fails(ui_window_factory):
    window = ui_window_factory()

    class FailingWorker:
        def __init__(self):
            self.finished = FakeSignal()

        def start(self):
            raise RuntimeError("falhou ao iniciar")

        def isRunning(self):
            return False

    with pytest.raises(RuntimeError):
        window.start_background_job(
            BackgroundJobSpec(
                name="failing-job",
                worker=FailingWorker(),
                busy_message="Falhando...",
            )
        )

    assert "failing-job" not in window.job_runner._tracked_workers
    assert window.progress_bar.isHidden() is True
    assert window.progress_cancel_button.isHidden() is True
    window.close()


def test_job_runner_records_runtime_history_for_blocking_jobs(ui_window_factory):
    window = ui_window_factory()

    window.run_blocking_spec(
        BlockingJobSpec(
            name="load-workbook",
            busy_message="Carregando sessão...",
            operation=lambda: "ok",
            success_message="Sessão carregada.",
        )
    )

    jobs = window.list_runtime_jobs(limit=10)
    target_job = next(job for job in jobs if job.name == "load-workbook")

    assert target_job.kind == "blocking"
    assert target_job.status == "completed"
    assert target_job.label == "Carregando sessão..."
    assert target_job.detail_message == "Sessão carregada."
    assert target_job.started_at
    assert target_job.finished_at
    window.close()


def test_job_runner_records_runtime_status_for_background_jobs(ui_window_factory):
    window = ui_window_factory()
    calls = []

    class FakeWorker:
        def __init__(self):
            self.finished = FakeSignal()
            self._running = False

        def start(self):
            self._running = True

        def isRunning(self):
            return self._running

    worker = FakeWorker()
    window.start_background_job(
        BackgroundJobSpec(
            name="sync-runtime",
            worker=worker,
            busy_message="Sincronizando espelho...",
            total=3,
            cancellable=True,
            cancel_callback=lambda: calls.append("cancel"),
        )
    )

    running = next(job for job in window.list_runtime_jobs(limit=10) if job.name == "sync-runtime")
    assert running.name == "sync-runtime"
    assert running.kind == "background"
    assert running.status == "running"
    assert running.cancellable is True

    window.cancel_active_operation()
    assert calls == ["cancel"]

    window.mark_job_cancelled("sync-runtime", "Sincronizacao cancelada.")
    worker._running = False
    worker.finished.emit()
    window.end_busy_operation("Sincronizacao cancelada.")

    finished = next(job for job in window.list_runtime_jobs(limit=10) if job.name == "sync-runtime")
    assert finished.status == "cancelled"
    assert finished.detail_message == "Sincronizacao cancelada."
    assert finished.finished_at
    window.close()
