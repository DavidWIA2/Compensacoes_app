from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, Iterable, List, Optional, Sequence

from app.models.tcra import Tcra

STATUS_TODOS = "Todos"
STATUS_SEM_STATUS = "Sem status"
STATUS_EM_ACOMPANHAMENTO = "Em acompanhamento"
STATUS_CUMPRIDO = "Cumprido"
STATUS_PRAZO_VENCIDO = "Prazo vencido"
STATUS_RELATORIO_PENDENTE = "Relatório pendente"
STATUS_ARQUIVADO = "Arquivado"
STATUS_SEM_VALIDADE = "Sem validade"

QUICK_FILTER_ALL = "all"
QUICK_FILTER_ALERTAS = "alertas"
QUICK_FILTER_PROXIMOS = "proximos"
QUICK_FILTER_SEM_NUMERO = "sem_numero"
QUICK_FILTER_SEM_RESPONSAVEL = "sem_responsavel"

AGENDA_SCOPE_TODOS = "todos"
AGENDA_SCOPE_HOJE = "hoje"
AGENDA_SCOPE_7D = "7d"
AGENDA_SCOPE_30D = "30d"
AGENDA_SCOPE_VENCIDOS = "vencidos"
AGENDA_SCOPE_PENDENTES = "pendentes"

UPCOMING_REPORT_WINDOW_DAYS = 30


@dataclass(frozen=True)
class TcraFilterFacets:
    total_count: int
    statuses: tuple[str, ...] = ()
    orgaos_acompanhamento: tuple[str, ...] = ()
    bairros: tuple[str, ...] = ()
    anos_processo: tuple[str, ...] = ()
    responsaveis_execucao: tuple[str, ...] = ()


@dataclass(frozen=True)
class TcraUpcomingReportSample:
    uid: str
    numero_processo: str
    numero_tcra: str
    local: str
    data_proximo_relatorio: date


@dataclass(frozen=True)
class TcraAgendaItem:
    uid: str
    priority_rank: int
    prioridade_label: str
    termo_label: str
    local: str
    detalhe: str
    data_referencia: date | None = None
    status_operacional: str = ""


@dataclass(frozen=True)
class TcraQualityQueueItem:
    uid: str
    severity_rank: int
    severity_label: str
    termo_label: str
    local: str
    detalhe: str
    issues: tuple[str, ...] = ()


@dataclass(frozen=True)
class TcraRecordOverview:
    total_count: int
    ativos_count: int
    cumpridos_count: int
    prazo_vencido_count: int
    relatorio_pendente_count: int
    mpsp_relacionados_count: int
    com_eventos_count: int
    sem_numero_tcra_count: int
    upcoming_30d_count: int = 0
    sem_responsavel_count: int = 0
    alertas_count: int = 0
    top_statuses: tuple[tuple[str, int], ...] = ()
    top_orgaos: tuple[tuple[str, int], ...] = ()
    upcoming_reports: tuple[TcraUpcomingReportSample, ...] = ()


def _stringify(value: object) -> str:
    return str(value or "").strip()


