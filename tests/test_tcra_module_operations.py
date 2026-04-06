from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

import openpyxl
from openpyxl import load_workbook

from app.application.use_cases.tcra_module_operations import TcraModuleOperations
from app.models.tcra import Tcra
from app.models.tcra_evento import TcraEvento
from app.services.tcra_excel_service import TCRA_SHEET_NAME
from app.services.tcra_sqlite_service import TcraSqliteService


def make_tcra(**overrides) -> Tcra:
    base = {
        "uid": "tcra-1",
        "numero_processo": "26207/2019",
        "numero_tcra": "TCRA-2019-001",
        "local": "Sistema de Lazer - Residencial Itamarati",
        "endereco": "Rua Ireneu Couto",
        "bairro": "Residencial Itamarati",
        "orgao_acompanhamento": "CETESB",
        "status": "Em acompanhamento",
        "data_assinatura": date(2019, 6, 1),
        "prazo_final": date(2026, 4, 1),
        "periodicidade_relatorio_meses": 60,
        "data_ultimo_relatorio": date(2024, 4, 11),
        "data_proximo_relatorio": date(2025, 3, 10),
        "area_m2": 2920.0,
        "numero_mudas_previsto": 486,
        "servicos_exigidos": "Tratos culturais regulares",
        "responsavel_execucao": "Secretaria Municipal",
        "observacoes": "Relatorio a cada 5 anos",
        "mpsp_relacionado": "Nao",
        "inquerito_civil": "",
        "eventos": [
            TcraEvento(
                sequence=1,
                data_evento=date(2024, 4, 11),
                tipo_evento="Relatorio",
                descricao="Relatorio periodico protocolado",
                prazo_resultante=date(2025, 3, 10),
                status_resultante="Em acompanhamento",
            )
        ],
    }
    base.update(overrides)
    return Tcra(**base)


def build_legacy_tcra_workbook(path: Path) -> None:
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = TCRA_SHEET_NAME
    worksheet.append(
        [
            "Processo",
            "Local",
            "Endereco",
            "Relat. Periodico",
            "Ultimo Rel.",
            "Prazo",
            "Servicos a realizar",
            "Tamanho",
            "No de Mudas",
            "Acompanhamento",
            "",
            "MPSP?",
        ]
    )
    worksheet.append(
        [
            "26207/2019",
            "Sistema de Lazer - Residencial Itamarati",
            "Rua Ireneu Couto - Residencial Itamarati",
            date(2025, 3, 10),
            date(2024, 4, 11),
            date(2026, 4, 1),
            "Tratos Culturais regulares antes do prazo",
            2920,
            "=ROUNDDOWN(H2/6,0)",
            "CETESB",
            "*Relatorio a cada 5 anos",
            "Nao",
        ]
    )
    worksheet.append(
        [
            "2360/2021",
            "Varjao",
            "Margem da Rod. Eng. Thales de Lorena Peixoto Junior",
            "-",
            date(2025, 1, 3),
            "-",
            "Inquerito Civil Arquivado em 23/01/2025",
            12577,
            "=ROUNDDOWN(H3/6,0)",
            "Cumprido",
            "*Cumprido",
            "Sim",
        ]
    )
    workbook.save(path)


def make_operations(service: TcraSqliteService, audit_calls: list[dict] | None = None) -> TcraModuleOperations:
    audit_calls = audit_calls if audit_calls is not None else []
    audit_service = SimpleNamespace(append_session_event=lambda **kwargs: audit_calls.append(kwargs))
    return TcraModuleOperations(
        service,
        today=date(2026, 4, 3),
        audit_service_provider=lambda: audit_service,
        session_path_provider=lambda: "session://banco-local",
    )


