import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6 import QtWidgets
from PySide6.QtCore import QItemSelectionModel, QThread, Signal
from PySide6.QtWidgets import QApplication, QMessageBox

from app.application.use_cases.local_record_queries import LocalRecordReadStatus
from app.application.use_cases.persistence_monitoring import PersistenceRecordOverviewReport
from app.models.compensacao import Compensacao
from app.ui.controllers.form_controller_support import FormValidationPresentation
from app.ui.main_window import MainWindow
from app.ui.tabs.data_tab import DataTab


class MockQWebEngineView(QtWidgets.QWidget):
    loadFinished = Signal(bool)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._page = SimpleNamespace(runJavaScript=lambda *a: None)

    def setPage(self, page):
        self._page = page

    def page(self):
        return self._page

    def load(self, url):
        return None

    def setUrl(self, url):
        return None


class MockDashboardTab(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.btn_export_pdf = QtWidgets.QPushButton("Export PDF")
        self.btn_export_diagnostics = QtWidgets.QPushButton("Export Diagnostics")

    def update_dashboard(self, *args, **kwargs):
        return None

    def apply_theme(self, theme):
        return None

    def export_images(self):
        return "pie.png", "bar.png"


class NoopUpdaterWorker(QThread):
    update_available = Signal(str, str)

    def start(self, *args, **kwargs):
        return None

    def quit(self):
        return None

    def wait(self, *args, **kwargs):
        return True


def get_app():
    return QApplication.instance() or QApplication([])


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
        "uid": "test-uid-123",
    }
    base.update(overrides)
    return Compensacao(**base)


@pytest.fixture(autouse=True)
def phase2_mocks(monkeypatch, tmp_path):
    get_app()
    import app.ui.components.ui_utils as ui_utils_module
    import app.ui.controllers.data_controller as data_controller_module
    import app.ui.controllers.form_controller as form_controller_module
    import app.ui.controllers.map_controller as map_controller_module
    import app.ui.main_window as main_window_module
    from app.services.sqlite_mirror_service import SqliteMirrorService

    monkeypatch.setattr("app.ui.tabs.data_tab.QWebEngineView", MockQWebEngineView)
    monkeypatch.setattr("app.ui.main_window.DashboardTab", MockDashboardTab)
    monkeypatch.setattr(main_window_module, "UpdaterWorker", NoopUpdaterWorker)
    monkeypatch.setattr(MainWindow, "_apply_theme", lambda self: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: None)
    monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kwargs: None)
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Yes)
    monkeypatch.setattr(ui_utils_module, "msg_confirm", lambda *args, **kwargs: True)
    monkeypatch.setattr(data_controller_module, "msg_confirm", lambda *args, **kwargs: True)
    monkeypatch.setattr(form_controller_module, "msg_confirm", lambda *args, **kwargs: True)
    monkeypatch.setattr(map_controller_module, "msg_confirm", lambda *args, **kwargs: True)
    monkeypatch.setattr(main_window_module, "msg_confirm", lambda *args, **kwargs: True)
    monkeypatch.setattr(DataTab, "load_map", lambda self: None)
    monkeypatch.setattr(
        main_window_module,
        "SqliteMirrorService",
        lambda *args, **kwargs: SqliteMirrorService(db_path=tmp_path / "phase2-mirror.db"),
    )

    class GlobalMockSettings:
        def __init__(self, *args, **kwargs):
            return None

        def value(self, key, default=""):
            return default

        def setValue(self, key, val):
            return None

        def remove(self, key):
            return None

    monkeypatch.setattr("app.ui.main_window.QSettings", GlobalMockSettings)


def test_window_chrome_summarizes_loaded_session():
    window = MainWindow()
    records = [
        make_record(oficio_processo="PROC-1", av_tec="AT-1", uid="u-1"),
        make_record(excel_row=3, oficio_processo="PROC-2", av_tec="AT-2", uid="u-2"),
    ]
    window.session_runtime.path = window.persistence_service.ensure_singleton_session().session_path
    window.records = list(records)
    window.filtered_records = [records[0]]
    window.selected = records[0]
    window.search.setText("PROC-1")

    window._refresh_window_chrome()

    assert "Base local" in window.windowTitle()
    assert "(1/2)" in window.windowTitle()
    assert window.session_file_label.text() == "Fonte: Banco local"
    assert window.session_records_label.text() == "Registros: 1 de 2"
    assert window.session_sync_label.text() == "Sincronia: local"
    assert window.session_write_label.text() == "Escrita: aguardando"
    assert window.session_selection_label.text() == "Selecionado: AT-1"
    assert window.session_records_label.toolTip() == "Busca atual: PROC-1"
    window.close()


