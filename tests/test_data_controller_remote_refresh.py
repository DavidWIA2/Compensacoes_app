from types import SimpleNamespace

from PySide6.QtWidgets import QApplication, QWidget

from app.application.use_cases.local_record_queries import LocalRecordReadResult
from app.services.access_service import AccessEnvironment, AppAccessSession
from app.ui.controllers.data_controller import DataController


def get_app():
    return QApplication.instance() or QApplication([])


def make_production_session(**overrides) -> AppAccessSession:
    base = {
        "environment": AccessEnvironment.PRODUCTION,
        "label": "Producao",
        "auth_mode": "password",
        "user_id": "user-123",
        "user_email": "analista@prefeitura.sp.gov.br",
        "supabase_url": "https://yonvcnnkewzoqwnnmcdx.supabase.co",
        "local_db_path": "C:/tmp/producao.db",
        "local_session_path": "session://banco-local",
        "app_role": "editor",
        "access_token": "token",
        "refresh_token": "refresh-token",
    }
    base.update(overrides)
    return AppAccessSession(**base)


class FakeStatusBar:
    def __init__(self):
        self.messages = []

    def showMessage(self, message):
        self.messages.append(message)


class FakeLocalRecordQueries:
    def build_read_status(self, record_source, *, filtered_records):
        return SimpleNamespace(
            source=getattr(record_source, "source", "sqlite"),
            filtered_records=filtered_records,
        )


class FakePersistence:
    def __init__(self, *, refresh_result=None, record_source=None):
        self.local_record_queries = FakeLocalRecordQueries()
        self.local_mutation_sync = SimpleNamespace()
        self.local_write_authority = SimpleNamespace()
        self.authoritative_write = SimpleNamespace()
        self.refresh_result = refresh_result or SimpleNamespace(refreshed=False, issues=())
        self.record_source = record_source or LocalRecordReadResult(
            source="sqlite",
            records=("remote-record",),
            strategy="sqlite_runtime",
            workbook_path="session://banco-local",
            issues=(),
        )
        self.set_persistence_calls = []
        self.refresh_calls = []
        self.resolve_calls = []

    def set_persistence_service(self, persistence_service):
        self.set_persistence_calls.append(persistence_service)

    def refresh_remote_snapshot_if_production(self, session_path):
        self.refresh_calls.append(session_path)
        return self.refresh_result

    def resolve_runtime_record_source(self, session_path, *, fallback_records):
        self.resolve_calls.append((session_path, tuple(fallback_records)))
        return self.record_source

    def has_local_snapshot(self, _session_path):
        return True


class FakeWindow(QWidget):
    def __init__(self, *, persistence, access_session):
        super().__init__()
        self.authoritative_persistence = persistence
        self.persistence_monitoring_use_cases = None
        self.session_runtime = None
        self.audit_service = object()
        self.persistence_service = object()
        self.access_session = access_session
        self.records = ["cached-record"]
        self.form_controller = SimpleNamespace(has_pending_changes=lambda: False)
        self.shell_controller = SimpleNamespace(current_session_path=lambda: "session://banco-local")
        self._status_bar = FakeStatusBar()
        self.settings_controller = SimpleNamespace(save_last_session_path=lambda _path: None)

    def statusBar(self):
        return self._status_bar

    def run_blocking_spec(self, spec):
        return spec.operation()


def test_data_controller_refreshes_remote_snapshot_in_production():
    get_app()
    persistence = FakePersistence(
        refresh_result=SimpleNamespace(refreshed=True, issues=()),
        record_source=LocalRecordReadResult(
            source="sqlite",
            records=("remote-a", "remote-b"),
            strategy="sqlite_runtime",
            workbook_path="session://banco-local",
            issues=(),
        ),
    )
    window = FakeWindow(persistence=persistence, access_session=make_production_session())
    controller = DataController(window)
    applied = []
    controller._apply_loaded_runtime_state = lambda records, *, sync_snapshot: applied.append((list(records), sync_snapshot))

    refreshed = controller.refresh_production_snapshot_if_stale(force=True)

    assert refreshed is True
    assert persistence.refresh_calls == ["session://banco-local"]
    assert persistence.resolve_calls == [("session://banco-local", ("cached-record",))]
    assert applied == [(["remote-a", "remote-b"], False)]


def test_data_controller_skips_remote_refresh_outside_production():
    get_app()
    persistence = FakePersistence(refresh_result=SimpleNamespace(refreshed=True, issues=()))
    window = FakeWindow(persistence=persistence, access_session=AppAccessSession.local_default())
    controller = DataController(window)

    refreshed = controller.refresh_production_snapshot_if_stale(force=True)

    assert refreshed is False
    assert persistence.refresh_calls == []


def test_data_controller_reuses_loaded_singleton_and_forces_remote_refresh():
    get_app()
    persistence = FakePersistence()
    window = FakeWindow(persistence=persistence, access_session=make_production_session())
    controller = DataController(window)
    calls = []
    controller._ensure_singleton_database_entry = lambda: SimpleNamespace(session_path="session://banco-local")
    controller.refresh_production_snapshot_if_stale = lambda *, force=False: calls.append(force) or True
    controller.load_session = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("nao deveria recarregar via load_session"))

    loaded = controller._load_singleton_database(confirm_discard=False, show_feedback=False)

    assert loaded is True
    assert calls == [True]
