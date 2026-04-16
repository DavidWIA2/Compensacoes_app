from __future__ import annotations

import os
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QProcess
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication


@dataclass(frozen=True)
class MainWindowClassRegistry:
    data_tab_cls: type
    dashboard_tab_cls: type
    operations_tab_cls: type
    tcra_tab_cls: type
    admin_users_tab_cls: type | None
    updater_cls: type
    microb_name_field: str
    microb_dir: str


@dataclass(frozen=True)
class MainWindowRuntimeBundle:
    settings: Any
    session_runtime: Any
    persistence_service: Any | None
    audit_service: Any
    authoritative_persistence: Any
    persistence_monitoring_use_cases: Any


def calculate_scale_factor(screen_width: int, screen_height: int) -> float:
    factor = min(float(screen_width) / 1920.0, float(screen_height) / 1080.0)
    return max(0.7, factor)


def resolve_primary_screen_dimensions(app: QApplication | None = None) -> tuple[int, int]:
    qt_app = app or QApplication.instance()
    if qt_app is None:
        return 1920, 1080
    screen = qt_app.primaryScreen()
    if screen is None:
        return 1920, 1080
    geometry = screen.availableGeometry() if hasattr(screen, "availableGeometry") else screen.geometry()
    return geometry.width(), geometry.height()


def apply_scaled_application_font(app: QApplication | None, scale_factor: float) -> int:
    if app is None:
        return 0
    font = app.font()
    point_size = max(int(10 * scale_factor), 1)
    font.setPointSize(point_size)
    app.setFont(font)
    return point_size


def apply_window_scaling(window, app: QApplication | None = None) -> float:
    width, height = resolve_primary_screen_dimensions(app)
    scale_factor = calculate_scale_factor(width, height)
    window.scale_factor = scale_factor
    apply_scaled_application_font(app, scale_factor)
    return scale_factor


def apply_window_icon(window, icon_source: str | QIcon) -> str | QIcon:
    if isinstance(icon_source, QIcon):
        if not icon_source.isNull():
            window.setWindowIcon(icon_source)
        return icon_source
    if icon_source and os.path.exists(icon_source):
        window.setWindowIcon(QIcon(icon_source))
    return icon_source


def build_login_relaunch_command() -> tuple[str, list[str], str]:
    if getattr(sys, "frozen", False):
        executable = str(Path(sys.executable).resolve())
        return executable, [], str(Path(executable).parent)

    repo_root = Path(__file__).resolve().parents[2]
    executable = str(Path(sys.executable).resolve())
    return executable, [str(repo_root / "run.py")], str(repo_root)


def relaunch_login_process() -> bool:
    executable, arguments, working_directory = build_login_relaunch_command()
    result = QProcess.startDetached(executable, arguments, working_directory)
    if isinstance(result, tuple):
        return bool(result[0])
    return bool(result)


def configure_window_class_registry(
    window,
    *,
    data_tab_cls,
    dashboard_tab_cls,
    operations_tab_cls,
    tcra_tab_cls,
    admin_users_tab_cls,
    updater_cls,
    microb_name_field: str,
    microb_dir: str,
) -> MainWindowClassRegistry:
    registry = MainWindowClassRegistry(
        data_tab_cls=data_tab_cls,
        dashboard_tab_cls=dashboard_tab_cls,
        operations_tab_cls=operations_tab_cls,
        tcra_tab_cls=tcra_tab_cls,
        admin_users_tab_cls=admin_users_tab_cls,
        updater_cls=updater_cls,
        microb_name_field=microb_name_field,
        microb_dir=microb_dir,
    )
    window.MICROB_NAME_FIELD = registry.microb_name_field
    window.MICROB_DIR = registry.microb_dir
    window._data_tab_cls = registry.data_tab_cls
    window._dashboard_tab_cls = registry.dashboard_tab_cls
    window._operations_tab_cls = registry.operations_tab_cls
    window._tcra_tab_cls = registry.tcra_tab_cls
    window._admin_users_tab_cls = registry.admin_users_tab_cls
    window._updater_cls = registry.updater_cls
    return registry


def build_runtime_bundle(
    *,
    settings_factory,
    qsettings_factory,
    qsettings_org: str,
    qsettings_name: str,
    loader_factory,
    session_runtime_cls,
    persistence_service_factory,
    audit_service_cls,
    monitoring_use_cases_cls,
    authoritative_persistence_cls,
    access_service=None,
    logger=None,
) -> MainWindowRuntimeBundle:
    settings = settings_factory(qsettings_factory(qsettings_org, qsettings_name))
    session_runtime = session_runtime_cls(loader_factory=loader_factory)

    persistence_service = None
    try:
        persistence_service = persistence_service_factory()
    except Exception as exc:
        if logger is not None:
            logger.warning("Falha ao inicializar espelho local em SQLite: %s", exc, exc_info=True)

    audit_service = audit_service_cls(persistence_service=persistence_service)
    monitoring_use_cases = monitoring_use_cases_cls(persistence_service)
    authoritative_persistence = authoritative_persistence_cls(
        session_runtime,
        audit_service,
        persistence_service,
        loader_factory=loader_factory,
        monitoring_use_cases=monitoring_use_cases,
        access_service=access_service,
    )
    resolved_monitoring_use_cases = getattr(
        authoritative_persistence,
        "persistence_monitoring_use_cases",
        monitoring_use_cases,
    )
    return MainWindowRuntimeBundle(
        settings=settings,
        session_runtime=session_runtime,
        persistence_service=persistence_service,
        audit_service=audit_service,
        authoritative_persistence=authoritative_persistence,
        persistence_monitoring_use_cases=resolved_monitoring_use_cases,
    )
