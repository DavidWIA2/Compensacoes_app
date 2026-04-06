from app.models.compensacao import Compensacao
from app.models.plantio_item import PlantioItem
from app.ui.controllers.form_controller_support import (
    FormStateSnapshot,
    build_dirty_state_view,
    build_duplicate_highlight_stylesheet,
    build_form_action_state,
    build_form_record,
    build_form_state_snapshot,
    build_prefill_form_state,
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
