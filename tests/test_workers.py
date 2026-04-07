from app.config import DEFAULT_UPDATE_MANIFEST_URL
from app.ui.components.workers import UpdaterWorker


def test_updater_worker_skips_when_no_source_is_configured():
    worker = UpdaterWorker(update_url="")
    worker.update_url = ""
    emitted = []
    worker.update_available.connect(lambda version, notes: emitted.append((version, notes)))

    worker.run()

    assert emitted == []


def test_updater_worker_uses_default_manifest_url_when_not_overridden(monkeypatch):
    monkeypatch.delenv("COMPENSACOES_UPDATE_URL", raising=False)
    worker = UpdaterWorker(update_url=None)

    assert worker.update_url == DEFAULT_UPDATE_MANIFEST_URL


def test_updater_worker_emits_when_endpoint_reports_newer_version():
    worker = UpdaterWorker(
        update_url="https://example.com/releases/latest.json",
        current_version="1.0.0",
        fetch_json=lambda _url: {
            "version": "1.1.0",
            "notes": "- Melhorias",
            "download_url": "https://example.com/Compensacoes-v1.1.0-win64.zip",
            "sha256": "abc123",
        },
    )
    emitted = []
    details = []
    worker.update_available.connect(lambda version, notes: emitted.append((version, notes)))
    worker.update_ready.connect(lambda payload: details.append(dict(payload)))

    worker.run()

    assert emitted == [("1.1.0", "- Melhorias")]
    assert details == [{
        "version": "1.1.0",
        "notes": "- Melhorias",
        "download_url": "https://example.com/Compensacoes-v1.1.0-win64.zip",
        "homepage_url": "",
        "published_at": "",
        "sha256": "abc123",
        "filename": "",
        "signed": None,
        "signature_mode": "",
    }]


def test_updater_worker_ignores_same_or_older_versions():
    worker = UpdaterWorker(
        update_url="https://example.com/releases/latest.json",
        current_version="1.1.0",
        fetch_json=lambda _url: {"version": "1.1.0", "notes": "- Sem mudancas"},
    )
    emitted = []
    no_update = []
    worker.update_available.connect(lambda version, notes: emitted.append((version, notes)))
    worker.no_update.connect(lambda version: no_update.append(version))

    worker.run()

    assert emitted == []
    assert no_update == ["1.1.0"]


def test_updater_worker_does_not_treat_prerelease_as_newer_than_same_stable():
    worker = UpdaterWorker(update_url="https://example.com/releases/latest.json", current_version="1.0.0")

    assert worker._is_newer_version("1.0.0-beta1", "1.0.0") is False
    assert worker._is_newer_version("1.0.0-rc1", "1.0.0") is False
    assert worker._is_newer_version("1.0.0", "1.0.0-beta1") is True


def test_updater_worker_emits_failure_for_invalid_payload():
    worker = UpdaterWorker(
        update_url="https://example.com/releases/latest.json",
        current_version="1.0.0",
        fetch_json=lambda _url: {"notes": "sem versao"},
    )
    failures = []
    worker.check_failed.connect(lambda message: failures.append(message))

    worker.run()

    assert failures == ["Resposta de atualização sem versão válida."]
