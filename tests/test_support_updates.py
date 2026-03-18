import os
from types import SimpleNamespace

from app.ui.controllers.support_controller import SupportController


class DummyStatusBar:
    def __init__(self):
        self.messages = []

    def showMessage(self, message):
        self.messages.append(message)


class DummyWindow:
    def __init__(self):
        self._status_bar = DummyStatusBar()

    def statusBar(self):
        return self._status_bar


def test_present_update_offer_opens_download_url(monkeypatch):
    window = DummyWindow()
    controller = SupportController(window)
    opened = []

    monkeypatch.setattr(
        "app.ui.controllers.support_controller.QMessageBox.question",
        lambda *args, **kwargs: 16384,
    )
    monkeypatch.setattr(
        "app.ui.controllers.support_controller.QDesktopServices.openUrl",
        lambda url: opened.append(url.toString()),
    )

    controller.present_update_offer(
        {
            "version": "1.1.0",
            "notes": "- Melhorias",
            "download_url": "https://example.com/app.zip",
            "published_at": "2026-03-18T12:00:00Z",
        }
    )

    assert opened == ["https://example.com/app.zip"]
    assert window.statusBar().messages[-1] == "Link da atualizacao aberto no navegador."


def test_check_for_updates_requires_manifest_env(monkeypatch):
    window = DummyWindow()
    controller = SupportController(window)
    messages = []

    monkeypatch.delenv("COMPENSACOES_UPDATE_URL", raising=False)
    monkeypatch.setattr(
        "app.ui.controllers.support_controller.QMessageBox.information",
        lambda *args, **kwargs: messages.append(args[2]),
    )

    controller.check_for_updates()

    assert messages
    assert "COMPENSACOES_UPDATE_URL" in messages[0]


def test_check_for_updates_wires_manual_worker(monkeypatch):
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

    monkeypatch.setenv("COMPENSACOES_UPDATE_URL", "https://example.com/latest.json")
    monkeypatch.setattr("app.ui.controllers.support_controller.UpdaterWorker", FakeWorker)
    monkeypatch.setattr(
        "app.ui.controllers.support_controller.QMessageBox.information",
        lambda *args, **kwargs: events.append(("info", args[1], args[2])),
    )

    controller.check_for_updates()

    assert events[0] == ("start", "https://example.com/latest.json", "1.0.0")
    assert events[1][0] == "info"
    assert "versao mais recente" in events[1][2]
