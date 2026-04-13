from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher
from typing import Iterable, Mapping, Sequence

from app.models.tcra import Tcra
from app.models.tcra_evento import TcraEvento
from app.services.audit_service import AuditEvent, format_audit_timestamp
from app.services.tcra_records_service import (
    STATUS_ARQUIVADO,
    STATUS_CUMPRIDO,
    TcraOperationalRules,
    operational_sort_key,
    resolve_operational_status,
    resolve_tcra_risk_profile,
    tcra_has_missing_identity,
    tcra_has_missing_orgao,
    tcra_has_missing_responsavel,
    tcra_has_prazo_vencido,
    tcra_has_relatorio_pendente,
    tcra_has_report_due_soon,
    tcra_has_stale_movement,
    tcra_last_movement_date,
)


def _stringify(value: object) -> str:
    return str(value or "").strip()


def _format_date(value: date | None) -> str:
    return value.strftime("%d/%m/%Y") if value is not None else "--"


def _parse_date(value: object) -> date | None:
    raw_value = _stringify(value)
    if not raw_value:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y"):
        try:
            return datetime.strptime(raw_value, fmt).date()
        except ValueError:
            continue
    return None


def _label_for_record(record: Tcra | None) -> str:
    if record is None:
        return "--"
    return _stringify(record.numero_tcra or record.numero_processo or record.local or record.uid) or "--"


def _normalized_text(value: object) -> str:
    return " ".join(_stringify(value).casefold().split())


def _sequence_similarity(left: object, right: object) -> float:
    left_text = _normalized_text(left)
    right_text = _normalized_text(right)
    if not left_text or not right_text:
        return 0.0
    return SequenceMatcher(None, left_text, right_text).ratio()


def _safe_rules(rules: TcraOperationalRules | None) -> TcraOperationalRules:
    if rules is None:
        return TcraOperationalRules()
    return TcraOperationalRules(
        upcoming_report_window_days=max(int(getattr(rules, "upcoming_report_window_days", 30) or 0), 1),
        stale_movement_window_days=max(int(getattr(rules, "stale_movement_window_days", 180) or 0), 1),
        medium_risk_threshold=max(int(getattr(rules, "medium_risk_threshold", 35) or 0), 1),
        high_risk_threshold=max(int(getattr(rules, "high_risk_threshold", 70) or 0), 1),
        treatment_sla_days=max(int(getattr(rules, "treatment_sla_days", 5) or 0), 1),
        escalation_sla_days=max(int(getattr(rules, "escalation_sla_days", 10) or 0), 1),
    )


@dataclass(frozen=True)
class TcraSlaProfile:
    issue_key: str
    issue_label: str
    started_at: date | None
    due_at: date | None
    escalation_at: date | None
    status: str
    overdue_days: int = 0
    summary: str = ""


@dataclass(frozen=True)
class TcraSlaQueueItem:
    uid: str
    termo_label: str
    responsavel: str
    issue_label: str
    status: str
    due_at: date | None
    escalation_at: date | None
    risk_score: int
    summary: str


@dataclass(frozen=True)
class TcraSlaSummary:
    total_items: int
    due_today_count: int
    overdue_count: int
    escalated_count: int
    summary_text: str


@dataclass(frozen=True)
class TcraPotentialDuplicate:
    uid: str
    label: str
    score: int
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class TcraTrendBucket:
    week_label: str
    entered_high_risk_count: int = 0
    exited_high_risk_count: int = 0
    completed_count: int = 0
    changed_count: int = 0


@dataclass(frozen=True)
class TcraTrendSummary:
    buckets: tuple[TcraTrendBucket, ...]
    summary_text: str


@dataclass(frozen=True)
class TcraWorkloadEntry:
    responsavel: str
    total_count: int
    alert_count: int
    high_risk_count: int
    workload_score: int


@dataclass(frozen=True)
class TcraWorkloadSuggestion:
    record_uid: str
    record_label: str
    suggested_responsavel: str
    reason: str


@dataclass(frozen=True)
class TcraWorkloadSnapshot:
    entries: tuple[TcraWorkloadEntry, ...]
    suggestions: tuple[TcraWorkloadSuggestion, ...]
    summary_text: str