def test_window_chrome_shows_distinct_process_counts_for_compensacoes():
    window = MainWindow()
    window.resize(1920, 1080)
    window.show()
    QApplication.processEvents()
    records = [
        make_record(oficio_processo="PROC-1", uid="u-1"),
        make_record(excel_row=3, oficio_processo="PROC-1", uid="u-2", av_tec="AT-2"),
        make_record(excel_row=4, oficio_processo="PROC-2", uid="u-3", av_tec="AT-3"),
        make_record(excel_row=5, oficio_processo="PROC-3", uid="u-4", av_tec="AT-4"),
    ]
    window.records = list(records)
    window.filtered_records = [records[0], records[2]]

    window._refresh_window_chrome()

    assert window.session_records_label.text() == "Registros: 2 de 4"
    assert window.session_processes_label.text() == "Processos/oficios: 2 de 3"
    assert window.shell_controller._process_status_requested_visible is True
    assert "Linhas repetidas" in window.session_processes_label.toolTip()
    window.close()


def test_window_chrome_uses_tcra_counts_when_tcra_tab_is_active():
    window = MainWindow()
    window.resize(1920, 1080)
    window.show()
    QApplication.processEvents()
    window.tcra_tab.handle_tab_activated = lambda schedule_fit=False: None
    window.tcra_tab.search_input.blockSignals(True)
    window.tcra_tab.search_input.setText("Aracy")
    window.tcra_tab.search_input.blockSignals(False)
    window.tcra_tab.all_tcras = [object(), object(), object()]
    window.tcra_tab.filtered_tcras = [object(), object()]

    window.tabs.setCurrentIndex(1)
    window._on_tab_changed(1)
    QApplication.processEvents()

    assert "(2/3)" in window.windowTitle()
    assert window.session_records_label.text() == "Registros: 2 de 3"
    assert window.session_records_label.toolTip() == "Busca atual: Aracy"
    assert window.shell_controller._process_status_requested_visible is False
    window.close()


def test_window_chrome_marks_snapshot_only_sessions(monkeypatch):
    window = MainWindow()
    window.session_runtime.path = "session://banco-local"
    monkeypatch.setattr(
        window.authoritative_persistence,
        "resolve_session_availability",
        lambda _path: SimpleNamespace(
            path="session://banco-local",
            display_label="Banco local",
            detail_message="Cache local sincronizado disponível em Banco local.",
        ),
    )

    window._refresh_window_chrome()

    assert window.session_file_label.text() == "Fonte: Banco local"
    assert "Cache local sincronizado" in window.session_file_label.toolTip()
    window.close()


def test_window_chrome_prefers_operational_status_counts_over_session_lists():
    window = MainWindow()
    window.session_runtime.path = os.path.join("C:\\base", "compensacoes.xlsx")
    window.records = [make_record(uid="u-1")]
    window.filtered_records = [make_record(uid="u-1")]
    window._local_session_source_status = LocalRecordReadStatus(
        status="sqlite",
        source="sqlite",
        strategy="sqlite_snapshot",
        workbook_path="dummy.xlsx",
        synced_at="2026-03-31T12:00:00+00:00",
        mirrored_records=4,
        session_records=1,
        filtered_records=4,
    )
    window._local_record_read_status = LocalRecordReadStatus(
        status="sqlite",
        source="sqlite",
        strategy="sqlite_query",
        workbook_path="dummy.xlsx",
        synced_at="2026-03-31T12:00:00+00:00",
        mirrored_records=4,
        session_records=4,
        filtered_records=2,
    )

    window._refresh_window_chrome()

    assert "(2/4)" in window.windowTitle()
    assert window.session_records_label.text() == "Registros: 2 de 4"
    window.close()


