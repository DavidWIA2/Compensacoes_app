from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Iterable, Mapping, Optional, Sequence, cast

from app.models.compensacao import Compensacao
from app.services.plantio_service import serialize_plantios_state, sync_legacy_plantio_fields
from app.services.records_service import display_tipo_value, safe_upper, storage_tipo_value


@dataclass(frozen=True)
class FormStateSnapshot:
    oficio_processo: str = ""
    caixa: str = ""
    av_tec: str = ""
    compensacao: str = ""
    endereco: str = ""
    endereco_plantio: str = ""
    plantios: tuple[tuple[int, str, str, str, str], ...] = ()
    microbacia: str = ""
    compensado: bool = False
    sn: bool = False
    arquivado: bool = False
    eletronico: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "oficio_processo": self.oficio_processo,
            "caixa": self.caixa,
            "av_tec": self.av_tec,
            "compensacao": self.compensacao,
            "endereco": self.endereco,
            "endereco_plantio": self.endereco_plantio,
            "plantios": self.plantios,
            "microbacia": self.microbacia,
            "compensado": self.compensado,
            "sn": self.sn,
            "arquivado": self.arquivado,
            "eletronico": self.eletronico,
        }

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object] | None) -> "FormStateSnapshot":
        payload = dict(payload or {})
        return cls(
            oficio_processo=str(payload.get("oficio_processo", "")),
            caixa=str(payload.get("caixa", "")),
            av_tec=str(payload.get("av_tec", "")),
            compensacao=str(payload.get("compensacao", "")),
            endereco=str(payload.get("endereco", "")),
            endereco_plantio=str(payload.get("endereco_plantio", "")),
            plantios=tuple(
                cast(
                    Sequence[tuple[int, str, str, str, str]],
                    payload.get("plantios", ()),
                )
            ),
            microbacia=str(payload.get("microbacia", "")),
            compensado=bool(payload.get("compensado", False)),
            sn=bool(payload.get("sn", False)),
            arquivado=bool(payload.get("arquivado", False)),
            eletronico=str(payload.get("eletronico", "")),
        )


@dataclass(frozen=True)
class FormDirtyStateView:
    group_title: str
    status_label: str
    window_modified: bool


@dataclass(frozen=True)
class FormActionState:
    enable_add: bool
    enable_save: bool
    enable_delete: bool
    enable_ficha: bool


def build_form_state_snapshot(
    *,
    oficio_processo: str,
    caixa: str,
    av_tec: str,
    compensacao: str,
    endereco: str,
    endereco_plantio: str,
    plantios: Iterable[tuple[int, str, str, str, str]],
    microbacia: str,
    compensado: bool,
    sn: bool,
    arquivado: bool,
    eletronico: str,
) -> FormStateSnapshot:
    return FormStateSnapshot(
        oficio_processo=str(oficio_processo).strip(),
        caixa=str(caixa).strip(),
        av_tec=str(av_tec).strip(),
        compensacao=str(compensacao).strip(),
        endereco=str(endereco).strip(),
        endereco_plantio=str(endereco_plantio).strip(),
        plantios=tuple(plantios),
        microbacia=str(microbacia).strip(),
        compensado=bool(compensado),
        sn=bool(sn),
        arquivado=bool(arquivado),
        eletronico=display_tipo_value(eletronico),
    )


def build_prefill_form_state(record: Compensacao) -> FormStateSnapshot:
    sync_legacy_plantio_fields(record)
    return FormStateSnapshot(
        oficio_processo=(record.oficio_processo or "").strip(),
        caixa=(record.caixa or "").strip(),
        av_tec=str(record.av_tec or ""),
        compensacao=str(record.compensacao or ""),
        endereco=str(record.endereco or ""),
        endereco_plantio=str(record.endereco_plantio or ""),
        plantios=serialize_plantios_state(record.plantios),
        microbacia=str(record.microbacia or ""),
        compensado=safe_upper(record.compensado) == "SIM",
        sn=(record.oficio_processo or "").strip().upper() == "S/N",
        arquivado=(record.caixa or "").strip().upper() == "ARQUIVADO",
        eletronico=display_tipo_value(record.eletronico),
    )


def build_duplicate_highlight_stylesheet(*, background_color: str, text_color: str) -> str:
    return (
        "QLineEdit { "
        "border: 2px solid #e74c3c; "
        f"background-color: {background_color}; "
        f"color: {text_color}; "
        "}"
    )


def build_dirty_state_view(
    *,
    is_dirty: bool,
    dirty_group_title: str,
    clean_group_title: str,
) -> FormDirtyStateView:
    return FormDirtyStateView(
        group_title=dirty_group_title if is_dirty else clean_group_title,
        status_label="Alterações pendentes" if is_dirty else "Sem alterações",
        window_modified=bool(is_dirty),
    )


def build_form_action_state(
    *,
    has_session: bool,
    has_selected: bool,
    is_dirty: bool,
    plantio_error: str,
) -> FormActionState:
    allow_save = bool(has_session and has_selected and is_dirty and not plantio_error)
    enable_selected_actions = bool(has_session and has_selected)
    return FormActionState(
        enable_add=bool(has_session),
        enable_save=allow_save,
        enable_delete=enable_selected_actions,
        enable_ficha=enable_selected_actions,
    )


def build_form_record(
    *,
    selected_record: Optional[Compensacao],
    oficio_processo: str,
    caixa: str,
    av_tec: str,
    compensacao: str,
    endereco: str,
    endereco_plantio: str,
    microbacia: str,
    compensado_checked: bool,
    eletronico_value: str,
    plantios,
) -> Compensacao:
    record = Compensacao(
        excel_row=selected_record.excel_row if selected_record else -1,
        oficio_processo=str(oficio_processo).strip(),
        caixa=str(caixa).strip(),
        av_tec=str(av_tec).strip(),
        compensacao=str(compensacao).strip(),
        endereco=str(endereco).strip(),
        endereco_plantio=str(endereco_plantio).strip(),
        microbacia=str(microbacia).strip(),
        compensado="SIM" if compensado_checked else "",
        eletronico=storage_tipo_value(eletronico_value),
        uid=selected_record.uid if selected_record else "",
        plantios=list(plantios),
    )
    return sync_legacy_plantio_fields(record)


def same_record_identity(left: Compensacao | None, right: Compensacao | None) -> bool:
    if left is None or right is None:
        return False
    left_uid = str(getattr(left, "uid", "") or "").strip()
    right_uid = str(getattr(right, "uid", "") or "").strip()
    if left_uid and right_uid:
        return left_uid == right_uid
    left_row = int(getattr(left, "excel_row", 0) or 0)
    right_row = int(getattr(right, "excel_row", 0) or 0)
    return left_row > 0 and right_row > 0 and left_row == right_row


def resolve_before_record_for_audit(
    authoritative_record: Compensacao | None,
    selected_record: Compensacao | None,
) -> Compensacao | None:
    if selected_record is not None and same_record_identity(authoritative_record, selected_record):
        return deepcopy(selected_record)
    return deepcopy(authoritative_record) if authoritative_record is not None else None
