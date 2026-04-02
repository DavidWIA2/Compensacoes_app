from app import __version__ as APP_VERSION
from app.config import DEFAULT_UPDATE_MANIFEST_URL
from app.ui.controllers.support_controller import SupportController


class DummyStatusBar:
    def __init__(self):
        self.messages = []

    def showMessage(self, message):
        self.messages.append(message)


class DummyFormController:
    def __init__(self, allow_discard=True):
        self.allow_discard = allow_discard
        self.calls = []

    def confirm_discard_changes(self, action_text):
        self.calls.append(action_text)
        return self.allow_discard


class DummyWindow:
    def __init__(self):
        self._status_bar = DummyStatusBar()
        self.form_controller = DummyFormController()
        self._skip_close_discard_confirmation = False
        self.closed = False
        self.busy_events = []
        self.tracked_workers = []
        self.released_workers = []

    def statusBar(self):
        return self._status_bar

    def begin_busy_operation(self, message, *, total=None, cancellable=False, cancel_callback=None):
        self.busy_events.append(("begin", message, total, cancellable, bool(cancel_callback)))

    def update_busy_operation(self, value, message=None):
        self.busy_events.append(("update", value, message))

    def end_busy_operation(self, message="Pronto"):
        self.busy_events.append(("end", message))

    def track_background_worker(self, name, worker, **kwargs):
        self.tracked_workers.append((name, worker))
        return worker

    def release_background_worker(self, name):
        self.released_workers.append(name)

    def close(self):
        self.closed = True


def test_present_update_offer_opens_download_url_when_auto_update_is_not_supported(monkeypatch):
    window = DummyWindow()
    controller = SupportController(window)
    opened = []
    prompts = []
    default_buttons = []

    monkeypatch.setattr(controller, "_can_automatically_apply_update", lambda payload: False)
    monkeypatch.setattr(
        "app.ui.controllers.support_controller.QMessageBox.question",
        lambda *args, **kwargs: prompts.append(args[2]) or default_buttons.append(args[4]) or 16384,
    )
    monkeypatch.setattr(
        "app.ui.controllers.support_controller.QDesktopServices.openUrl",
        lambda url: opened.append(url.toString()),
    )

    controller.present_update_offer(
        {
            "version": "1.1.0",
            "notes": "- Melhorias",
            "download_url": "https://example.com/app.exe",
            "published_at": "2026-03-18T12:00:00Z",
            "filename": "Compensacoes-Setup-v1.1.0-win64.exe",
            "sha256": "abc123",
            "signed": False,
        }
    )

    assert opened == ["https://example.com/app.exe"]
    assert "Arquivo: Compensacoes-Setup-v1.1.0-win64.exe" in prompts[0]
    assert "SHA-256: abc123" in prompts[0]
    assert "Assinatura digital: ausente nesta release." in prompts[0]
    assert default_buttons == [16384]
    assert window.statusBar().messages[-1] == "Link da atualizacao aberto no navegador."


def test_present_update_offer_starts_automatic_update_when_supported(monkeypatch):
    window = DummyWindow()
    controller = SupportController(window)
    started = []
    default_buttons = []

    monkeypatch.setattr(controller, "_can_automatically_apply_update", lambda payload: True)
    monkeypatch.setattr(controller, "begin_automatic_update", lambda payload: started.append(dict(payload)))
    monkeypatch.setattr(
        "app.ui.controllers.support_controller.QMessageBox.question",
        lambda *args, **kwargs: default_buttons.append(args[4]) or 16384,
    )

    controller.present_update_offer(
        {
            "version": "1.1.0",
            "notes": "- Melhorias",
            "download_url": "https://example.com/app.exe",
            "filename": "Compensacoes-Setup-v1.1.0-win64.exe",
            "sha256": "abc123",
        }
    )

    assert started == [{
        "version": "1.1.0",
        "notes": "- Melhorias",
        "download_url": "https://example.com/app.exe",
        "filename": "Compensacoes-Setup-v1.1.0-win64.exe",
        "sha256": "abc123",
    }]
    assert default_buttons == [16384]