@dataclass(frozen=True)
class TcraResponsavelDigest:
    responsavel: str
    total_count: int
    alert_count: int
    escalated_count: int
    workload_score: int
    summary: str
    message_lines: tuple[str, ...] = ()


@dataclass(frozen=True)
class TcraRouteStop:
    uid: str
    label: str
    bairro: str
    query: str
    priority_score: int
    reason: str


@dataclass(frozen=True)
class TcraRoutePlan:
    stops: tuple[TcraRouteStop, ...]
    summary_text: str


def resolve_tcra_sla_profile(
    record: Tcra,
    *,
    today: date | None = None,
    rules: TcraOperationalRules | None = None,
) -> TcraSlaProfile:
    current_day = today or date.today()
    rule_set = _safe_rules(rules)
    issue_key = ""
    issue_label = ""
    issue_date: date | None = None
    last_touch = tcra_last_movement_date(record) or record.data_assinatura

    if resolve_operational_status(record, today=current_day) in {STATUS_CUMPRIDO, STATUS_ARQUIVADO}:
        return TcraSlaProfile(
            issue_key="",
            issue_label="",
            started_at=None,
            due_at=None,
            escalation_at=None,
            status="ok",
            summary="Sem prazo interno de tratamento pendente.",
        )

    if tcra_has_prazo_vencido(record, today=current_day):
        issue_key = "prazo_vencido"
        issue_label = "Prazo vencido"
        issue_date = record.prazo_final or current_day
    elif tcra_has_relatorio_pendente(record, today=current_day):
        issue_key = "relatorio_pendente"
        issue_label = "Relatório pendente"
        issue_date = record.data_proximo_relatorio or current_day
    elif tcra_has_report_due_soon(record, today=current_day, rules=rule_set):
        issue_key = "relatorio_proximo"
        issue_label = "Relatório próximo"
        issue_date = record.data_proximo_relatorio or current_day
    elif tcra_has_stale_movement(record, today=current_day, rules=rule_set):
        issue_key = "sem_movimentacao"
        issue_label = "Sem movimentação"
        issue_date = tcra_last_movement_date(record) or record.data_assinatura or current_day
    elif tcra_has_missing_identity(record):
        issue_key = "sem_numero"
        issue_label = "Sem número TCRA"
        issue_date = last_touch or current_day
    elif tcra_has_missing_responsavel(record):
        issue_key = "sem_responsavel"
        issue_label = "Sem responsável"
        issue_date = last_touch or current_day
    elif tcra_has_missing_orgao(record):
        issue_key = "sem_orgao"
        issue_label = "Sem órgão"
        issue_date = last_touch or current_day
    else:
        return TcraSlaProfile(
            issue_key="",
            issue_label="",
            started_at=None,
            due_at=None,
            escalation_at=None,
            status="ok",
            summary="Sem prazo interno de tratamento pendente.",
        )

    started_at = max([item for item in (issue_date, last_touch) if item is not None], default=issue_date)
    due_at = started_at + timedelta(days=rule_set.treatment_sla_days) if started_at is not None else None
    escalation_at = started_at + timedelta(days=rule_set.escalation_sla_days) if started_at is not None else None

    status = "ok"
    overdue_days = 0
    if escalation_at is not None and current_day > escalation_at:
        status = "escalated"
        overdue_days = (current_day - escalation_at).days
        summary = f"Prazo interno de tratamento escalado há {overdue_days} dia(s); cobrar coordenação."
    elif due_at is not None and current_day > due_at:
        status = "overdue"
        overdue_days = (current_day - due_at).days
        summary = f"Prazo interno de tratamento atrasado há {overdue_days} dia(s)."
    elif due_at is not None and current_day == due_at:
        status = "due_today"
        summary = "Prazo interno de tratamento vence hoje."
    else:
        summary = (
            f"Prazo interno de tratamento em curso até {_format_date(due_at)}."
            if due_at is not None
            else "Prazo interno de tratamento em curso."
        )

    return TcraSlaProfile(
        issue_key=issue_key,
        issue_label=issue_label,
        started_at=started_at,
        due_at=due_at,
        escalation_at=escalation_at,
        status=status,
        overdue_days=overdue_days,
        summary=summary,
    )


