from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import date
from typing import Callable, Iterable, Mapping, Optional, Sequence, cast

from app.models.compensacao import Compensacao
from app.services.plantio_service import serialize_plantios_state, sync_legacy_plantio_fields
from app.services.records_service import display_tipo_value, extract_year, safe_upper, storage_tipo_value


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


@dataclass(frozen=True)
class InlineFieldFeedback:
    severity: str
    message: str


@dataclass(frozen=True)
class FormValidationPresentation:
    severity: str
    summary_text: str
    detail_text: str
    duplicate_text: str
    geocode_text: str
    focus_field: str = ""
    field_feedback: Mapping[str, InlineFieldFeedback] = ()


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


def _collapse_text(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def normalize_oficio_processo_value(value: object, *, sn_checked: bool = False) -> str:
    text = _collapse_text(value)
    if sn_checked:
        return "S/N"
    return text


def normalize_av_tec_value(value: object) -> str:
    return _collapse_text(value).upper()


def normalize_caixa_value(value: object, *, arquivado_checked: bool = False) -> str:
    text = _collapse_text(value)
    if arquivado_checked:
        return "Arquivado"
    if text.upper() == "ARQUIVADO":
        return ""
    return text.upper()


def normalize_microbacia_value(
    value: object,
    *,
    resolver: Callable[[object], str] | None = None,
) -> str:
    text = _collapse_text(value)
    if not text:
        return ""
    if resolver is None:
        return text
    resolved = _collapse_text(resolver(text))
    return resolved or text


def normalize_compensacao_value(value: object) -> str:
    return _collapse_text(value)


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


def build_field_feedback_stylesheet(
    *,
    background_color: str,
    text_color: str,
    severity: str,
) -> str:
    border_color = {
        "error": "#d32f2f",
        "warning": "#d97706",
        "info": "#2563eb",
        "success": "#2e7d32",
    }.get(str(severity or "").strip().lower(), "#2563eb")
    return (
        "QLineEdit, QComboBox { "
        f"border: 2px solid {border_color}; "
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
    sn_checked: bool = False,
    arquivado_checked: bool = False,
    microbacia_resolver: Callable[[object], str] | None = None,
) -> Compensacao:
    record = Compensacao(
        excel_row=selected_record.excel_row if selected_record else -1,
        oficio_processo=normalize_oficio_processo_value(oficio_processo, sn_checked=sn_checked),
        caixa=normalize_caixa_value(caixa, arquivado_checked=arquivado_checked),
        av_tec=normalize_av_tec_value(av_tec),
        compensacao=normalize_compensacao_value(compensacao),
        endereco=_collapse_text(endereco),
        endereco_plantio=_collapse_text(endereco_plantio),
        microbacia=normalize_microbacia_value(microbacia, resolver=microbacia_resolver),
        compensado="SIM" if compensado_checked else "",
        eletronico=storage_tipo_value(eletronico_value),
        uid=selected_record.uid if selected_record else "",
        updated_at=selected_record.updated_at if selected_record else "",
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


def build_form_validation_presentation(
    *,
    record: Compensacao,
    duplicate_row: Optional[int] = None,
    current_year: int | None = None,
) -> FormValidationPresentation:
    issues: dict[str, InlineFieldFeedback] = {}

    def add_feedback(field: str, severity: str, message: str) -> None:
        current = issues.get(field)
        priority = {"error": 3, "warning": 2, "info": 1, "success": 0}
        if current is not None and priority.get(current.severity, 0) >= priority.get(severity, 0):
            return
        issues[field] = InlineFieldFeedback(severity=severity, message=message)

    oficio_text = str(record.oficio_processo or "").strip()
    av_tec_text = str(record.av_tec or "").strip()
    compensacao_text = str(record.compensacao or "").strip()
    endereco_text = str(record.endereco or "").strip()
    endereco_plantio_text = str(record.endereco_plantio or "").strip()
    microbacia_text = str(record.microbacia or "").strip()
    latitude_text = str(getattr(record, "latitude", "") or "").strip()
    longitude_text = str(getattr(record, "longitude", "") or "").strip()
    plantios = tuple(getattr(record, "plantios", ()) or ())
    current_year = int(current_year or date.today().year)

    if not oficio_text:
        add_feedback("oficio_processo", "error", "Informe Ofício/Processo ou marque S/N.")
    else:
        oficio_year = extract_year(oficio_text)
        if oficio_year:
            extracted_year = int(oficio_year)
            if extracted_year > current_year:
                add_feedback(
                    "oficio_processo",
                    "error",
                    f"O ano do Ofício/Processo não pode ser maior que {current_year}.",
                )

    if not av_tec_text:
        add_feedback("av_tec", "error", "Informe a Av. Tec. do cadastro.")
    elif duplicate_row:
        add_feedback(
            "av_tec",
            "warning",
            f"Já existe um cadastro com esta Av. Tec. na linha {max(int(duplicate_row or 0) - 1, 1)}.",
        )

    if not compensacao_text:
        add_feedback("compensacao", "error", "Informe a compensação prevista.")
    else:
        normalized_number = compensacao_text.replace(" ", "").replace(".", "").replace(",", ".")
        try:
            if float(normalized_number) <= 0:
                add_feedback("compensacao", "error", "A compensação precisa ser maior que zero.")
        except ValueError:
            add_feedback("compensacao", "error", "Use um número válido em Compensação.")

    if latitude_text and not longitude_text or longitude_text and not latitude_text:
        add_feedback("endereco", "warning", "Latitude e longitude devem ser preenchidas juntas.")

    if record.compensado == "SIM" and not endereco_plantio_text and not plantios:
        add_feedback(
            "endereco_plantio",
            "warning",
            "Cadastro compensado sem plantio informado. Use “Plantios...” ou preencha o endereço de plantio.",
        )

    if endereco_text and not microbacia_text:
        add_feedback(
            "microbacia",
            "info",
            "Microbacia ainda não definida. Você pode preencher manualmente ou usar Buscar Endereço.",
        )

    error_fields = [field for field, feedback in issues.items() if feedback.severity == "error"]
    warning_fields = [field for field, feedback in issues.items() if feedback.severity == "warning"]
    info_fields = [field for field, feedback in issues.items() if feedback.severity == "info"]
    ordered_messages = [issues[field].message for field in error_fields + warning_fields + info_fields]

    if error_fields:
        severity = "error"
        summary = f"Revise {len(error_fields)} campo(s) antes de salvar."
        focus_field = error_fields[0]
    elif warning_fields:
        severity = "warning"
        summary = "Cadastro preenchido, mas ainda há pontos de revisão."
        focus_field = warning_fields[0]
    elif info_fields:
        severity = "info"
        summary = "Cadastro pronto para seguir, com sugestões de preenchimento."
        focus_field = info_fields[0]
    else:
        severity = "success"
        summary = "Cadastro consistente para seguir."
        focus_field = ""

    if not endereco_text and not endereco_plantio_text and not plantios:
        geocode_text = "Geocodificação: informe um endereço principal ou de plantio para usar o mapa."
    elif endereco_text and not latitude_text and not longitude_text and not microbacia_text:
        geocode_text = "Geocodificação: Buscar Endereço pode posicionar o processo e sugerir a microbacia."
    elif record.compensado == "SIM" and (plantios or endereco_plantio_text):
        geocode_text = "Geocodificação: Buscar Plantio ajuda a revisar o ponto do plantio atual."
    elif endereco_text:
        geocode_text = "Geocodificação: Buscar Endereço pode revisar o ponto principal do cadastro."
    else:
        geocode_text = ""

    duplicate_text = ""
    if duplicate_row:
        duplicate_text = (
            f"Duplicidade preventiva: a Av. Tec. coincide com a linha {max(int(duplicate_row or 0) - 1, 1)}. "
            "Revise antes de confirmar."
        )

    detail_text = " | ".join(ordered_messages[:3])
    if not detail_text and geocode_text:
        detail_text = geocode_text
    if not detail_text and severity == "success":
        detail_text = "Os campos principais já estão prontos para salvar, exportar ou geocodificar."

    return FormValidationPresentation(
        severity=severity,
        summary_text=summary,
        detail_text=detail_text,
        duplicate_text=duplicate_text,
        geocode_text=geocode_text,
        focus_field=focus_field,
        field_feedback=issues,
    )
