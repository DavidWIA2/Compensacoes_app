from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence
import unicodedata


@dataclass(frozen=True)
class RecordIntegrityIssue:
    severity: str
    code: str
    message: str
    uid: str = ""
    av_tec: str = ""
    excel_row: int = 0
    field: str = ""


@dataclass(frozen=True)
class RecordIntegrityReport:
    total_records: int
    analyzed_records: int
    issue_count: int
    error_count: int
    warning_count: int
    affected_records_count: int
    ok: bool
    summary: str
    issues: tuple[RecordIntegrityIssue, ...] = ()


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_token(value: Any) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return " ".join(ascii_text.lower().split())


def _record_like(record: Any) -> bool:
    return any(
        hasattr(record, attribute)
        for attribute in (
            "uid",
            "av_tec",
            "oficio_processo",
            "endereco",
            "compensado",
        )
    )


def _integer(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _coordinate_value(value: Any) -> float | None:
    text = _clean_text(value)
    if not text:
        return None
    try:
        return float(text.replace(",", "."))
    except ValueError:
        return None


def _coordinate_issue(
    *,
    field: str,
    label: str,
    raw_value: Any,
    minimum: float,
    maximum: float,
    uid: str,
    av_tec: str,
    excel_row: int,
) -> RecordIntegrityIssue | None:
    text = _clean_text(raw_value)
    if not text:
        return None
    numeric_value = _coordinate_value(text)
    if numeric_value is None:
        return RecordIntegrityIssue(
            severity="warning",
            code=f"invalid_{field}_format",
            message=f"{label} invalida: '{text}'.",
            uid=uid,
            av_tec=av_tec,
            excel_row=excel_row,
            field=field,
        )
    if numeric_value < minimum or numeric_value > maximum:
        return RecordIntegrityIssue(
            severity="warning",
            code=f"invalid_{field}_range",
            message=f"{label} fora da faixa esperada: {text}.",
            uid=uid,
            av_tec=av_tec,
            excel_row=excel_row,
            field=field,
        )
    return None


def _pair_coordinate_issue(
    *,
    latitude_field: str,
    longitude_field: str,
    latitude_label: str,
    longitude_label: str,
    latitude_value: Any,
    longitude_value: Any,
    uid: str,
    av_tec: str,
    excel_row: int,
) -> RecordIntegrityIssue | None:
    latitude_text = _clean_text(latitude_value)
    longitude_text = _clean_text(longitude_value)
    if bool(latitude_text) == bool(longitude_text):
        return None
    missing_label = longitude_label if latitude_text else latitude_label
    return RecordIntegrityIssue(
        severity="warning",
        code=f"incomplete_{latitude_field}_{longitude_field}",
        message=f"Coordenadas incompletas: falta {missing_label.lower()}.",
        uid=uid,
        av_tec=av_tec,
        excel_row=excel_row,
        field=longitude_field if latitude_text else latitude_field,
    )


def _is_compensated(value: Any) -> bool:
    normalized = _normalize_token(value)
    return normalized in {"sim", "compensado", "realizado"}


def build_record_integrity_report(records: Sequence[Any]) -> RecordIntegrityReport:
    issues: list[RecordIntegrityIssue] = []
    affected_records: set[tuple[int, str, str]] = set()
    first_uid_occurrence: dict[str, int] = {}
    first_av_occurrence: dict[str, int] = {}
    analyzed_records = 0

    for record in records or ():
        if not _record_like(record):
            continue

        analyzed_records += 1
        excel_row = _integer(getattr(record, "excel_row", 0))
        uid = _clean_text(getattr(record, "uid", ""))
        av_tec = _clean_text(getattr(record, "av_tec", ""))
        oficio_processo = _clean_text(getattr(record, "oficio_processo", ""))
        endereco = _clean_text(getattr(record, "endereco", ""))
        endereco_plantio = _clean_text(getattr(record, "endereco_plantio", ""))
        plantios = tuple(getattr(record, "plantios", ()) or ())

        def add_issue(issue: RecordIntegrityIssue | None) -> None:
            if issue is None:
                return
            issues.append(issue)
            affected_records.add((issue.excel_row, issue.uid, issue.av_tec))

        if not uid:
            add_issue(
                RecordIntegrityIssue(
                    severity="warning",
                    code="missing_uid",
                    message="Registro sem UID persistido.",
                    av_tec=av_tec,
                    excel_row=excel_row,
                    field="uid",
                )
            )
        else:
            first_row = first_uid_occurrence.get(uid)
            if first_row is None:
                first_uid_occurrence[uid] = excel_row
            else:
                add_issue(
                    RecordIntegrityIssue(
                        severity="error",
                        code="duplicate_uid",
                        message=f"UID duplicado '{uid}' (primeira ocorrencia na linha {first_row}).",
                        uid=uid,
                        av_tec=av_tec,
                        excel_row=excel_row,
                        field="uid",
                    )
                )

        av_key = _normalize_token(av_tec)
        if av_key:
            first_row = first_av_occurrence.get(av_key)
            if first_row is None:
                first_av_occurrence[av_key] = excel_row
            else:
                add_issue(
                    RecordIntegrityIssue(
                        severity="error",
                        code="duplicate_av_tec",
                        message=f"Av. Tec. duplicada '{av_tec}' (primeira ocorrencia na linha {first_row}).",
                        uid=uid,
                        av_tec=av_tec,
                        excel_row=excel_row,
                        field="av_tec",
                    )
                )

        if not any((uid, av_tec, oficio_processo, endereco)):
            add_issue(
                RecordIntegrityIssue(
                    severity="warning",
                    code="weak_identity",
                    message="Registro sem identificadores operacionais suficientes.",
                    uid=uid,
                    av_tec=av_tec,
                    excel_row=excel_row,
                )
            )

        add_issue(
            _pair_coordinate_issue(
                latitude_field="latitude",
                longitude_field="longitude",
                latitude_label="Latitude",
                longitude_label="Longitude",
                latitude_value=getattr(record, "latitude", ""),
                longitude_value=getattr(record, "longitude", ""),
                uid=uid,
                av_tec=av_tec,
                excel_row=excel_row,
            )
        )
        add_issue(
            _coordinate_issue(
                field="latitude",
                label="Latitude",
                raw_value=getattr(record, "latitude", ""),
                minimum=-90.0,
                maximum=90.0,
                uid=uid,
                av_tec=av_tec,
                excel_row=excel_row,
            )
        )
        add_issue(
            _coordinate_issue(
                field="longitude",
                label="Longitude",
                raw_value=getattr(record, "longitude", ""),
                minimum=-180.0,
                maximum=180.0,
                uid=uid,
                av_tec=av_tec,
                excel_row=excel_row,
            )
        )
        add_issue(
            _pair_coordinate_issue(
                latitude_field="latitude_plantio",
                longitude_field="longitude_plantio",
                latitude_label="Latitude do plantio",
                longitude_label="Longitude do plantio",
                latitude_value=getattr(record, "latitude_plantio", ""),
                longitude_value=getattr(record, "longitude_plantio", ""),
                uid=uid,
                av_tec=av_tec,
                excel_row=excel_row,
            )
        )
        add_issue(
            _coordinate_issue(
                field="latitude_plantio",
                label="Latitude do plantio",
                raw_value=getattr(record, "latitude_plantio", ""),
                minimum=-90.0,
                maximum=90.0,
                uid=uid,
                av_tec=av_tec,
                excel_row=excel_row,
            )
        )
        add_issue(
            _coordinate_issue(
                field="longitude_plantio",
                label="Longitude do plantio",
                raw_value=getattr(record, "longitude_plantio", ""),
                minimum=-180.0,
                maximum=180.0,
                uid=uid,
                av_tec=av_tec,
                excel_row=excel_row,
            )
        )

        if _is_compensated(getattr(record, "compensado", "")) and not endereco_plantio and not plantios:
            add_issue(
                RecordIntegrityIssue(
                    severity="warning",
                    code="compensated_without_planting_data",
                    message="Registro marcado como compensado sem endereco de plantio ou plantios vinculados.",
                    uid=uid,
                    av_tec=av_tec,
                    excel_row=excel_row,
                    field="endereco_plantio",
                )
            )

    error_count = sum(1 for issue in issues if issue.severity == "error")
    warning_count = sum(1 for issue in issues if issue.severity != "error")
    issue_count = len(issues)
    total_records = len(records or ())
    ok = issue_count == 0
    if ok:
        summary = f"Base validada: {analyzed_records} registro(s) analisado(s) sem inconsistencias estruturais."
    else:
        summary = (
            f"Base com {error_count} erro(s) e {warning_count} alerta(s) "
            f"em {len(affected_records)} registro(s) analisados."
        )
    return RecordIntegrityReport(
        total_records=total_records,
        analyzed_records=analyzed_records,
        issue_count=issue_count,
        error_count=error_count,
        warning_count=warning_count,
        affected_records_count=len(affected_records),
        ok=ok,
        summary=summary,
        issues=tuple(issues),
    )