def build_sla_queue(
    records: Sequence[Tcra],
    *,
    today: date | None = None,
    rules: TcraOperationalRules | None = None,
    limit: int = 0,
) -> tuple[TcraSlaQueueItem, ...]:
    current_day = today or date.today()
    rule_set = _safe_rules(rules)
    rows: list[TcraSlaQueueItem] = []
    status_rank = {"escalated": 0, "overdue": 1, "due_today": 2, "ok": 3}
    for record in records:
        profile = resolve_tcra_sla_profile(record, today=current_day, rules=rule_set)
        if not profile.issue_key:
            continue
        risk_profile = resolve_tcra_risk_profile(record, today=current_day, rules=rule_set)
        rows.append(
            TcraSlaQueueItem(
                uid=_stringify(record.uid),
                termo_label=_label_for_record(record),
                responsavel=_stringify(record.responsavel_execucao) or "(Sem responsável)",
                issue_label=profile.issue_label,
                status=profile.status,
                due_at=profile.due_at,
                escalation_at=profile.escalation_at,
                risk_score=risk_profile.score,
                summary=profile.summary,
            )
        )
    rows.sort(
        key=lambda item: (
            status_rank.get(item.status, 9),
            item.due_at or date.max,
            -int(item.risk_score or 0),
            item.termo_label.casefold(),
        )
    )
    if limit > 0:
        return tuple(rows[:limit])
    return tuple(rows)


def build_sla_summary(
    records: Sequence[Tcra],
    *,
    today: date | None = None,
    rules: TcraOperationalRules | None = None,
) -> TcraSlaSummary:
    queue = build_sla_queue(records, today=today, rules=rules, limit=0)
    due_today_count = sum(1 for item in queue if item.status == "due_today")
    overdue_count = sum(1 for item in queue if item.status == "overdue")
    escalated_count = sum(1 for item in queue if item.status == "escalated")
    summary_text = (
        f"Prazo interno de tratamento: {len(queue)} pendência(s) | "
        f"{due_today_count} vence(m) hoje | "
        f"{overdue_count} atrasada(s) | "
        f"{escalated_count} escalada(s)"
    )
    return TcraSlaSummary(
        total_items=len(queue),
        due_today_count=due_today_count,
        overdue_count=overdue_count,
        escalated_count=escalated_count,
        summary_text=summary_text,
    )


def find_potential_duplicate_tcras(
    record: Tcra,
    candidates: Sequence[Tcra],
    *,
    limit: int = 3,
    threshold: int = 72,
) -> tuple[TcraPotentialDuplicate, ...]:
    matches: list[TcraPotentialDuplicate] = []
    current_uid = _stringify(record.uid)
    for candidate in candidates:
        candidate_uid = _stringify(candidate.uid)
        if candidate_uid and candidate_uid == current_uid:
            continue

        weighted_score = 0.0
        weight_total = 0.0
        reasons: list[str] = []

        for label, weight, left, right in (
            ("TCRA", 4.0, record.numero_tcra, candidate.numero_tcra),
            ("processo", 3.0, record.numero_processo, candidate.numero_processo),
            ("local", 2.0, record.local, candidate.local),
            ("endereço", 1.5, record.endereco, candidate.endereco),
            ("bairro", 1.0, record.bairro, candidate.bairro),
        ):
            similarity = _sequence_similarity(left, right)
            if not _normalized_text(left) or not _normalized_text(right):
                continue
            weighted_score += similarity * weight
            weight_total += weight
            if similarity >= 0.98:
                reasons.append(f"{label} igual")
            elif similarity >= 0.82:
                reasons.append(f"{label} muito parecido")

        if weight_total <= 0:
            continue
        score = int(round((weighted_score / weight_total) * 100))
        if score < threshold:
            continue
        matches.append(
            TcraPotentialDuplicate(
                uid=candidate_uid,
                label=_label_for_record(candidate),
                score=score,
                reasons=tuple(dict.fromkeys(reasons)),
            )
        )

    matches.sort(key=lambda item: (-item.score, item.label.casefold(), item.uid.casefold()))
    return tuple(matches[: max(limit, 0)])


