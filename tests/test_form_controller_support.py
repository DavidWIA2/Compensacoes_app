from app.models.compensacao import Compensacao
from app.models.plantio_item import PlantioItem
from app.ui.controllers.form_controller_support import (
    FormStateSnapshot,
    build_field_feedback_stylesheet,
    build_dirty_state_view,
    build_duplicate_highlight_stylesheet,
    build_form_action_state,
    build_form_record,
    build_form_state_snapshot,
    build_form_validation_presentation,
    build_prefill_form_state,
    normalize_av_tec_value,
    normalize_caixa_value,
    normalize_microbacia_value,
    normalize_oficio_processo_value,
    resolve_before_record_for_audit,
    same_record_identity,
)


def make_record(**overrides) -> Compensacao:
    payload = {
        "excel_row": 2,
        "oficio_processo": "123/2026",
        "eletronico": "SIM",
        "caixa": "CX-1",
        "av_tec": "AT-1",
        "compensacao": "10",
        "endereco": "Rua A",
        "microbacia": "Gregorio",
        "compensado": "",
        "latitude": "",
        "longitude": "",
        "uid": "u-1",
    }
    payload.update(overrides)
    return Compensacao(**payload)


def test_form_controller_support_builds_state_snapshot_round_trip():
    snapshot = build_form_state_snapshot(
        oficio_processo=" 123/2026 ",
        caixa=" CX-1 ",
        av_tec=" AT-1 ",
        compensacao=" 20 ",
        endereco=" Rua A ",
        endereco_plantio=" Plantio A ",
        plantios=((1, "Plantio A", "20", "-22.0", "-47.0"),),
        microbacia=" Gregorio ",
        compensado=True,
        sn=False,
        arquivado=True,
        eletronico="SIM",
    )
    restored = FormStateSnapshot.from_mapping(snapshot.to_dict())
    assert restored == snapshot
    assert restored.eletronico
    assert restored.arquivado is True


def test_form_controller_support_builds_prefill_state_and_form_record():
    record = make_record(
        uid="u-10",
        compensado="SIM",
        plantios=[PlantioItem(sequence=1, endereco="Plantio A", qtd_mudas="20", latitude="-22", longitude="-47")],
    )
    snapshot = build_prefill_form_state(record)
    assert snapshot.compensado is True
    assert snapshot.endereco_plantio
    rebuilt = build_form_record(
        selected_record=record,
        oficio_processo=snapshot.oficio_processo,
        caixa=snapshot.caixa,
        av_tec=snapshot.av_tec,
        compensacao=snapshot.compensacao,
        endereco=snapshot.endereco,
        endereco_plantio=snapshot.endereco_plantio,
        microbacia=snapshot.microbacia,
        compensado_checked=snapshot.compensado,
        eletronico_value=snapshot.eletronico,
        plantios=record.plantios,
    )
    assert rebuilt.uid == "u-10"
    assert rebuilt.compensado == "SIM"
    assert rebuilt.endereco_plantio
    assert rebuilt.eletronico


def test_form_controller_support_normalizes_new_record_values():
    rebuilt = build_form_record(
        selected_record=None,
        oficio_processo=" 123/2026 ",
        caixa=" cx-9 ",
        av_tec=" at-9 ",
        compensacao=" 20,5 ",
        endereco=" Rua  A ",
        endereco_plantio="  Plantio  A  ",
        microbacia=" gregorio ",
        compensado_checked=False,
        eletronico_value="SIM",
        plantios=[],
        sn_checked=False,
        arquivado_checked=False,
        microbacia_resolver=lambda value: "Gregório" if str(value).strip().lower() == "gregorio" else str(value),
    )

    assert rebuilt.oficio_processo == "123/2026"
    assert rebuilt.caixa == "CX-9"
    assert rebuilt.av_tec == "AT-9"
    assert rebuilt.compensacao == "20,5"
    assert rebuilt.endereco == "Rua A"
    assert rebuilt.endereco_plantio == "Plantio A"
    assert rebuilt.microbacia == "Gregório"


def test_form_controller_support_normalization_helpers_cover_special_flags():
    assert normalize_oficio_processo_value(" 999/2026 ", sn_checked=True) == "S/N"
    assert normalize_av_tec_value(" at 123 ") == "AT 123"
    assert normalize_caixa_value("arquivado", arquivado_checked=False) == ""
    assert normalize_caixa_value("12", arquivado_checked=True) == "Arquivado"
    assert normalize_microbacia_value(" medeiros ", resolver=lambda _: "Medeiros") == "Medeiros"


def test_form_controller_support_builds_dirty_and_action_views():
    dirty = build_dirty_state_view(
        is_dirty=True,
        dirty_group_title="Cadastro *",
        clean_group_title="Cadastro",
    )
    assert dirty.group_title == "Cadastro *"
    assert dirty.window_modified is True

    actions = build_form_action_state(
        has_session=True,
        has_selected=True,
        is_dirty=True,
        plantio_error="",
    )
    assert actions.enable_add is True
    assert actions.enable_save is True
    assert actions.enable_delete is True
    assert actions.enable_ficha is True

    blocked_actions = build_form_action_state(
        has_session=True,
        has_selected=True,
        is_dirty=True,
        plantio_error="faltando plantio",
    )
    assert blocked_actions.enable_save is False

    style = build_duplicate_highlight_stylesheet(background_color="#ffffff", text_color="#111111")
    assert "#e74c3c" in style
    assert "#ffffff" in style

    feedback_style = build_field_feedback_stylesheet(
        background_color="#ffffff",
        text_color="#111111",
        severity="warning",
    )
    assert "#d97706" in feedback_style


def test_form_controller_support_builds_validation_presentation_for_preventive_feedback():
    presentation = build_form_validation_presentation(
        record=make_record(
            oficio_processo="",
            av_tec="AT-1",
            compensacao="0",
            endereco="Rua A",
            microbacia="",
            latitude="-22.0",
            longitude="",
            compensado="SIM",
            endereco_plantio="",
            plantios=[],
        ),
        duplicate_row=6,
        current_year=2026,
    )

    assert presentation.severity == "error"
    assert presentation.focus_field == "oficio_processo"
    assert "Revise" in presentation.summary_text
    assert "linha 5" in presentation.duplicate_text
    assert "Buscar Endereço" in presentation.geocode_text
    assert presentation.field_feedback["oficio_processo"].severity == "error"
    assert presentation.field_feedback["av_tec"].severity == "warning"
    assert presentation.field_feedback["microbacia"].severity == "info"


def test_form_controller_support_resolves_identity_and_audit_baseline():
    selected = make_record(uid="u-20", excel_row=4, endereco="Original")
    authoritative = make_record(uid="u-20", excel_row=99, endereco="Atualizado")
    assert same_record_identity(selected, authoritative) is True

    before = resolve_before_record_for_audit(authoritative, selected)
    assert before is not None
    assert before is not selected
    assert before.endereco == "Original"

    fallback = resolve_before_record_for_audit(authoritative, None)
    assert fallback is not None
    assert fallback is not authoritative
    assert fallback.endereco == "Atualizado"