def test_window_chrome_keeps_zero_when_filters_other_than_search_empty():
    window = MainWindow()
    window.session_runtime.path = os.path.join("C:\\base", "compensacoes.xlsx")
    window.records = [make_record(uid="u-1")]
    window.filtered_records = []
    window._local_session_source_status = LocalRecordReadStatus(
        status="sqlite",
        source="sqlite",
        strategy="sqlite_snapshot",
        workbook_path="dummy.xlsx",
        synced_at="2026-03-31T12:00:00+00:00",
        mirrored_records=4,
        session_records=4,
        filtered_records=4,
    )
    window._local_record_read_status = LocalRecordReadStatus(
        status="sqlite",
        source="sqlite",
        strategy="sqlite_query",
        workbook_path="dummy.xlsx",
        synced_at="2026-03-31T12:00:00+00:00",
        mirrored_records=4,
        session_records=4,
        filtered_records=0,
    )
    window.data_tab.filter_status.setCurrentText("Compensados")

    window._refresh_window_chrome()

    assert "(0/4)" in window.windowTitle()
    assert window.session_records_label.text() == "Registros: 0 de 4"
    window.close()


def test_dirty_form_refreshes_window_chrome(monkeypatch):
    real_exists = os.path.exists
    monkeypatch.setattr(os.path, "exists", lambda path: True if path == "dummy.xlsx" else real_exists(path))

    window = MainWindow()
    record = make_record(oficio_processo="PROC-9", av_tec="AT-9", uid="u-9")
    window.session_runtime.path = "dummy.xlsx"
    window.records = [record]
    window.filtered_records = [record]
    window.selected = record
    window._fill_form(record)

    window.data_tab.in_comp.setText("99")

    assert window.isWindowModified() is True
    assert "Base local" in window.windowTitle()
    assert "(1/1)" in window.windowTitle()
    assert window.form_state_label.text() == "Alterações pendentes"
    assert window.session_selection_label.text() == "Selecionado: AT-9"
    window.close()


def test_form_feedback_uses_compact_top_toolbar():
    window = MainWindow()
    data_tab = window.data_tab

    assert data_tab.actions_row.indexOf(data_tab.lbl_form_feedback) >= 0
    assert data_tab.right_panel.layout().indexOf(data_tab.lbl_form_feedback) == -1
    assert data_tab.right_panel.layout().indexOf(data_tab.lbl_form_geocode) == -1
    assert data_tab.lbl_form_feedback.wordWrap() is False
    assert data_tab.lbl_form_geocode.wordWrap() is False
    assert data_tab.lbl_form_feedback.minimumWidth() >= 260

    window.form_controller._apply_validation_feedback(
        FormValidationPresentation(
            severity="success",
            summary_text="Cadastro consistente para seguir.",
            detail_text="Geocodificação: Buscar Endereço pode revisar o ponto principal do cadastro.",
            duplicate_text="",
            geocode_text="Geocodificação: Buscar Endereço pode revisar o ponto principal do cadastro.",
        )
    )

    assert "\n" not in data_tab.lbl_form_feedback.text()
    assert data_tab.lbl_form_feedback.isHidden() is False
    assert " | " in data_tab.lbl_form_feedback.text()
    assert "Geocodificação" in data_tab.lbl_form_feedback.text()
    assert data_tab.lbl_form_feedback.toolTip().startswith("Cadastro consistente")
    assert "\n" not in data_tab.lbl_form_geocode.text()
    assert data_tab.lbl_form_geocode.isVisible() is False
    assert data_tab.lbl_form_feedback.maximumHeight() <= max(int(24 * window.scale_factor), 22)
    window.close()


def test_window_chrome_shows_authoritative_write_status():
    window = MainWindow()
    window.session_runtime.path = os.path.join("C:\\base", "compensacoes.xlsx")
    window._authoritative_write_status = type(
        "WriteStatus",
        (),
        {
            "status": "sqlite_primary",
            "operation": "import",
            "finalized": True,
            "issues": (),
        },
    )()

    window._refresh_window_chrome()

    assert window.session_sync_label.text() == "Sincronia: local"
    assert window.session_write_label.text() == "Escrita: SQLite + cache"
    assert "Última operação: import" in window.session_write_label.toolTip()
    assert "Identidade final reconciliada após a gravação." in window.session_write_label.toolTip()
    window.close()