def build_workload_snapshot(
    records: Sequence[Tcra],
    *,
    today: date | None = None,
    rules: TcraOperationalRules | None = None,
) -> TcraWorkloadSnapshot:
    current_day = today or date.today()
    rule_set = _safe_rules(rules)
    grouped_records: dict[str, list[Tcra]] = defaultdict(list)
    unassigned: list[Tcra] = []

    for record in records:
        responsavel = _stringify(record.responsavel_execucao)
        if responsavel:
            grouped_records[responsavel].append(record)
        else:
            unassigned.append(record)

    entries: list[TcraWorkloadEntry] = []
    for responsavel, grouped in grouped_records.items():
        alert_count = 0
        high_risk_count = 0
        workload_score = 0
        for record in grouped:
            risk_profile = resolve_tcra_risk_profile(record, today=current_day, rules=rule_set)
            sla_profile = resolve_tcra_sla_profile(record, today=current_day, rules=rule_set)
            workload_score += risk_profile.score
            if sla_profile.status in {"overdue", "escalated"}:
                alert_count += 1
                workload_score += 25
            elif sla_profile.issue_key:
                workload_score += 10
            if risk_profile.band == "Alto":
                high_risk_count += 1
        entries.append(
            TcraWorkloadEntry(
                responsavel=responsavel,
                total_count=len(grouped),
                alert_count=alert_count,
                high_risk_count=high_risk_count,
                workload_score=workload_score,
            )
        )

    entries.sort(key=lambda item: (-item.workload_score, -item.total_count, item.responsavel.casefold()))
    suggestions: list[TcraWorkloadSuggestion] = []
    if entries and unassigned:
        receivers = sorted(entries, key=lambda item: (item.workload_score, item.total_count, item.responsavel.casefold()))
        for index, record in enumerate(sorted(unassigned, key=lambda item: operational_sort_key(item, today=current_day, rules=rule_set))):
            receiver = receivers[index % len(receivers)]
            suggestions.append(
                TcraWorkloadSuggestion(
                    record_uid=_stringify(record.uid),
                    record_label=_label_for_record(record),
                    suggested_responsavel=receiver.responsavel,
                    reason="Sem responsável no recorte atual; direcionar para a menor carga ativa.",
                )
            )

    summary_text = "Carga: sem responsáveis distribuídos."
    if entries:
        top = entries[0]
        summary_text = (
            f"Carga: {len(entries)} responsável(is) ativos | "
            f"maior fila {top.responsavel} ({top.total_count} termo(s), score {top.workload_score}) | "
            f"{len(suggestions)} sugestão(ões) de redistribuição"
        )

    return TcraWorkloadSnapshot(
        entries=tuple(entries),
        suggestions=tuple(suggestions),
        summary_text=summary_text,
    )


def build_responsavel_digests(
    records: Sequence[Tcra],
    *,
    today: date | None = None,
    rules: TcraOperationalRules | None = None,
    cadence: str = "daily",
) -> tuple[TcraResponsavelDigest, ...]:
    current_day = today or date.today()
    rule_set = _safe_rules(rules)
    cadence_label = "seu dia" if _stringify(cadence).lower().startswith("d") else "sua semana"
    grouped_records: dict[str, list[Tcra]] = defaultdict(list)
    for record in records:
        grouped_records[_stringify(record.responsavel_execucao) or "(Sem responsável)"].append(record)

    workload_map = {entry.responsavel: entry for entry in build_workload_snapshot(records, today=current_day, rules=rule_set).entries}
    digests: list[TcraResponsavelDigest] = []
    for responsavel, grouped in grouped_records.items():
        relevant = sorted(grouped, key=lambda item: operational_sort_key(item, today=current_day, rules=rule_set))
        escalated_count = 0
        alert_count = 0
        lines: list[str] = [f"Olá, {responsavel}. Prioridades para {cadence_label}:"]
        for record in relevant[:5]:
            profile = resolve_tcra_sla_profile(record, today=current_day, rules=rule_set)
            risk_profile = resolve_tcra_risk_profile(record, today=current_day, rules=rule_set)
            if profile.issue_key:
                alert_count += 1
            if profile.status == "escalated":
                escalated_count += 1
            lines.append(
                f"- {_label_for_record(record)} | {profile.issue_label or 'Rotina'} | "
                f"{profile.summary} | risco {risk_profile.band} {risk_profile.score}"
            )
        if len(relevant) > 5:
            lines.append(f"- +{len(relevant) - 5} termo(s) adicional(is) no recorte.")
        workload_score = int(getattr(workload_map.get(responsavel), "workload_score", 0) or 0)
        summary = (
            f"{responsavel}: {len(grouped)} termo(s) | "
            f"{alert_count} com prazo interno aberto | "
            f"{escalated_count} escalado(s) | "
            f"score {workload_score}"
        )
        digests.append(
            TcraResponsavelDigest(
                responsavel=responsavel,
                total_count=len(grouped),
                alert_count=alert_count,
                escalated_count=escalated_count,
                workload_score=workload_score,
                summary=summary,
                message_lines=tuple(lines),
            )
        )
    digests.sort(key=lambda item: (-item.alert_count, -item.workload_score, item.responsavel.casefold()))
    return tuple(digests)


