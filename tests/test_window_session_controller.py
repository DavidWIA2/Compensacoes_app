import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.models.compensacao import Compensacao


def make_record(**overrides) -> Compensacao:
    base = {
        "excel_row": 2,
        "oficio_processo": "123/2026",
        "eletronico": "SIM",
        "caixa": "CX-1",
        "av_tec": "AT-1",
        "compensacao": "10",
        "endereco": "Rua A",
        "microbacia": "",
        "compensado": "",
        "latitude": "",
        "longitude": "",
        "uid": "session-test-uid",
    }
    base.update(overrides)
    return Compensacao(**base)


def test_main_window_session_properties_proxy_state(ui_window_factory):
    window = ui_window_factory()
    record = make_record()

    window.records = [record]
    window.filtered_records = [record]
    window.selected = record
    window.form_plantios = [{"endereco": "Rua do Plantio"}]
    window.last_marker_coords = (-22.9, -43.2)
    window.recent_files = ["C:/dados/base.xlsx"]
    window._record_search_index = {"abc": "record"}
    window._local_record_read_status = {"source": "sqlite"}
    window._local_session_source_status = {"source": "sqlite", "strategy": "sqlite_snapshot"}
    window._local_filter_facets_result = {"source": "sqlite", "microbacias": ("Gregorio",)}
    window._local_filter_facets_status = {"source": "sqlite", "micro_count": 2}
    window._local_mutation_sync_status = {"status": "sqlite", "operation": "edit"}
    window._authoritative_write_status = {"status": "sqlite_primary", "operation": "edit"}
    window._filtered_metrics = {"count_total": 1, "total_geral": 10.0}
    window._persistence_status_report = {"status": "sincronizado", "expected_records": 1}
    window._dashboard_dirty = False
    window._pending_dashboard_metrics = {"count_total": 1}
    marker = object()
    window._dashboard_record_overview = marker

    state = window.session_controller.state
    assert state.records == [record]
    assert state.filtered_records == [record]
    assert state.selected is record
    assert state.form_plantios == [{"endereco": "Rua do Plantio"}]
    assert state.last_marker_coords == (-22.9, -43.2)
    assert state.recent_files == ["C:/dados/base.xlsx"]
    assert state.record_search_index == {"abc": "record"}
    assert state.local_record_read_status == {"source": "sqlite"}
    assert state.local_session_source_status == {"source": "sqlite", "strategy": "sqlite_snapshot"}
    assert state.local_filter_facets_result == {"source": "sqlite", "microbacias": ("Gregorio",)}
    assert state.local_filter_facets_status == {"source": "sqlite", "micro_count": 2}
    assert state.local_mutation_sync_status == {"status": "sqlite", "operation": "edit"}
    assert state.authoritative_write_status == {"status": "sqlite_primary", "operation": "edit"}
    assert state.filtered_metrics == {"count_total": 1, "total_geral": 10.0}
    assert state.persistence_status_report == {"status": "sincronizado", "expected_records": 1}
    assert state.dashboard_dirty is False
    assert state.pending_dashboard_metrics == {"count_total": 1}
    assert state.dashboard_record_overview is marker
    window.close()


def test_window_session_snapshot_restores_previous_state(ui_window_factory):
    window = ui_window_factory()
    record = make_record()
    marker = object()

    window.records = [record]
    window.filtered_records = [record]
    window.selected = record
    window.form_plantios = [{"talhao": 1}]
    window.last_marker_coords = (1.0, 2.0)
    window.recent_files = ["C:/dados/original.xlsx"]
    window._record_search_index = {"PROC": "123/2026"}
    window._local_record_read_status = {"source": "sqlite", "filtered_records": 1}
    window._local_session_source_status = {"source": "session", "issues": ["fallback"]}
    window._local_filter_facets_result = {"source": "sqlite", "microbacias": ("Gregorio",)}
    window._local_filter_facets_status = {"source": "sqlite", "micro_count": 1}
    window._local_mutation_sync_status = {"status": "sqlite", "operation": "delete"}
    window._authoritative_write_status = {"status": "session_fallback", "operation": "import"}
    window._filtered_metrics = {"count_total": 5, "total_geral": 50.0}
    window._persistence_status_report = {"status": "atencao", "expected_records": 5}
    window._dashboard_dirty = False
    window._pending_dashboard_metrics = {"count_total": 5}
    window._dashboard_record_overview = marker

    snapshot = window.session_controller.snapshot()

    window.session_controller.clear_workbook_state()
    window.recent_files = ["C:/dados/outra.xlsx"]
    window._dashboard_dirty = True

    window.session_controller.restore(snapshot)

    assert window.records == [record]
    assert window.filtered_records == [record]
    assert window.selected is record
    assert window.form_plantios == [{"talhao": 1}]
    assert window.last_marker_coords == (1.0, 2.0)
    assert window.recent_files == ["C:/dados/original.xlsx"]
    assert window._record_search_index == {"PROC": "123/2026"}
    assert window._local_record_read_status == {"source": "sqlite", "filtered_records": 1}
    assert window._local_session_source_status == {"source": "session", "issues": ["fallback"]}
    assert window._local_filter_facets_result == {"source": "sqlite", "microbacias": ("Gregorio",)}
    assert window._local_filter_facets_status == {"source": "sqlite", "micro_count": 1}
    assert window._local_mutation_sync_status == {"status": "sqlite", "operation": "delete"}
    assert window._authoritative_write_status == {"status": "session_fallback", "operation": "import"}
    assert window._filtered_metrics == {"count_total": 5, "total_geral": 50.0}
    assert window._persistence_status_report == {"status": "atencao", "expected_records": 5}
    assert window._dashboard_dirty is False
    assert window._pending_dashboard_metrics == {"count_total": 5}
    assert window._dashboard_record_overview is marker
    window.close()
