from app.models.compensacao import Compensacao
from app.services.record_integrity_service import build_record_integrity_report


def make_record(
    *,
    excel_row: int,
    uid: str = "",
    av_tec: str = "",
    oficio_processo: str = "",
    endereco: str = "",
    compensado: str = "",
    endereco_plantio: str = "",
    latitude: str = "",
    longitude: str = "",
    latitude_plantio: str = "",
    longitude_plantio: str = "",
    plantios=None,
):
    return Compensacao(
        excel_row=excel_row,
        oficio_processo=oficio_processo,
        eletronico="",
        caixa="",
        av_tec=av_tec,
        compensacao="",
        endereco=endereco,
        microbacia="Gregorio",
        compensado=compensado,
        endereco_plantio=endereco_plantio,
        latitude_plantio=latitude_plantio,
        longitude_plantio=longitude_plantio,
        latitude=latitude,
        longitude=longitude,
        uid=uid,
        plantios=list(plantios or []),
    )


def test_record_integrity_report_detects_duplicates_and_structural_warnings():
    records = [
        make_record(
            excel_row=2,
            uid="uid-1",
            av_tec="107/2021",
            oficio_processo="206/2021",
            endereco="Rua A",
            compensado="SIM",
        ),
        make_record(
            excel_row=3,
            uid="uid-1",
            av_tec="107/2021",
            oficio_processo="207/2021",
            endereco="Rua B",
            latitude="200",
        ),
        make_record(
            excel_row=4,
            uid="",
            av_tec="",
            oficio_processo="",
            endereco="",
        ),
    ]

    report = build_record_integrity_report(records)

    assert report.total_records == 3
    assert report.analyzed_records == 3
    assert report.issue_count >= 5
    assert report.error_count >= 2
    assert report.warning_count >= 3
    assert report.affected_records_count == 3
    assert report.ok is False
    messages = [issue.message for issue in report.issues]
    assert any("UID duplicado" in message for message in messages)
    assert any("Av. Tec. duplicada" in message for message in messages)
    assert any("sem UID" in message for message in messages)
    assert any("fora da faixa esperada" in message for message in messages)
    assert any("sem endereco de plantio" in message for message in messages)


def test_record_integrity_report_accepts_clean_records():
    record = make_record(
        excel_row=2,
        uid="uid-1",
        av_tec="107/2021",
        oficio_processo="206/2021",
        endereco="Rua A",
        compensado="SIM",
        endereco_plantio="Plantio A",
        latitude="-22.01",
        longitude="-47.89",
        latitude_plantio="-22.05",
        longitude_plantio="-47.91",
    )

    report = build_record_integrity_report([record])

    assert report.issue_count == 0
    assert report.error_count == 0
    assert report.warning_count == 0
    assert report.ok is True
    assert "sem inconsistencias estruturais" in report.summary