def build_priority_route(
    records: Sequence[Tcra],
    *,
    today: date | None = None,
    rules: TcraOperationalRules | None = None,
    limit: int = 8,
) -> TcraRoutePlan:
    current_day = today or date.today()
    rule_set = _safe_rules(rules)
    grouped: dict[str, list[Tcra]] = defaultdict(list)
    for record in records:
        bairro = _stringify(record.bairro) or _stringify(record.local) or "Sem região"
        grouped[bairro].append(record)

    ordered_stops: list[TcraRouteStop] = []
    for bairro, grouped_records in sorted(grouped.items(), key=lambda item: item[0].casefold()):
        ranked = sorted(
            grouped_records,
            key=lambda item: operational_sort_key(item, today=current_day, rules=rule_set),
        )
        for record in ranked[:2]:
            risk_profile = resolve_tcra_risk_profile(record, today=current_day, rules=rule_set)
            ordered_stops.append(
                TcraRouteStop(
                    uid=_stringify(record.uid),
                    label=_label_for_record(record),
                    bairro=bairro,
                    query=", ".join(
                        part
                        for part in (record.endereco, record.local, record.bairro, "São Carlos SP")
                        if _stringify(part)
                    ),
                    priority_score=risk_profile.score,
                    reason=resolve_tcra_sla_profile(record, today=current_day, rules=rule_set).issue_label or "Rotina",
                )
            )

    ordered_stops.sort(key=lambda item: (-item.priority_score, item.bairro.casefold(), item.label.casefold()))
    selected = tuple(ordered_stops[: max(limit, 0)])
    summary_text = (
        f"Rota: {len(selected)} parada(s) priorizada(s) em {len({item.bairro for item in selected}) if selected else 0} região(ões)."
    )
    return TcraRoutePlan(stops=selected, summary_text=summary_text)


def _deserialize_event(payload: Mapping[str, object]) -> TcraEvento:
    return TcraEvento(
        sequence=int(payload.get("sequence") or 0),
        data_evento=_parse_date(payload.get("data_evento")),
        tipo_evento=_stringify(payload.get("tipo_evento")),
        descricao=_stringify(payload.get("descricao")),
        prazo_resultante=_parse_date(payload.get("prazo_resultante")),
        status_resultante=_stringify(payload.get("status_resultante")),
        protocolo=_stringify(payload.get("protocolo")),
        documento_ref=_stringify(payload.get("documento_ref")),
    )