def test_dashboard_render_uses_persistence_micro_palette_keys():
    window = MainWindow()
    captured = []
    window.records = [
        make_record(uid="u-1", microbacia="Sessao A"),
        make_record(excel_row=3, uid="u-2", microbacia="Sessao B"),
    ]
    window._dashboard_record_overview = PersistenceRecordOverviewReport(
        status="sincronizado",
        workbook_path="dummy.xlsx",
        synced_at="2026-03-31T12:00:00+00:00",
        total_records=4,
        compensados_count=1,
        pendentes_count=3,
        records_with_plantios_count=0,
        records_without_microbacia_count=0,
        records_without_coordinates_count=0,
        top_microbacias=(("SQLite A", 3), ("SQLite B", 1)),
    )
    window.tabs.setCurrentWidget(window.dash_tab)
    window.dash_tab.update_dashboard = lambda *args, **kwargs: captured.append((args, kwargs))

    window._update_dashboard_view(
        {
            "total_geral": 10,
            "total_pendente": 7,
            "total_compensado": 3,
            "count_total": 4,
            "pend_micro_sorted": [("SQLite B", 2), ("Filtro C", 1)],
        }
    )

    assert len(captured) == 1
    assert captured[0][0][2] == ["SQLite A", "SQLite B", "Filtro C"]
    window.close()


def test_dashboard_render_can_resolve_report_through_shell_controller(monkeypatch):
    window = MainWindow()
    captured = []
    report = PersistenceRecordOverviewReport(
        status="sincronizado",
        workbook_path="dummy.xlsx",
        synced_at="2026-03-31T12:00:00+00:00",
        total_records=3,
        compensados_count=1,
        pendentes_count=2,
        records_with_plantios_count=0,
        records_without_microbacia_count=0,
        records_without_coordinates_count=0,
        top_microbacias=(("SQLite Only", 3),),
    )
    window.tabs.setCurrentWidget(window.dash_tab)
    window.dash_tab.update_dashboard = lambda *args, **kwargs: captured.append((args, kwargs))
    monkeypatch.setattr(
        window.shell_controller,
        "resolved_dashboard_record_overview",
        lambda **kwargs: report,
    )

    window._update_dashboard_view(
        {
            "total_geral": 10,
            "total_pendente": 7,
            "total_compensado": 3,
            "count_total": 4,
            "pend_micro_sorted": [("Filtro C", 1)],
        }
    )

    assert len(captured) == 1
    assert captured[0][0][2] == ["SQLite Only", "Filtro C"]
    assert captured[0][0][3] is report
    window.close()


def test_help_menu_exposes_update_action():
    window = MainWindow()

    assert window.action_check_updates.text() == "Verificar Atualizacoes"
    window.close()


def test_startup_layout_does_not_lock_table_or_splitter_heights():
    window = MainWindow()

    window._finalize_startup_layout()

    assert window.data_tab._locked_table_height is None
    assert window.data_tab._locked_splitter_height is None
    window.close()


def test_compensacoes_quick_filters_update_counts_and_persist_state():
    window = MainWindow()
    saved_states = []
    window.settings_controller.set_compensacoes_filter_state = lambda state: saved_states.append(dict(state))
    session_path = window.persistence_service.ensure_singleton_session().session_path
    records = [
        make_record(uid="u-1", eletronico="Ofício", microbacia="", latitude="", longitude="", av_tec="AT-1"),
        make_record(
            excel_row=3,
            uid="u-2",
            eletronico="SIM",
            compensado="SIM",
            endereco_plantio="Área 1",
            microbacia="Gregório",
            latitude="-22.01",
            longitude="-47.89",
            av_tec="AT-2",
        ),
        make_record(
            excel_row=4,
            uid="u-3",
            eletronico="Físico",
            microbacia="Medeiros",
            latitude="-22.02",
            longitude="-47.88",
            av_tec="AT-3",
        ),
    ]
    window.session_runtime.path = session_path
    window.persistence_service.sync_workbook_snapshot(session_path, records)
    window.records = list(records)

    window.data_controller.update_ui_after_load()
    get_app().processEvents()

    assert "Ofícios (1)" in window.data_tab.quick_filter_buttons["oficios"].text()
    assert "Revisão (1)" in window.data_tab.quick_filter_buttons["qualidade"].text()

    window.data_tab.quick_filter_buttons["oficios"].click()
    window.data_controller.apply_filter()
    get_app().processEvents()

    assert [record.uid for record in window.filtered_records] == ["u-1"]
    assert saved_states
    assert saved_states[-1]["quick_filter_mode"] == "oficios"
    window.close()


