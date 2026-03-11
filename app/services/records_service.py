from typing import Dict, Iterable, List, Sequence

from app.models.compensacao import Compensacao


def safe_upper(s: str) -> str:
    return str(s).strip().upper() if s is not None else ""


def unique_non_empty(values: Iterable[str]) -> List[str]:
    seen = set()
    out = []
    for v in values:
        v = str(v).strip() if v is not None else ""
        if not v:
            continue
        key = v.upper()
        if key not in seen:
            seen.add(key)
            out.append(v)
    return sorted(out)


def row_is_compensado(c: Compensacao) -> bool:
    return safe_upper(c.compensado) == "SIM"


def to_float(value) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace(",", ".")
    if not s:
        return 0.0
    try:
        return float(s)
    except Exception:
        return 0.0


def compute_metrics(records: Sequence[Compensacao]) -> Dict[str, object]:
    total_geral = 0.0
    total_pendente = 0.0
    total_compensado = 0.0
    count_total = 0
    count_comp = 0
    count_pend = 0
    pend_micro: Dict[str, float] = {}
    pend_ele: Dict[str, float] = {}

    for r in records:
        val = to_float(r.compensacao)
        total_geral += val
        count_total += 1
        if row_is_compensado(r):
            total_compensado += val
            count_comp += 1
        else:
            total_pendente += val
            count_pend += 1
            micro = (r.microbacia or "").strip() or "(Sem microbacia)"
            pend_micro[micro] = pend_micro.get(micro, 0.0) + val
            ele = (r.eletronico or "").strip() or "(Sem eletrônico)"
            pend_ele[ele] = pend_ele.get(ele, 0.0) + val

    micro_sorted = sorted(pend_micro.items(), key=lambda x: x[1], reverse=True)
    ele_sorted = sorted(pend_ele.items(), key=lambda x: x[1], reverse=True)

    return {
        "total_geral": total_geral,
        "total_pendente": total_pendente,
        "total_compensado": total_compensado,
        "count_total": count_total,
        "count_comp": count_comp,
        "count_pend": count_pend,
        "pend_micro_sorted": micro_sorted,
        "pend_ele_sorted": ele_sorted,
    }


def filter_records(
    records: Sequence[Compensacao],
    *,
    text: str,
    status: str,
    selected_micros: Sequence[str],
    selected_eletronicos: Sequence[str],
    micro_all_selected: bool,
    eletronico_all_selected: bool,
) -> List[Compensacao]:
    normalized_text = (text or "").strip().lower()
    selected_micros_set = set(selected_micros or [])
    selected_ele_set = set(selected_eletronicos or [])

    filtered = []
    for r in records:
        blob = f"{r.oficio_processo} {r.endereco} {r.microbacia} {r.av_tec} {r.caixa} {r.eletronico}".lower()
        if normalized_text and normalized_text not in blob:
            continue

        is_comp = row_is_compensado(r)
        if status == "Compensados" and not is_comp:
            continue
        if status == "Pendentes" and is_comp:
            continue

        if not micro_all_selected and r.microbacia not in selected_micros_set:
            continue

        if not eletronico_all_selected and r.eletronico not in selected_ele_set:
            continue

        filtered.append(r)

    return filtered