def deserialize_tcra_payload(payload: Mapping[str, object] | None) -> Tcra | None:
    if not isinstance(payload, Mapping):
        return None
    uid = _stringify(payload.get("uid"))
    numero_processo = _stringify(payload.get("numero_processo"))
    numero_tcra = _stringify(payload.get("numero_tcra"))
    local = _stringify(payload.get("local"))
    if not any((uid, numero_processo, numero_tcra, local)):
        return None
    eventos_payload = payload.get("eventos") or ()
    eventos = [
        _deserialize_event(item)
        for item in eventos_payload
        if isinstance(item, Mapping)
    ]
    return Tcra(
        uid=uid,
        numero_processo=numero_processo,
        numero_tcra=numero_tcra,
        local=local,
        endereco=_stringify(payload.get("endereco")),
        bairro=_stringify(payload.get("bairro")),
        orgao_acompanhamento=_stringify(payload.get("orgao_acompanhamento")),
        status=_stringify(payload.get("status")),
        data_assinatura=_parse_date(payload.get("data_assinatura")),
        prazo_final=_parse_date(payload.get("prazo_final")),
        periodicidade_relatorio_meses=payload.get("periodicidade_relatorio_meses"),
        data_ultimo_relatorio=_parse_date(payload.get("data_ultimo_relatorio")),
        data_proximo_relatorio=_parse_date(payload.get("data_proximo_relatorio")),
        area_m2=payload.get("area_m2"),
        numero_mudas_previsto=payload.get("numero_mudas_previsto"),
        servicos_exigidos=_stringify(payload.get("servicos_exigidos")),
        responsavel_execucao=_stringify(payload.get("responsavel_execucao")),
        observacoes=_stringify(payload.get("observacoes")),
        mpsp_relacionado=_stringify(payload.get("mpsp_relacionado")),
        inquerito_civil=_stringify(payload.get("inquerito_civil")),
        eventos=eventos,
    )


def _week_start(value: date) -> date:
    return value - timedelta(days=value.weekday())


def build_audit_trend_summary(
    audit_events: Sequence[AuditEvent],
    *,
    today: date | None = None,
    rules: TcraOperationalRules | None = None,
    weeks: int = 6,
) -> TcraTrendSummary:
    current_day = today or date.today()
    rule_set = _safe_rules(rules)
    start_week = _week_start(current_day) - timedelta(days=max(weeks - 1, 0) * 7)
    buckets: dict[date, dict[str, int]] = {
        start_week + timedelta(days=index * 7): {
            "entered": 0,
            "exited": 0,
            "completed": 0,
            "changed": 0,
        }
        for index in range(max(weeks, 1))
    }

    for event in audit_events:
        raw_timestamp = _stringify(getattr(event, "timestamp", ""))
        if not raw_timestamp:
            continue
        try:
            event_day = datetime.fromisoformat(raw_timestamp.replace("Z", "+00:00")).astimezone().date()
        except ValueError:
            continue
        bucket_key = _week_start(event_day)
        if bucket_key not in buckets:
            continue
        before_record = deserialize_tcra_payload(getattr(event, "before", None))
        after_record = deserialize_tcra_payload(getattr(event, "after", None))
        if before_record is None and after_record is None:
            continue

        bucket = buckets[bucket_key]
        bucket["changed"] += 1

        before_risk = resolve_tcra_risk_profile(before_record, today=event_day, rules=rule_set) if before_record else None
        after_risk = resolve_tcra_risk_profile(after_record, today=event_day, rules=rule_set) if after_record else None
        if after_risk is not None and after_risk.band == "Alto" and (before_risk is None or before_risk.band != "Alto"):
            bucket["entered"] += 1
        if before_risk is not None and before_risk.band == "Alto" and (after_risk is None or after_risk.band != "Alto"):
            bucket["exited"] += 1

        before_status = resolve_operational_status(before_record, today=event_day) if before_record else ""
        after_status = resolve_operational_status(after_record, today=event_day) if after_record else ""
        if after_status == STATUS_CUMPRIDO and before_status != STATUS_CUMPRIDO:
            bucket["completed"] += 1

    trend_buckets = tuple(
        TcraTrendBucket(
            week_label=f"Semana de {_format_date(week)}",
            entered_high_risk_count=values["entered"],
            exited_high_risk_count=values["exited"],
            completed_count=values["completed"],
            changed_count=values["changed"],
        )
        for week, values in sorted(buckets.items())
    )
    if not trend_buckets:
        return TcraTrendSummary(buckets=(), summary_text="Tendência: sem histórico auditado.")

    latest = trend_buckets[-1]
    summary_text = (
        f"Tendência: {latest.week_label} | "
        f"{latest.entered_high_risk_count} entrou(ram) em alto risco | "
        f"{latest.exited_high_risk_count} saiu(ram) de alto risco | "
        f"{latest.completed_count} concluído(s)"
    )
    return TcraTrendSummary(buckets=trend_buckets, summary_text=summary_text)


