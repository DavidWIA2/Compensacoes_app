from app.application.use_cases.session_startup_use_cases import build_singleton_session_startup_plan


def test_session_startup_plan_prefers_legacy_bootstrap():
    plan = build_singleton_session_startup_plan(
        pending_legacy_source_path="C:/dados/ultima.xlsx",
        singleton_session_path="session://banco-local",
    )

    assert plan.should_bootstrap_legacy is True
    assert plan.source_path == "C:/dados/ultima.xlsx"


def test_session_startup_plan_can_load_existing_singleton():
    plan = build_singleton_session_startup_plan(
        pending_legacy_source_path="",
        singleton_session_path="session://banco-local",
    )

    assert plan.should_load_singleton is True
    assert plan.singleton_path == "session://banco-local"


def test_session_startup_plan_ignores_legacy_bootstrap_when_disabled():
    plan = build_singleton_session_startup_plan(
        pending_legacy_source_path="C:/dados/ultima.xlsx",
        singleton_session_path="session://banco-local",
        allow_legacy_bootstrap=False,
    )

    assert plan.should_bootstrap_legacy is False
    assert plan.should_load_singleton is True
    assert plan.singleton_path == "session://banco-local"


def test_session_startup_plan_can_be_noop():
    plan = build_singleton_session_startup_plan(
        pending_legacy_source_path="",
        singleton_session_path="",
    )

    assert plan.is_noop is True
