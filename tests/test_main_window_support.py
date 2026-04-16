from types import SimpleNamespace

from app.ui.main_window_support import (
    apply_scaled_application_font,
    apply_window_scaling,
    build_login_relaunch_command,
    build_runtime_bundle,
    calculate_scale_factor,
    configure_window_class_registry,
)


class FakeFont:
    def __init__(self):
        self.point_size = None

    def setPointSize(self, value):
        self.point_size = value


class FakeGeometry:
    def __init__(self, width: int, height: int):
        self._width = width
        self._height = height

    def width(self):
        return self._width

    def height(self):
        return self._height


class FakeScreen:
    def __init__(self, width: int, height: int):
        self._geometry = FakeGeometry(width, height)

    def geometry(self):
        return self._geometry


class FakeApp:
    def __init__(self, width: int = 1920, height: int = 1080):
        self._font = FakeFont()
        self._screen = FakeScreen(width, height)
        self.applied_font = None

    def font(self):
        return self._font

    def setFont(self, font):
        self.applied_font = font

    def primaryScreen(self):
        return self._screen


class FakeSettings:
    def __init__(self, backend):
        self.backend = backend


class FakeSessionRuntime:
    def __init__(self, *, loader_factory):
        self.loader_factory = loader_factory


class FakeAuditService:
    def __init__(self, *, persistence_service):
        self.persistence_service = persistence_service


class FakeMonitoringUseCases:
    def __init__(self, persistence_service):
        self.persistence_service = persistence_service


class FakeAuthoritativePersistence:
    def __init__(
        self,
        session_runtime,
        audit_service,
        persistence_service,
        *,
        loader_factory,
        monitoring_use_cases,
        access_service=None,
    ):
        self.session_runtime = session_runtime
        self.audit_service = audit_service
        self.persistence_service = persistence_service
        self.loader_factory = loader_factory
        self.persistence_monitoring_use_cases = monitoring_use_cases
        self.access_service = access_service


def test_calculate_scale_factor_respects_floor():
    assert calculate_scale_factor(800, 600) == 0.7
    assert calculate_scale_factor(1920, 1080) == 1.0


def test_apply_scaled_application_font_updates_font_size():
    app = FakeApp()

    point_size = apply_scaled_application_font(app, 1.25)

    assert point_size == 12
    assert app.applied_font is app.font()
    assert app.font().point_size == 12


def test_apply_window_scaling_sets_window_scale_factor():
    app = FakeApp(2560, 1440)
    window = SimpleNamespace(scale_factor=0.0)

    scale_factor = apply_window_scaling(window, app)

    assert round(scale_factor, 3) == round(1440 / 1080, 3)
    assert window.scale_factor == scale_factor


def test_build_login_relaunch_command_uses_python_entrypoint_when_not_frozen():
    executable, arguments, working_directory = build_login_relaunch_command()

    assert executable
    assert arguments[-1].endswith("run.py")
    assert working_directory


def test_configure_window_class_registry_populates_window():
    window = SimpleNamespace()

    configure_window_class_registry(
        window,
        data_tab_cls=dict,
        dashboard_tab_cls=list,
        operations_tab_cls=tuple,
        tcra_tab_cls=set,
        admin_users_tab_cls=frozenset,
        updater_cls=object,
        microb_name_field="Nome_Do_Arquivo",
        microb_dir="C:/tmp/microbacias",
    )

    assert window._data_tab_cls is dict
    assert window._dashboard_tab_cls is list
    assert window._operations_tab_cls is tuple
    assert window._tcra_tab_cls is set
    assert window._admin_users_tab_cls is frozenset
    assert window._updater_cls is object
    assert window.MICROB_NAME_FIELD == "Nome_Do_Arquivo"
    assert window.MICROB_DIR == "C:/tmp/microbacias"


def test_build_runtime_bundle_wires_services():
    logger_calls = []
    backend = object()
    loader_factory = object()
    persistence_service = object()
    access_service = object()

    bundle = build_runtime_bundle(
        settings_factory=FakeSettings,
        qsettings_factory=lambda org, name: (org, name, backend),
        qsettings_org="Org",
        qsettings_name="App",
        loader_factory=loader_factory,
        session_runtime_cls=FakeSessionRuntime,
        persistence_service_factory=lambda: persistence_service,
        audit_service_cls=FakeAuditService,
        monitoring_use_cases_cls=FakeMonitoringUseCases,
        authoritative_persistence_cls=FakeAuthoritativePersistence,
        access_service=access_service,
        logger=SimpleNamespace(warning=lambda *args, **kwargs: logger_calls.append(args)),
    )

    assert bundle.settings.backend == ("Org", "App", backend)
    assert bundle.session_runtime.loader_factory is loader_factory
    assert bundle.persistence_service is persistence_service
    assert bundle.audit_service.persistence_service is persistence_service
    assert bundle.authoritative_persistence.loader_factory is loader_factory
    assert bundle.authoritative_persistence.access_service is access_service
    assert bundle.persistence_monitoring_use_cases.persistence_service is persistence_service
    assert logger_calls == []


def test_build_runtime_bundle_tolerates_sqlite_failure():
    logger_calls = []

    bundle = build_runtime_bundle(
        settings_factory=FakeSettings,
        qsettings_factory=lambda org, name: (org, name),
        qsettings_org="Org",
        qsettings_name="App",
        loader_factory=object(),
        session_runtime_cls=FakeSessionRuntime,
        persistence_service_factory=lambda: (_ for _ in ()).throw(RuntimeError("sqlite indisponivel")),
        audit_service_cls=FakeAuditService,
        monitoring_use_cases_cls=FakeMonitoringUseCases,
        authoritative_persistence_cls=FakeAuthoritativePersistence,
        logger=SimpleNamespace(warning=lambda *args, **kwargs: logger_calls.append(args)),
    )

    assert bundle.persistence_service is None
    assert bundle.audit_service.persistence_service is None
    assert bundle.persistence_monitoring_use_cases.persistence_service is None
    assert logger_calls
