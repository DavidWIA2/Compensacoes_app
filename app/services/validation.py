from app.models.compensacao import Compensacao


def validate_compensacao(c: Compensacao) -> str:
    if not (c.oficio_processo or "").strip():
        return "Preencha Ofício/Processo."
    if not (c.av_tec or "").strip():
        return "Preencha Av. Tec."
    if str(c.compensacao).strip() == "":
        return "Preencha Compensação."
    return ""