def remove_accents(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(char for char in normalized if not unicodedata.combining(char))


def normalize_key(value: object) -> str:
    return remove_accents(value).upper()


def _smart_label(value: object) -> str:
    text = _stringify(value)
    if not text:
        return ""

    lowercase_words = {"de", "da", "do", "das", "dos", "e"}
    words = []
    for raw_word in text.split():
        key = normalize_key(raw_word)
        if key in {"MPSP", "CETESB", "DAAE", "SAAE", "SMAA", "SMCQUA"}:
            words.append(key)
            continue
        lower_word = raw_word.lower()
        if lower_word in lowercase_words:
            words.append(lower_word)
            continue
        words.append(lower_word.capitalize())
    return " ".join(words)


def normalize_status_label(value: object) -> str:
    text = _stringify(value)
    normalized = normalize_key(text)
    if not normalized:
        return ""
    if "SEM VALIDADE" in normalized:
        return STATUS_SEM_VALIDADE
    if normalized in {"ARQUIVADO", "ARQUIVADA"}:
        return STATUS_ARQUIVADO
    if normalized in {"CUMPRIDO", "CONCLUIDO", "CONCLUIDA", "ENCERRADO", "ENCERRADA"}:
        return STATUS_CUMPRIDO
    if "PRAZO" in normalized and "VENC" in normalized:
        return STATUS_PRAZO_VENCIDO
    if "RELATORIO" in normalized and ("PEND" in normalized or "ATRAS" in normalized):
        return STATUS_RELATORIO_PENDENTE
    if "ACOMPANH" in normalized or normalized in {"ATIVO", "EM ANDAMENTO"}:
        return STATUS_EM_ACOMPANHAMENTO
    if normalized in {"SEM STATUS", "SEM INFORMACAO"}:
        return STATUS_SEM_STATUS
    return _smart_label(text)


def normalize_orgao_label(value: object) -> str:
    text = _stringify(value)
    normalized = normalize_key(text)
    if not normalized:
        return ""
    if "MINISTERIO PUBLICO" in normalized or "PROMOTORIA" in normalized or normalized == "MPSP":
        return "MPSP"
    if "CETESB" in normalized:
        return "CETESB"
    if "DAAE" in normalized:
        return "DAAE"
    if "SAAE" in normalized:
        return "SAAE"
    if "SMAA" in normalized:
        return "SMAA"
    if "SMCQUA" in normalized:
        return "SMCQUA"
    return _smart_label(text)


def normalize_event_type_label(value: object) -> str:
    text = _stringify(value)
    normalized = normalize_key(text)
    if not normalized:
        return ""
    if normalized == "RELATORIO":
        return "Relatório"
    if normalized == "RELATORIO ENTREGUE":
        return "Relatório entregue"
    if normalized == "OBSERVACAO":
        return "Observação"
    return _smart_label(text)


def unique_non_empty(values: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    unique_values: list[str] = []
    for value in values:
        clean = str(value or "").strip()
        if not clean:
            continue
        key = normalize_key(clean)
        if key in seen:
            continue
        seen.add(key)
        unique_values.append(clean)
    return sorted(unique_values)


def extract_year(text: str) -> Optional[str]:
    if not text:
        return None
    match = re.search(r"/(20\d{2}|19\d{2})", text)
    if match:
        return match.group(1)
    match = re.search(r"\b(20\d{2}|19\d{2})\b", text)
    if match:
        return match.group(1)
    return None


def build_search_blob(record: Tcra) -> str:
    parts = [
        record.numero_processo,
        record.numero_tcra,
        record.local,
        record.endereco,
        record.bairro,
        record.orgao_acompanhamento,
        record.status,
        record.servicos_exigidos,
        record.responsavel_execucao,
        record.observacoes,
        record.mpsp_relacionado,
        record.inquerito_civil,
    ]
    for evento in record.eventos:
        parts.extend((evento.tipo_evento, evento.descricao, evento.status_resultante))
    return remove_accents(" ".join(part for part in parts if part)).lower()


def build_record_search_index(records: Sequence[Tcra]) -> Dict[str, str]:
    index: Dict[str, str] = {}
    for position, record in enumerate(records, start=1):
        key = record.uid or f"tcra:{position}"
        index[key] = build_search_blob(record)
    return index


def tcra_is_cumprido(record: Tcra) -> bool:
    return normalize_status_label(record.status) in {STATUS_CUMPRIDO, STATUS_ARQUIVADO}


def tcra_has_prazo_vencido(record: Tcra, *, today: date | None = None) -> bool:
    if tcra_is_cumprido(record):
        return False
    current_day = today or date.today()
    return bool(record.prazo_final and record.prazo_final < current_day)


def tcra_has_relatorio_pendente(record: Tcra, *, today: date | None = None) -> bool:
    if tcra_is_cumprido(record):
        return False
    current_day = today or date.today()
    return bool(record.data_proximo_relatorio and record.data_proximo_relatorio < current_day)


def tcra_has_report_due_soon(
    record: Tcra,
    *,
    today: date | None = None,
    within_days: int = UPCOMING_REPORT_WINDOW_DAYS,
) -> bool:
    if tcra_is_cumprido(record):
        return False
    current_day = today or date.today()
    if record.data_proximo_relatorio is None:
        return False
    limit_day = current_day + timedelta(days=max(int(within_days or 0), 0))
    return current_day <= record.data_proximo_relatorio <= limit_day


def tcra_has_missing_identity(record: Tcra) -> bool:
    return not _stringify(record.numero_tcra)


def tcra_has_missing_responsavel(record: Tcra) -> bool:
    return not _stringify(record.responsavel_execucao)


def tcra_has_missing_orgao(record: Tcra) -> bool:
    return not normalize_orgao_label(record.orgao_acompanhamento)


def tcra_is_mpsp_related(record: Tcra) -> bool:
    explicit_flag = normalize_key(record.mpsp_relacionado)
    if explicit_flag in {"SIM", "S", "YES", "Y", "1", "VERDADEIRO"}:
        return True
    if "MPSP" in normalize_key(record.orgao_acompanhamento):
        return True
    return bool(str(record.inquerito_civil or "").strip())


def resolve_operational_status(record: Tcra, *, today: date | None = None) -> str:
    normalized_status = normalize_status_label(record.status)
    normalized = normalize_key(normalized_status)
    if normalized_status == STATUS_SEM_VALIDADE:
        return STATUS_SEM_VALIDADE
    if normalized_status in {STATUS_CUMPRIDO, STATUS_ARQUIVADO}:
        return STATUS_CUMPRIDO
    if normalized_status == STATUS_PRAZO_VENCIDO or ("PRAZO" in normalized and "VENC" in normalized):
        return STATUS_PRAZO_VENCIDO
    if normalized_status == STATUS_RELATORIO_PENDENTE or ("RELATORIO" in normalized and ("PEND" in normalized or "ATRAS" in normalized)):
        return STATUS_RELATORIO_PENDENTE
    if tcra_has_prazo_vencido(record, today=today):
        return STATUS_PRAZO_VENCIDO
    if tcra_has_relatorio_pendente(record, today=today):
        return STATUS_RELATORIO_PENDENTE
    if normalized_status == STATUS_EM_ACOMPANHAMENTO or normalized in {"EM ACOMPANHAMENTO", "ACOMPANHAMENTO", "ATIVO"}:
        return STATUS_EM_ACOMPANHAMENTO
    if normalized_status:
        return normalized_status
    if record.prazo_final or record.data_proximo_relatorio or record.data_ultimo_relatorio:
        return STATUS_EM_ACOMPANHAMENTO
    return STATUS_SEM_STATUS


def resolve_operational_issues(record: Tcra, *, today: date | None = None) -> tuple[str, ...]:
    issues: list[str] = []
    if tcra_has_prazo_vencido(record, today=today):
        issues.append("Prazo final vencido")
    if tcra_has_relatorio_pendente(record, today=today):
        issues.append("Relatório pendente")
    elif tcra_has_report_due_soon(record, today=today):
        issues.append(f"Relatório nos próximos {UPCOMING_REPORT_WINDOW_DAYS} dias")
    if tcra_has_missing_identity(record):
        issues.append("Sem número TCRA")
    if tcra_has_missing_responsavel(record):
        issues.append("Sem responsável")
    if tcra_has_missing_orgao(record):
        issues.append("Sem órgão")
    return tuple(issues)


def resolve_record_consistency_issues(record: Tcra, *, today: date | None = None) -> tuple[str, ...]:
    issues: list[str] = []
    normalized_status = normalize_status_label(record.status)

    if record.periodicidade_relatorio_meses is not None and record.periodicidade_relatorio_meses <= 0:
        issues.append("Periodicidade de relatório deve ser maior que zero.")
    if record.data_assinatura and record.prazo_final and record.prazo_final < record.data_assinatura:
        issues.append("Prazo final não pode ser anterior à data de assinatura.")
    if record.data_ultimo_relatorio and record.data_proximo_relatorio:
        if record.data_proximo_relatorio < record.data_ultimo_relatorio:
            issues.append("Próximo relatório não pode ser anterior ao último relatório.")
    if normalized_status in {STATUS_CUMPRIDO, STATUS_ARQUIVADO} and record.data_proximo_relatorio is not None:
        issues.append("TCRA cumprido/arquivado não deve manter próximo relatório em aberto.")
    if normalized_status == STATUS_RELATORIO_PENDENTE and record.data_proximo_relatorio is None:
        issues.append("Status 'Relatório pendente' exige data do próximo relatório.")
    if normalized_status == STATUS_PRAZO_VENCIDO and record.prazo_final is None:
        issues.append("Status 'Prazo vencido' exige prazo final informado.")
    if tcra_has_prazo_vencido(record, today=today) and normalized_status in {STATUS_CUMPRIDO, STATUS_ARQUIVADO}:
        issues.append("Status concluído conflita com prazo vencido em aberto.")
    return tuple(issues)


def build_quality_queue(
    records: Sequence[Tcra],
    *,
    today: date | None = None,
    limit: int = 8,
) -> tuple[TcraQualityQueueItem, ...]:
    queue: list[TcraQualityQueueItem] = []
    current_day = today or date.today()
    records_by_uid = {record.uid: record for record in records}

    for record in records:
        consistency_issues = list(resolve_record_consistency_issues(record, today=current_day))
        cadastro_issues: list[str] = []
        if tcra_has_missing_identity(record):
            cadastro_issues.append("Sem número TCRA")
        if tcra_has_missing_responsavel(record):
            cadastro_issues.append("Sem responsável")
        if tcra_has_missing_orgao(record):
            cadastro_issues.append("Sem órgão")

        issues = consistency_issues + [issue for issue in cadastro_issues if issue not in consistency_issues]
        if not issues:
            continue

        if consistency_issues:
            severity_rank = 0
            severity_label = "Critico"
        else:
            severity_rank = 1
            severity_label = "Cadastro"

        detalhe = issues[0]
        if len(issues) > 1:
            detalhe = f"{detalhe} | +{len(issues) - 1} pendencia(s)"

        queue.append(
            TcraQualityQueueItem(
                uid=record.uid,
                severity_rank=severity_rank,
                severity_label=severity_label,
                termo_label=_stringify(record.numero_tcra or record.numero_processo or record.uid),
                local=_stringify(record.local or record.endereco or "--"),
                detalhe=detalhe,
                issues=tuple(issues),
            )
        )

    sorted_queue = sorted(
        queue,
        key=lambda item: (
            item.severity_rank,
            -len(item.issues),
            operational_sort_key(records_by_uid[item.uid], today=current_day),
        ),
    )
    if limit <= 0:
        return tuple(sorted_queue)
    return tuple(sorted_queue[:limit])


def build_operational_agenda(
    records: Sequence[Tcra],
    *,
    today: date | None = None,
    limit: int = 8,
) -> tuple[TcraAgendaItem, ...]:
    agenda_rows: list[TcraAgendaItem] = []
    current_day = today or date.today()

    for record in records:
        priority_rank: int | None = None
        prioridade_label = ""
        data_referencia: date | None = None
        detalhe_principal = ""

        if tcra_has_prazo_vencido(record, today=current_day):
            priority_rank = 0
            prioridade_label = "Prazo vencido"
            data_referencia = record.prazo_final
            detalhe_principal = f"Prazo final em {_format_agenda_date(record.prazo_final)}."
        elif tcra_has_relatorio_pendente(record, today=current_day):
            priority_rank = 1
            prioridade_label = "Relatório pendente"
            data_referencia = record.data_proximo_relatorio
            detalhe_principal = f"Relatório previsto em {_format_agenda_date(record.data_proximo_relatorio)}."
        elif tcra_has_report_due_soon(record, today=current_day):
            priority_rank = 2
            prioridade_label = "Relatório próximo"
            data_referencia = record.data_proximo_relatorio
            detalhe_principal = f"Relatório previsto em {_format_agenda_date(record.data_proximo_relatorio)}."
        elif tcra_has_missing_identity(record):
            priority_rank = 3
            prioridade_label = "Cadastro incompleto"
            detalhe_principal = "Sem número TCRA informado."
        elif tcra_has_missing_responsavel(record):
            priority_rank = 4
            prioridade_label = "Sem responsável"
            detalhe_principal = "Defina um responsável de execução."
        elif tcra_has_missing_orgao(record):
            priority_rank = 5
            prioridade_label = "Sem órgão"
            detalhe_principal = "Informe o órgão de acompanhamento."
        else:
            consistency_issues = resolve_record_consistency_issues(record, today=current_day)
            if consistency_issues:
                priority_rank = 6
                prioridade_label = "Revisar cadastro"
                detalhe_principal = consistency_issues[0]

        if priority_rank is None:
            continue

        extra_issues = [issue for issue in resolve_operational_issues(record, today=current_day) if issue not in detalhe_principal]
        if extra_issues:
            detalhe = f"{detalhe_principal} {' | '.join(extra_issues[:2])}".strip()
        else:
            detalhe = detalhe_principal
        agenda_rows.append(
            TcraAgendaItem(
                uid=record.uid,
                priority_rank=priority_rank,
                prioridade_label=prioridade_label,
                termo_label=_stringify(record.numero_tcra or record.numero_processo or record.uid),
                local=_stringify(record.local or record.endereco or "--"),
                detalhe=detalhe,
                data_referencia=data_referencia,
                status_operacional=resolve_operational_status(record, today=current_day),
            )
        )

    sorted_rows = sorted(
        agenda_rows,
        key=lambda item: (
            item.priority_rank,
            item.data_referencia or date.max,
            item.termo_label.lower(),
            item.uid.lower(),
        ),
    )
    if limit <= 0:
        return tuple(sorted_rows)
    return tuple(sorted_rows[:limit])


def filter_agenda_items_by_scope(
    items: Sequence[TcraAgendaItem],
    *,
    scope: str = AGENDA_SCOPE_TODOS,
    today: date | None = None,
) -> tuple[TcraAgendaItem, ...]:
    current_day = today or date.today()
    normalized_scope = _stringify(scope).lower() or AGENDA_SCOPE_TODOS

    if normalized_scope == AGENDA_SCOPE_TODOS:
        return tuple(items)

    def includes(item: TcraAgendaItem) -> bool:
        if normalized_scope == AGENDA_SCOPE_VENCIDOS:
            return item.priority_rank == 0
        if normalized_scope == AGENDA_SCOPE_PENDENTES:
            return item.priority_rank in {1, 3, 4, 5, 6}
        if normalized_scope == AGENDA_SCOPE_HOJE:
            if item.priority_rank in {0, 1, 3, 4, 5, 6}:
                return True
            return bool(item.priority_rank == 2 and item.data_referencia and item.data_referencia <= current_day)
        if normalized_scope == AGENDA_SCOPE_7D:
            if item.priority_rank in {0, 1, 3, 4, 5, 6}:
                return True
            return bool(
                item.priority_rank == 2
                and item.data_referencia
                and item.data_referencia <= current_day + timedelta(days=7)
            )
        if normalized_scope == AGENDA_SCOPE_30D:
            if item.priority_rank in {0, 1, 3, 4, 5, 6}:
                return True
            return bool(
                item.priority_rank == 2
                and item.data_referencia
                and item.data_referencia <= current_day + timedelta(days=UPCOMING_REPORT_WINDOW_DAYS)
            )
        return True

    return tuple(item for item in items if includes(item))


def build_work_agenda(
    records: Sequence[Tcra],
    *,
    scope: str = AGENDA_SCOPE_TODOS,
    today: date | None = None,
    limit: int = 8,
) -> tuple[TcraAgendaItem, ...]:
    scoped_items = filter_agenda_items_by_scope(
        build_operational_agenda(records, today=today, limit=0),
        scope=scope,
        today=today,
    )
    if limit <= 0:
        return scoped_items
    return tuple(scoped_items[:limit])


def suggest_issue_fix(issue: str) -> str:
    normalized_issue = remove_accents(issue).lower()
    if "numero tcra" in normalized_issue:
        return "Informe o número oficial do termo ou registre um identificador interno temporário."
    if "responsavel" in normalized_issue:
        return "Defina o responsável pela execução para a equipe conseguir acompanhar o termo."
    if "orgao" in normalized_issue:
        return "Preencha o órgão de acompanhamento para orientar cobranças e relatórios."
    if "periodicidade" in normalized_issue:
        return "Use um número de meses maior que zero para o ciclo de relatórios."
    if "prazo final nao pode ser anterior" in normalized_issue:
        return "Revise as datas de assinatura e prazo final; o prazo precisa ser posterior à assinatura."
    if "proximo relatorio nao pode ser anterior" in normalized_issue:
        return "Ajuste o último ou o próximo relatório para manter a sequência cronológica."
    if "cumprido/arquivado" in normalized_issue and "proximo relatorio" in normalized_issue:
        return "Se o termo foi encerrado, limpe o próximo relatório; se ainda está ativo, revise o status."
    if "relatorio pendente" in normalized_issue and "exige data do proximo relatorio" in normalized_issue:
        return "Informe a data prevista do próximo relatório para manter o status pendente coerente."
    if "prazo vencido" in normalized_issue and "exige prazo final" in normalized_issue:
        return "Preencha o prazo final antes de marcar o termo como prazo vencido."
    if "status concluido conflita" in normalized_issue:
        return "Revise o status ou atualize o prazo final para remover o conflito de encerramento."
    return "Revise esse campo no cadastro e confirme a informação mais atual do termo."


def _format_agenda_date(value: date | None) -> str:
    if value is None:
        return "--"
    return value.strftime("%d/%m/%Y")


def resolve_quick_filter_count(records: Sequence[Tcra], mode: str, *, today: date | None = None) -> int:
    return len(apply_quick_filter(records, mode=mode, today=today))


def apply_quick_filter(records: Sequence[Tcra], *, mode: str, today: date | None = None) -> List[Tcra]:
    if mode == QUICK_FILTER_ALERTAS:
        return [
            record
            for record in records
            if tcra_has_prazo_vencido(record, today=today) or tcra_has_relatorio_pendente(record, today=today)
        ]
    if mode == QUICK_FILTER_PROXIMOS:
        return [record for record in records if tcra_has_report_due_soon(record, today=today)]
    if mode == QUICK_FILTER_SEM_NUMERO:
        return [record for record in records if tcra_has_missing_identity(record)]
    if mode == QUICK_FILTER_SEM_RESPONSAVEL:
        return [record for record in records if tcra_has_missing_responsavel(record)]
    return list(records)


def operational_sort_key(record: Tcra, *, today: date | None = None) -> tuple[int, date, str, str]:
    if tcra_has_prazo_vencido(record, today=today):
        priority = 0
    elif tcra_has_relatorio_pendente(record, today=today):
        priority = 1
    elif tcra_has_report_due_soon(record, today=today):
        priority = 2
    elif tcra_has_missing_identity(record) or tcra_has_missing_responsavel(record):
        priority = 3
    elif resolve_operational_status(record, today=today) == STATUS_CUMPRIDO:
        priority = 5
    elif resolve_operational_status(record, today=today) == STATUS_SEM_VALIDADE:
        priority = 6
    else:
        priority = 4

    deadline = record.data_proximo_relatorio or record.prazo_final or date.max
    return (
        priority,
        deadline,
        _stringify(record.numero_processo or record.numero_tcra or record.local).lower(),
        _stringify(record.uid).lower(),
    )


def compute_metrics(records: Sequence[Tcra], *, today: date | None = None) -> Dict[str, object]:
    status_counter: Counter[str] = Counter()
    orgao_counter: Counter[str] = Counter()
    total_count = len(records)
    cumpridos_count = 0
    prazo_vencido_count = 0
    relatorio_pendente_count = 0
    mpsp_relacionados_count = 0
    com_eventos_count = 0
    sem_numero_tcra_count = 0
    sem_responsavel_count = 0
    sem_orgao_count = 0
    relatorio_proximo_30d_count = 0
    alertas_count = 0

    for record in records:
        operational_status = resolve_operational_status(record, today=today)
        status_counter[operational_status] += 1
        orgao_counter[normalize_orgao_label(record.orgao_acompanhamento) or "(Sem órgão)"] += 1

        if operational_status == STATUS_CUMPRIDO:
            cumpridos_count += 1
        has_prazo_vencido = tcra_has_prazo_vencido(record, today=today)
        has_relatorio_pendente = tcra_has_relatorio_pendente(record, today=today)
        if has_prazo_vencido:
            prazo_vencido_count += 1
        if has_relatorio_pendente:
            relatorio_pendente_count += 1
        if has_prazo_vencido or has_relatorio_pendente:
            alertas_count += 1
        if tcra_has_report_due_soon(record, today=today):
            relatorio_proximo_30d_count += 1
        if tcra_is_mpsp_related(record):
            mpsp_relacionados_count += 1
        if record.eventos:
            com_eventos_count += 1
        if tcra_has_missing_identity(record):
            sem_numero_tcra_count += 1
        if tcra_has_missing_responsavel(record):
            sem_responsavel_count += 1
        if not normalize_orgao_label(record.orgao_acompanhamento):
            sem_orgao_count += 1

    return {
        "count_total": total_count,
        "count_ativos": total_count - cumpridos_count,
        "count_cumpridos": cumpridos_count,
        "count_prazo_vencido": prazo_vencido_count,
        "count_relatorio_pendente": relatorio_pendente_count,
        "count_mpsp_relacionados": mpsp_relacionados_count,
        "count_com_eventos": com_eventos_count,
        "count_sem_numero_tcra": sem_numero_tcra_count,
        "count_sem_responsavel": sem_responsavel_count,
        "count_sem_orgao": sem_orgao_count,
        "count_relatorio_proximo_30d": relatorio_proximo_30d_count,
        "count_alertas": alertas_count,
        "status_sorted": tuple(status_counter.most_common()),
        "orgaos_sorted": tuple(orgao_counter.most_common()),
    }


def filter_tcras(
    records: Sequence[Tcra],
    *,
    text: str,
    status: str,
    selected_orgaos: Sequence[str],
    selected_bairros: Sequence[str],
    selected_year: str = STATUS_TODOS,
    only_mpsp: bool = False,
    only_relatorio_pendente: bool = False,
    only_prazo_vencido: bool = False,
    search_index: Optional[Dict[str, str]] = None,
    today: date | None = None,
) -> List[Tcra]:
    search_query = remove_accents(text or "").lower()
    status_key = normalize_key(status)
    selected_orgaos_set = {normalize_key(item) for item in selected_orgaos or []}
    selected_bairros_set = {normalize_key(item) for item in selected_bairros or []}

    filtered: list[Tcra] = []
    for position, record in enumerate(records, start=1):
        key = record.uid or f"tcra:{position}"
        search_blob = search_index.get(key) if search_index is not None else None
        if search_blob is None:
            search_blob = build_search_blob(record)

        if search_query and search_query not in search_blob:
            continue

        if status_key and status_key != normalize_key(STATUS_TODOS):
            operational_status = resolve_operational_status(record, today=today)
            if status_key not in {normalize_key(operational_status), normalize_key(record.status)}:
                continue

        if selected_year and selected_year != STATUS_TODOS:
            if extract_year(record.numero_processo) != selected_year:
                continue

        if selected_orgaos_set:
            if normalize_key(record.orgao_acompanhamento) not in selected_orgaos_set:
                continue

        if selected_bairros_set:
            if normalize_key(record.bairro) not in selected_bairros_set:
                continue

        if only_mpsp and not tcra_is_mpsp_related(record):
            continue

        if only_relatorio_pendente and not tcra_has_relatorio_pendente(record, today=today):
            continue

        if only_prazo_vencido and not tcra_has_prazo_vencido(record, today=today):
            continue

        filtered.append(record)

    return filtered


def build_filter_facets(records: Sequence[Tcra], *, today: date | None = None) -> TcraFilterFacets:
    years = [year for year in (extract_year(record.numero_processo) for record in records) if year]
    sorted_years = tuple(sorted(set(years), reverse=True))

    return TcraFilterFacets(
        total_count=len(records),
        statuses=tuple(unique_non_empty(resolve_operational_status(record, today=today) for record in records)),
        orgaos_acompanhamento=tuple(unique_non_empty(normalize_orgao_label(record.orgao_acompanhamento) for record in records)),
        bairros=tuple(unique_non_empty(record.bairro for record in records)),
        anos_processo=sorted_years,
        responsaveis_execucao=tuple(unique_non_empty(record.responsavel_execucao for record in records)),
    )


def build_record_overview(records: Sequence[Tcra], *, today: date | None = None) -> TcraRecordOverview:
    metrics = compute_metrics(records, today=today)
    upcoming_candidates = sorted(
        (
            record
            for record in records
            if record.data_proximo_relatorio and not tcra_is_cumprido(record)
        ),
        key=lambda item: (item.data_proximo_relatorio or date.max, item.numero_processo, item.uid),
    )

    return TcraRecordOverview(
        total_count=int(metrics["count_total"]),
        ativos_count=int(metrics["count_ativos"]),
        cumpridos_count=int(metrics["count_cumpridos"]),
        prazo_vencido_count=int(metrics["count_prazo_vencido"]),
        relatorio_pendente_count=int(metrics["count_relatorio_pendente"]),
        mpsp_relacionados_count=int(metrics["count_mpsp_relacionados"]),
        com_eventos_count=int(metrics["count_com_eventos"]),
        sem_numero_tcra_count=int(metrics["count_sem_numero_tcra"]),
        upcoming_30d_count=int(metrics["count_relatorio_proximo_30d"]),
        sem_responsavel_count=int(metrics["count_sem_responsavel"]),
        alertas_count=int(metrics["count_alertas"]),
        top_statuses=tuple(metrics["status_sorted"]),
        top_orgaos=tuple(metrics["orgaos_sorted"]),
        upcoming_reports=tuple(
            TcraUpcomingReportSample(
                uid=record.uid,
                numero_processo=record.numero_processo,
                numero_tcra=record.numero_tcra,
                local=record.local,
                data_proximo_relatorio=record.data_proximo_relatorio,
            )
            for record in upcoming_candidates[:5]
            if record.data_proximo_relatorio is not None
        ),
    )