def test_tcra_module_operations_load_save_delete_and_dashboard(tmp_path):
    service = TcraSqliteService(db_path=tmp_path / "local.db")
    audit_calls: list[dict] = []
    operations = make_operations(service, audit_calls)

    load_result = operations.load_records()
    assert load_result.records == ()
    assert load_result.search_index == {}

    save_result = operations.save_record(
        make_tcra(uid="", numero_processo="777/2026", numero_tcra="TCRA-2026-777", local="Parque Linear"),
        pending_audit_metadata={"event_change_action": "add", "event_change_type": "Vistoria"},
    )

    assert save_result.status == "saved"
    assert save_result.saved_uid
    assert save_result.saved_record is not None
    assert audit_calls[-1]["action"] == "TCRA_CREATE"
    assert audit_calls[-1]["metadata"]["event_change_type"] == "Vistoria"

    load_result = operations.load_records()
    assert load_result.records[0].uid == save_result.saved_uid
    assert save_result.saved_uid in load_result.search_index

    dashboard_payload = operations.build_dashboard_payload(load_result.records)
    assert dashboard_payload.overview is not None
    assert len(dashboard_payload.agenda_items) >= 1

    delete_result = operations.delete_record(save_result.saved_uid)
    assert delete_result.status == "deleted"
    assert service.list_tcras() == []
    assert audit_calls[-1]["action"] == "TCRA_DELETE"


def test_tcra_module_operations_returns_duplicate_and_invalid_results(tmp_path):
    service = TcraSqliteService(db_path=tmp_path / "local.db")
    service.replace_all([make_tcra(uid="tcra-1")])
    operations = make_operations(service)

    duplicate_result = operations.save_record(
        make_tcra(uid="", numero_tcra="TCRA-2019-001", numero_processo="999/2026", local="Novo local")
    )
    assert duplicate_result.status == "duplicate"
    assert duplicate_result.duplicate_record is not None

    invalid_result = operations.save_record(
        make_tcra(
            uid="",
            numero_tcra="",
            numero_processo="888/2026",
            local="Area Norte",
            status="Cumprido",
            data_ultimo_relatorio=date(2026, 4, 10),
            data_proximo_relatorio=date(2026, 4, 1),
        )
    )
    assert invalid_result.status == "invalid"
    assert "Proximo relatorio nao pode ser anterior ao ultimo relatorio." in invalid_result.consistency_issues


def test_tcra_module_operations_applies_bulk_event_action(tmp_path):
    service = TcraSqliteService(db_path=tmp_path / "local.db")
    service.replace_all(
        [
            make_tcra(uid="tcra-1", data_proximo_relatorio=date(2026, 4, 1)),
            make_tcra(uid="tcra-2", numero_tcra="TCRA-2", numero_processo="7205/2014", data_proximo_relatorio=date(2026, 4, 2)),
        ]
    )
    audit_calls: list[dict] = []
    operations = make_operations(service, audit_calls)

    result = operations.apply_bulk_action(
        service.list_tcras(),
        {
            "action": "evento",
            "event_preset": "cumprimento",
            "event_date": "10/04/2026",
            "event_deadline": "10/04/2026",
        },
        parse_date=lambda text, _label: datetime.strptime(text, "%d/%m/%Y").date(),
        event_presets=(
            {
                "key": "cumprimento",
                "tipo_evento": "Cumprimento",
                "descricao": "Termo cumprido.",
                "status_resultante": "Cumprido",
            },
        ),
    )

    assert result.action == "evento"
    assert len(result.updated_uids) == 2
    updated_records = service.get_tcras_by_uids(result.updated_uids)
    assert all(record.status == "Cumprido" for record in updated_records)
    assert all(record.data_proximo_relatorio is None for record in updated_records)
    assert audit_calls[-1]["action"] == "TCRA_BULK_UPDATE"


def test_tcra_module_operations_imports_and_exports_reports(tmp_path):
    service = TcraSqliteService(db_path=tmp_path / "local.db")
    audit_calls: list[dict] = []
    operations = make_operations(service, audit_calls)
    workbook_path = tmp_path / "tcras.xlsx"
    build_legacy_tcra_workbook(workbook_path)

    analysis = operations.analyze_import_workbook(workbook_path)
    assert analysis.importable_count == 2

    import_result = operations.execute_import_merge(analysis)
    assert import_result.merge_result.importable_count == 2
    assert import_result.preferred_uid
    assert audit_calls[-1]["action"] == "TCRA_IMPORT"

    records = service.list_tcras()
    excel_path = tmp_path / "tcra-export.xlsx"
    pdf_path = tmp_path / "tcra-export.pdf"
    operations.export_excel_report(str(excel_path), records, filter_summary="Todos")
    operations.export_pdf_report(str(pdf_path), records, filter_summary="Todos")

    workbook = load_workbook(excel_path)
    assert workbook.sheetnames == ["Resumo", "TCRAs"]
    assert pdf_path.exists() is True
    assert pdf_path.stat().st_size > 0