def _event_matches_uid(event: AuditEvent, target_uid: str) -> bool:
    metadata = getattr(event, "metadata", {}) or {}
    if _stringify(metadata.get("uid")) == target_uid:
        return True
    before_record = deserialize_tcra_payload(getattr(event, "before", None))
    after_record = deserialize_tcra_payload(getattr(event, "after", None))
    return _stringify(getattr(before_record, "uid", "")) == target_uid or _stringify(getattr(after_record, "uid", "")) == target_uid


def _field_label(field_name: str) -> str:
    labels = {
        "numero_processo": "processo",
        "numero_tcra": "TCRA",
        "local": "local",
        "endereco": "endereço",
        "bairro": "bairro",
        "orgao_acompanhamento": "órgão",
        "status": "status",
        "data_assinatura": "assinatura",
        "prazo_final": "prazo final",
        "periodicidade_relatorio_meses": "periodicidade",
        "data_ultimo_relatorio": "último relatório",
        "data_proximo_relatorio": "próximo relatório",
        "responsavel_execucao": "responsável",
        "observacoes": "observações",
        "servicos_exigidos": "serviços",
        "mpsp_relacionado": "MPSP",
        "inquerito_civil": "inquérito",
        "eventos": "eventos",
    }
    return labels.get(field_name, field_name.replace("_", " "))


def _describe_payload_change(field_name: str, before: object, after: object) -> str:
    if field_name == "eventos":
        before_count = len(before) if isinstance(before, list) else 0
        after_count = len(after) if isinstance(after, list) else 0
        return f"eventos {before_count} -> {after_count}"
    before_text = _stringify(before) or "--"
    after_text = _stringify(after) or "--"
    return f"{_field_label(field_name)}: {before_text} -> {after_text}"


def build_record_change_timeline(
    audit_events: Sequence[AuditEvent],
    *,
    target_uid: str,
    today: date | None = None,
    rules: TcraOperationalRules | None = None,
    limit: int = 12,
) -> tuple[str, ...]:
    current_day = today or date.today()
    rule_set = _safe_rules(rules)
    lines: list[str] = []
    for event in audit_events:
        if not _event_matches_uid(event, target_uid):
            continue
        before_payload = getattr(event, "before", None) or {}
        after_payload = getattr(event, "after", None) or {}
        metadata = getattr(event, "metadata", {}) or {}
        changed_fields = list(metadata.get("changed_fields") or [])
        if not changed_fields and isinstance(before_payload, Mapping) and isinstance(after_payload, Mapping):
            changed_fields = sorted(
                key
                for key in set(before_payload) | set(after_payload)
                if before_payload.get(key) != after_payload.get(key)
            )
        changes = [
            _describe_payload_change(field_name, before_payload.get(field_name), after_payload.get(field_name))
            for field_name in changed_fields[:4]
        ]
        before_record = deserialize_tcra_payload(before_payload)
        after_record = deserialize_tcra_payload(after_payload)
        if before_record is not None or after_record is not None:
            before_risk = resolve_tcra_risk_profile(before_record, today=current_day, rules=rule_set) if before_record else None
            after_risk = resolve_tcra_risk_profile(after_record, today=current_day, rules=rule_set) if after_record else None
            if before_risk is not None and after_risk is not None and before_risk.band != after_risk.band:
                changes.append(
                    f"risco: {before_risk.band} {before_risk.score} -> {after_risk.band} {after_risk.score}"
                )
        summary = " | ".join(changes) if changes else _stringify(getattr(event, "summary", "")) or "Atualização registrada"
        lines.append(
            f"{format_audit_timestamp(_stringify(getattr(event, 'timestamp', '')))} | "
            f"{_stringify(getattr(event, 'action', '')).upper() or '--'} | {summary}"
        )
        if len(lines) >= max(limit, 0):
            break
    if not lines:
        return ("Nenhuma mudança auditada encontrada para este TCRA.",)
    return tuple(lines)


def build_record_change_timeline_text(
    audit_events: Sequence[AuditEvent],
    *,
    target_uid: str,
    today: date | None = None,
    rules: TcraOperationalRules | None = None,
    limit: int = 12,
) -> str:
    return "\n".join(
        build_record_change_timeline(
            audit_events,
            target_uid=target_uid,
            today=today,
            rules=rules,
            limit=limit,
        )
    )
