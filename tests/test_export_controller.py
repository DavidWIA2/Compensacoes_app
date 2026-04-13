from types import SimpleNamespace

from app.ui.controllers.export_controller import ExportController


def _make_window(**overrides):
    base = {
        "authoritative_persistence": None,
        "persistence_monitoring_use_cases": None,
        "access_session": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_export_controller_resolves_current_export_user_name_from_authenticated_session():
    window = _make_window(
        access_session=SimpleNamespace(user_email="david.oliveira@saocarlos.sp.gov.br")
    )

    controller = ExportController(window)

    assert controller._current_export_user_name() == "david.oliveira"


def test_export_controller_returns_empty_export_user_name_without_authenticated_email():
    controller = ExportController(_make_window())

    assert controller._current_export_user_name() == ""
