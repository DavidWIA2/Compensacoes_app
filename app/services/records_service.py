import re
import unicodedata
from typing import Dict, Iterable, List, Sequence, Optional

from app.models.compensacao import Compensacao


def remove_accents(input_str: str) -> str:
    """Remove acentos e caracteres especiais de uma string."""
    if not input_str:
        return ""
    nfkd_form = unicodedata.normalize('NFKD', input_str)
    return "".join([c for c in nfkd_form if not unicodedata.combining(c)])


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


def build_search_blob(record: Compensacao) -> str:
    blob = (
        f"{record.oficio_processo} {record.endereco} {record.endereco_plantio} "
        f"{record.microbacia} {record.av_tec} {record.caixa} {record.eletronico}"
    ).lower()
    return remove_accents(blob)


def build_record_search_index(records: Sequence[Compensacao]) -> Dict[str, str]:
    index: Dict[str, str] = {}
    for record in records:
        key = record.uid or str(record.excel_row)
        index[key] = build_search_blob(record)
    return index


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


def extract_year(text: str) -> Optional[str]:
    """Tenta extrair um ano (4 digitos) de um texto, priorizando o final do padrão '.../YYYY'."""
    if not text:
        return None
    # Procura por /20XX ou /19XX
    match = re.search(r'/(20\d{2}|19\d{2})', text)
    if match:
        return match.group(1)
    # Fallback: qualquer sequencia de 4 digitos que pareça um ano razoavel
    match = re.search(r'\b(20\d{2}|19\d{2})\b', text)
    if match:
        return match.group(1)
    return None


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
    selected_year: str = "Todos",
    search_index: Optional[Dict[str, str]] = None,
) -> List[Compensacao]:
    # Normaliza o texto de busca: remove acentos e deixa em minúsculo
    search_query = remove_accents(text or "").lower()
    
    selected_micros_set = {m.strip().upper() for m in (selected_micros or [])}
    selected_ele_set = {e.strip().upper() for e in (selected_eletronicos or [])}

    filtered = []
    for r in records:
        key = r.uid or str(r.excel_row)
        blob_normalized = search_index.get(key) if search_index is not None else None
        if blob_normalized is None:
            blob_normalized = build_search_blob(r)
        
        if search_query and search_query not in blob_normalized:
            continue

        if selected_year != "Todos":
            row_year = extract_year(r.oficio_processo)
            if row_year != selected_year:
                continue

        is_comp = row_is_compensado(r)
        if status == "Compensados" and not is_comp:
            continue
        if status == "Pendentes" and is_comp:
            continue

        # Só filtra se "Todos" não estiver marcado
        if not micro_all_selected:
            row_micro = (r.microbacia or "").strip().upper()
            if row_micro not in selected_micros_set:
                continue

        if not eletronico_all_selected:
            row_ele = (r.eletronico or "").strip().upper()
            if row_ele not in selected_ele_set:
                continue

        filtered.append(r)

    return filtered