def test_compensacoes_saved_views_store_current_filter_state(monkeypatch):
    window = MainWindow()
    persisted_views = {}
    window.settings_controller.compensacoes_saved_views = lambda: dict(persisted_views)
    window.settings_controller.set_compensacoes_saved_views = lambda views: persisted_views.update(dict(views))
    monkeypatch.setattr(
        "app.ui.controllers.data_controller.QInputDialog.getText",
        lambda *args, **kwargs: ("Equipe Ofícios", True),
    )

    window.data_controller.set_quick_filter_mode("oficios")
    window.search.setText("SMMADS")
    window.data_controller.apply_filter()

    assert window.data_controller.save_current_view() is True
    assert "Equipe Ofícios" in persisted_views
    assert persisted_views["Equipe Ofícios"]["quick_filter_mode"] == "oficios"
    assert persisted_views["Equipe Ofícios"]["search_text"] == "SMMADS"
    window.close()


def test_compensacoes_form_restores_saved_new_record_draft():
    window = MainWindow()
    window.form_controller._pending_new_form_draft = {
        "uid": "",
        "oficio_processo": "163/23 - SMMADS",
        "caixa": "Ofícios",
        "av_tec": "073/2023",
        "compensacao": "1",
        "endereco": "Rua Vicente de Carvalho - Vila Marcelino",
        "endereco_plantio": "",
        "plantios": (),
        "microbacia": "Gregório",
        "compensado": False,
        "sn": False,
        "arquivado": False,
        "eletronico": "Ofício",
    }

    window.clear_form(force=True)
    restored = window.form_controller.restore_saved_new_record_draft()
    get_app().processEvents()

    assert restored is True
    assert window.data_tab.in_oficio.text() == "163/23 - SMMADS"
    assert window.data_tab.in_caixa.text() == "Ofícios"
    assert window.data_tab.in_end.text().startswith("Rua Vicente")
    assert window.data_tab.in_micro.currentText() == "Gregório"
    assert window.form_controller.has_pending_changes() is True
    window.close()


def test_compensacoes_bulk_action_updates_selected_records(monkeypatch):
    window = MainWindow()
    session_path = window.persistence_service.ensure_singleton_session().session_path
    records = [
        make_record(uid="u-1", eletronico="SIM", caixa="", microbacia="", av_tec="AT-1"),
        make_record(excel_row=3, uid="u-2", eletronico="SIM", caixa="CX-2", microbacia="", av_tec="AT-2"),
    ]
    window.session_runtime.path = session_path
    window.persistence_service.sync_workbook_snapshot(session_path, records)
    window.records = list(records)

    window.data_controller.update_ui_after_load()
    get_app().processEvents()

    class BulkDialog:
        def __init__(self, *args, **kwargs):
            pass

        def exec(self):
            return True

        def values(self):
            return {"action": "tipo", "tipo": "Ofício", "microbacia": "", "caixa": ""}

    monkeypatch.setattr("app.ui.controllers.form_controller.CompensacaoBulkActionDialog", BulkDialog)

    selection_model = window.data_tab.table.selectionModel()
    assert selection_model is not None
    selection_model.select(
        window.data_tab.proxy.index(0, 0),
        QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows,
    )
    selection_model.select(
        window.data_tab.proxy.index(1, 0),
        QItemSelectionModel.Select | QItemSelectionModel.Rows,
    )
    get_app().processEvents()
    window.shell_controller.refresh_compensacoes_selection_state()

    assert window.data_tab.btn_bulk_action.isEnabled() is True
    assert window.data_tab.btn_bulk_action.text() == "Ações em lote (2)"
    assert "2 registros selecionados" in window.data_tab.lbl_selection_summary.text()

    assert window.form_controller.apply_bulk_action() is True
    get_app().processEvents()

    assert [record.eletronico for record in window.records] == ["Ofício", "Ofício"]
    assert [record.caixa for record in window.records] == ["OFÍCIOS", "OFÍCIOS"]
    window.close()


def test_bulk_tipo_eletronico_prefills_caixa_with_eletronico():
    window = MainWindow()

    updated = window.form_controller._build_bulk_updated_record(
        make_record(eletronico="Ofício", caixa="OFÍCIOS"),
        {"action": "tipo", "tipo": "Eletrônico"},
    )
    cleared = window.form_controller._build_bulk_updated_record(
        make_record(eletronico="Eletrônico", caixa="ELETRÔNICO"),
        {"action": "tipo", "tipo": "Físico"},
    )

    assert updated.eletronico == "Eletrônico"
    assert updated.caixa == "ELETRÔNICO"
    assert cleared.eletronico == "Físico"
    assert cleared.caixa == ""
    window.close()



