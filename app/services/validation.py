from datetime import date

from app.models.compensacao import Compensacao
from app.services.plantio_service import validate_record_plantios
from app.services.records_service import extract_year


def _parse_brazilian_number(value) -> float:
    if isinstance(value, (int, float)):
        return float(value)

    s = str(value or "").strip().replace(" ", "")
    if not s:
        raise ValueError("empty")

    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")

    return float(s)


def _validate_lat_lon(c: Compensacao) -> str:
    lat_raw = str(c.latitude or "").strip()
    lon_raw = str(c.longitude or "").strip()

    if not lat_raw and not lon_raw:
        return ""
    if (lat_raw and not lon_raw) or (lon_raw and not lat_raw):
        return "Preencha latitude e longitude juntas."

    try:
        lat = _parse_brazilian_number(lat_raw)
        lon = _parse_brazilian_number(lon_raw)
    except ValueError:
        return "Latitude/Longitude invalidas."

    if not (-90 <= lat <= 90):
        return "Latitude deve estar entre -90 e 90."
    if not (-180 <= lon <= 180):
        return "Longitude deve estar entre -180 e 180."

    return ""


def validate_compensacao(c: Compensacao) -> str:
    oficio_processo = (c.oficio_processo or "").strip()
    if not oficio_processo:
        return "Preencha Of\u00edcio/Processo."

    oficio_year = extract_year(oficio_processo)
    if oficio_year and int(oficio_year) > date.today().year:
        return f"O ano de Of\u00edcio/Processo n\u00e3o pode ser maior que {date.today().year}."

    if not (c.av_tec or "").strip():
        return "Preencha Av. Tec."

    compensacao_raw = str((c.compensacao if c.compensacao is not None else "")).strip()
    if compensacao_raw == "":
        return "Preencha Compensa\u00e7\u00e3o."

    try:
        compensacao = _parse_brazilian_number(compensacao_raw)
    except ValueError:
        return "Compensa\u00e7\u00e3o deve ser num\u00e9rica."

    if compensacao <= 0:
        return "Compensa\u00e7\u00e3o deve ser maior que zero."

    lat_lon_err = _validate_lat_lon(c)
    if lat_lon_err:
        return lat_lon_err

    plantio_err = validate_record_plantios(c)
    if plantio_err:
        return plantio_err

    return ""