def test_check_for_updates_uses_default_manifest_url(monkeypatch):
    window = DummyWindow()
    controller = SupportController(window)
    events = []

    class FakeSignal:
        def __init__(self):
            self.handlers = []

        def connect(self, handler):
            self.handlers.append(handler)

        def emit(self, *args):
            for handler in list(self.handlers):
                handler(*args)

    class FakeWorker:
        def __init__(self, update_url=None, current_version=None):
            self.update_url = update_url
            self.current_version = current_version
            self.update_ready = FakeSignal()
            self.no_update = FakeSignal()
            self.check_failed = FakeSignal()
            self.finished = FakeSignal()
            self._running = False

        def isRunning(self):
            return self._running

        def start(self):
            events.append(("start", self.update_url, self.current_version))
            self._running = True
            self.no_update.emit(self.current_version)
            self._running = False
            self.finished.emit()

    monkeypatch.delenv("COMPENSACOES_UPDATE_URL", raising=False)
    monkeypatch.setattr("app.ui.controllers.support_controller.UpdaterWorker", FakeWorker)
    monkeypatch.setattr(
        "app.ui.controllers.support_controller.QMessageBox.information",
        lambda *args, **kwargs: events.append(("info", args[1], args[2])),
    )

    controller.check_for_updates()

    assert events[0] == ("start", DEFAULT_UPDATE_MANIFEST_URL, APP_VERSION)
    assert events[1][0] == "info"
    assert "versao mais recente" in events[1][2]
    assert window.busy_events[0][0] == "begin"
    assert window.busy_events[-1] == ("end", "Verificacao de atualizacoes concluida.")
    assert window.released_workers == ["manual_update_check"]


def test_begin_automatic_update_wires_download_worker(monkeypatch):
    window = DummyWindow()
    controller = SupportController(window)
    events = []

    class FakeSignal:
        def __init__(self):
            self.handlers = []

        def connect(self, handler):
            self.handlers.append(handler)

        def emit(self, *args):
            for handler in list(self.handlers):
                handler(*args)

    class FakeProgressDialog:
        def __init__(self):
            self.shown = False
            self.closed = False
            self.values = []
            self.labels = []
            self.canceled = FakeSignal()

        def show(self):
            self.shown = True

        def close(self):
            self.closed = True

        def deleteLater(self):
            return None

        def setLabelText(self, text):
            self.labels.append(text)

        def setValue(self, value):
            self.values.append(value)

    class FakeWorker:
        def __init__(self, details, current_pid=None, current_executable=None):
            self.details = details
            self.current_pid = current_pid
            self.current_executable = current_executable
            self.progress = FakeSignal()
            self.staged = FakeSignal()
            self.failed = FakeSignal()
            self.cancelled = FakeSignal()
            self.finished = FakeSignal()
            self._running = False

        def isRunning(self):
            return self._running

        def start(self):
            events.append(("start", self.details["version"], self.current_pid, self.current_executable))
            self._running = True

        def requestInterruption(self):
            events.append(("interrupt",))

    monkeypatch.setattr(controller, "_can_automatically_apply_update", lambda payload: True)
    monkeypatch.setattr(controller, "_create_update_progress_dialog", lambda: FakeProgressDialog())
    monkeypatch.setattr("app.ui.controllers.support_controller.UpdateInstallerWorker", FakeWorker)

    controller.begin_automatic_update(
        {
            "version": "1.1.0",
            "download_url": "https://example.com/app.exe",
            "filename": "Compensacoes-Setup-v1.1.0-win64.exe",
            "sha256": "abc123",
        }
    )

    assert events[0][0] == "start"
    assert events[0][1] == "1.1.0"
    assert controller._update_progress_dialog is not None
    assert controller._update_progress_dialog.shown is True
    assert window.busy_events[0] == ("begin", "Baixando atualizacao automatica...", 100, True, True)
    assert window.tracked_workers and window.tracked_workers[0][0] == "automatic_update"


def test_on_auto_update_staged_launches_installer_and_closes_window(monkeypatch):
    window = DummyWindow()
    controller = SupportController(window)
    launched = []

    monkeypatch.setattr(
        "app.ui.controllers.support_controller.launch_update_installer",
        lambda path: launched.append(path),
    )

    controller._on_auto_update_staged({"launcher_path": "C:/tmp/install_update.ps1"})

    assert launched == ["C:/tmp/install_update.ps1"]
    assert window.form_controller.calls == ["instalar a atualizacao"]
    assert window._skip_close_discard_confirmation is True
    assert window.closed is True


def test_on_auto_update_staged_respects_discard_prompt(monkeypatch):
    window = DummyWindow()
    window.form_controller.allow_discard = False
    controller = SupportController(window)
    launched = []

    monkeypatch.setattr(
        "app.ui.controllers.support_controller.launch_update_installer",
        lambda path: launched.append(path),
    )

    controller._on_auto_update_staged({"launcher_path": "C:/tmp/install_update.ps1"})

    assert launched == []
    assert window.closed is False
    assert window._skip_close_discard_confirmation is False
    assert window.statusBar().messages[-1] == "Atualizacao pronta, mas instalacao cancelada pelo usuario."
