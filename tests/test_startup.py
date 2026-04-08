import os

from app import main as main_module
from app.services.access_service import AccessEnvironment, AppAccessSession


def test_resolve_startup_assets_returns_pair_when_files_exist(monkeypatch):
    monkeypatch.setattr(main_module, "resource_path", lambda *parts: os.path.join(*parts))
    monkeypatch.setattr(
        main_module.os.path,
        "exists",
        lambda path: path in {
            os.path.join("assets", "loading.gif"),
            os.path.join("assets", "Splash.png"),
        },
    )

    gif_path, splash_path = main_module.resolve_startup_assets()

    assert gif_path.endswith("loading.gif")
    assert splash_path.endswith("Splash.png")


def test_create_startup_splash_returns_none_without_assets(monkeypatch):
    monkeypatch.setattr(main_module, "resolve_startup_assets", lambda: (None, None))

    assert main_module.create_startup_splash() is None


def test_create_startup_splash_uses_resolved_assets(monkeypatch):
    captured = []

    class FakeSplash:
        def __init__(self, gif_path, splash_path):
            captured.append((gif_path, splash_path))

    monkeypatch.setattr(main_module, "resolve_startup_assets", lambda: ("gif", "splash"))
    monkeypatch.setattr(main_module, "AnimatedSplashScreen", FakeSplash)

    splash = main_module.create_startup_splash()

    assert captured == [("gif", "splash")]
    assert isinstance(splash, FakeSplash)


def test_request_app_access_returns_none_when_dialog_is_cancelled(monkeypatch):
    monkeypatch.setattr(main_module, "AppSettings", lambda: object())
    monkeypatch.setattr(main_module, "SupabaseAccessService", lambda: object())

    class FakeDialog:
        def __init__(self, **kwargs):
            self.access_session = None

        def exec(self):
            return 0

    monkeypatch.setattr(main_module, "AccessDialog", FakeDialog)

    assert main_module.request_app_access() is None


def test_main_stops_when_access_is_not_granted(monkeypatch):
    calls = []
    apps = []

    class FakeApp:
        def __init__(self, argv):
            self.argv = argv
            self.quit_on_last_window_closed = []
            apps.append(self)

        def setOrganizationName(self, value):
            calls.append(("org", value))

        def setApplicationName(self, value):
            calls.append(("name", value))

        def setApplicationDisplayName(self, value):
            calls.append(("display", value))

        def setWindowIcon(self, value):
            calls.append(("icon", value))

        def setQuitOnLastWindowClosed(self, value):
            self.quit_on_last_window_closed.append(value)

        def exec(self):
            calls.append(("exec", None))
            return 99

    monkeypatch.setattr(main_module, "QApplication", FakeApp)
    monkeypatch.setattr(
        main_module,
        "build_app_icon",
        lambda: type("FakeIcon", (), {"isNull": lambda self: False})(),
    )
    monkeypatch.setattr(main_module, "create_startup_transition_guard", lambda: object())
    monkeypatch.setattr(main_module, "release_startup_transition_guard", lambda guard: None)
    monkeypatch.setattr(main_module, "request_app_access", lambda: None)

    assert main_module.main() == 0
    assert any(tag == "icon" for tag, _ in calls)
    assert ("exec", None) not in calls
    assert apps[0].quit_on_last_window_closed == [False]


def test_main_creates_window_with_access_session(monkeypatch):
    access_session = AppAccessSession(
        environment=AccessEnvironment.DEMO,
        label="Demonstracao",
        auth_mode="demo_local",
        local_db_path="demo.db",
    )
    created = []
    splash_calls = []
    apps = []

    class FakeApp:
        def __init__(self, argv):
            self.argv = argv
            self.quit_on_last_window_closed = []
            apps.append(self)

        def setOrganizationName(self, value):
            return None

        def setApplicationName(self, value):
            return None

        def setApplicationDisplayName(self, value):
            return None

        def setWindowIcon(self, value):
            splash_calls.append(("icon", value))

        def setQuitOnLastWindowClosed(self, value):
            self.quit_on_last_window_closed.append(value)

        def exec(self):
            return 321

    class FakeSplash:
        def show(self):
            splash_calls.append("show")

        def update_status(self, message):
            splash_calls.append(message)

        def finish(self, window):
            splash_calls.append(("finish", window))

    class FakeWindow:
        def __init__(self, access_session=None):
            created.append(access_session)

        def show(self):
            splash_calls.append("window-show")

    monkeypatch.setattr(main_module, "QApplication", FakeApp)
    monkeypatch.setattr(
        main_module,
        "build_app_icon",
        lambda: type("FakeIcon", (), {"isNull": lambda self: False})(),
    )
    monkeypatch.setattr(main_module, "create_startup_transition_guard", lambda: object())
    monkeypatch.setattr(
        main_module,
        "release_startup_transition_guard",
        lambda guard: splash_calls.append(("guard-release", guard)),
    )
    monkeypatch.setattr(main_module, "request_app_access", lambda: access_session)
    monkeypatch.setattr(main_module, "create_startup_splash", lambda: FakeSplash())
    monkeypatch.setattr(main_module, "register_tile_scheme", lambda: splash_calls.append("register-tile"))
    monkeypatch.setattr(main_module, "install_tile_scheme", lambda: splash_calls.append("install-tile"))
    monkeypatch.setattr(main_module, "MainWindow", FakeWindow)

    result = main_module.main()

    assert result == 321
    assert created == [access_session]
    assert "register-tile" in splash_calls
    assert "install-tile" in splash_calls
    assert apps[0].quit_on_last_window_closed == [False, True]


def test_main_reports_error_when_main_window_fails_to_open(monkeypatch):
    access_session = AppAccessSession(
        environment=AccessEnvironment.PRODUCTION,
        label="Produção",
        auth_mode="password",
        user_email="admin@saocarlos.sp.gov.br",
    )
    apps = []
    critical_calls = []

    class FakeApp:
        def __init__(self, argv):
            self.argv = argv
            self.quit_on_last_window_closed = []
            apps.append(self)

        def setOrganizationName(self, value):
            return None

        def setApplicationName(self, value):
            return None

        def setApplicationDisplayName(self, value):
            return None

        def setWindowIcon(self, value):
            return None

        def setQuitOnLastWindowClosed(self, value):
            self.quit_on_last_window_closed.append(value)

        def exec(self):
            return 321

    class FakeSplash:
        def show(self):
            return None

        def update_status(self, message):
            return None

        def close(self):
            critical_calls.append("splash-close")

    monkeypatch.setattr(main_module, "QApplication", FakeApp)
    monkeypatch.setattr(
        main_module,
        "build_app_icon",
        lambda: type("FakeIcon", (), {"isNull": lambda self: False})(),
    )
    monkeypatch.setattr(main_module, "create_startup_transition_guard", lambda: object())
    monkeypatch.setattr(
        main_module,
        "release_startup_transition_guard",
        lambda guard: critical_calls.append("guard-release"),
    )
    monkeypatch.setattr(main_module, "request_app_access", lambda: access_session)
    monkeypatch.setattr(main_module, "create_startup_splash", lambda: FakeSplash())
    monkeypatch.setattr(main_module, "register_tile_scheme", lambda: None)
    monkeypatch.setattr(main_module, "install_tile_scheme", lambda: None)
    monkeypatch.setattr(main_module, "MainWindow", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(
        main_module.QMessageBox,
        "critical",
        lambda *args: critical_calls.append(args[2]),
    )

    result = main_module.main()

    assert result == 1
    assert apps[0].quit_on_last_window_closed == [False]
    assert any("boom" in str(call) for call in critical_calls)
