from app.ui.components.workers import UpdaterWorker


def test_updater_worker_skips_when_no_source_is_configured():
    worker = UpdaterWorker(update_url="")
    emitted = []
    worker.update_available.connect(lambda version, notes: emitted.append((version, notes)))

    worker.run()

    assert emitted == []


def test_updater_worker_emits_when_endpoint_reports_newer_version():
    worker = UpdaterWorker(
        update_url="https://example.com/releases/latest.json",
        current_version="1.0.0",
        fetch_json=lambda _url: {"version": "1.1.0", "notes": "- Melhorias"},
    )
    emitted = []
    worker.update_available.connect(lambda version, notes: emitted.append((version, notes)))

    worker.run()

    assert emitted == [("1.1.0", "- Melhorias")]


def test_updater_worker_ignores_same_or_older_versions():
    worker = UpdaterWorker(
        update_url="https://example.com/releases/latest.json",
        current_version="1.1.0",
        fetch_json=lambda _url: {"version": "1.1.0", "notes": "- Sem mudancas"},
    )
    emitted = []
    worker.update_available.connect(lambda version, notes: emitted.append((version, notes)))

    worker.run()

    assert emitted == []
