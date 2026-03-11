from pathlib import Path

import openpyxl

from app.models.compensacao import Compensacao
from app.services.excel_service import BACKUP_FOLDER_NAME, ExcelService


SHEET_NAME = "Compensa\u00e7\u00f5es"


def build_workbook(path: Path) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = SHEET_NAME
    ws.append(
        [
            "Of\u00edcio/ Processo",
            "Eletr\u00f4nico",
            "Caixa",
            "Av. Tec.",
            "Compensa\u00e7\u00e3o",
            "Endere\u00e7o",
            "Microbacia",
            "Compensado",
        ]
    )
    ws.append(["123/2026", "SIM", "CX-1", "AT-1", 8, "Rua A", "Gregorio", ""])
    wb.save(path)


def make_record(**overrides) -> Compensacao:
    base = {
        "excel_row": 3,
        "oficio_processo": "456/2026",
        "eletronico": "NAO",
        "caixa": "CX-2",
        "av_tec": "AT-2",
        "compensacao": "12",
        "endereco": "Rua B",
        "microbacia": "Monjolinho",
        "compensado": "SIM",
        "latitude": "-22.01",
        "longitude": "-47.89",
    }
    base.update(overrides)
    return Compensacao(**base)


def test_load_exposes_lat_lon_headers_without_mutating_workbook(tmp_path):
    path = tmp_path / "compensacoes.xlsx"
    build_workbook(path)

    service = ExcelService()
    records = service.load(str(path))

    assert len(records) == 1
    assert service.ws.cell(row=1, column=9).value == "Latitude"
    assert service.ws.cell(row=1, column=10).value == "Longitude"

    persisted = openpyxl.load_workbook(path)
    ws = persisted[SHEET_NAME]
    assert ws.max_column == 8
    assert ws.cell(row=1, column=9).value is None
    assert ws.cell(row=1, column=10).value is None


def test_load_does_not_create_backup(tmp_path):
    path = tmp_path / "compensacoes.xlsx"
    build_workbook(path)

    service = ExcelService()
    service.load(str(path))

    assert not (tmp_path / BACKUP_FOLDER_NAME).exists()


def test_add_new_persists_record_and_creates_backup(tmp_path):
    path = tmp_path / "compensacoes.xlsx"
    build_workbook(path)

    service = ExcelService()
    service.load(str(path))

    new_row = service.add_new(make_record())

    reloaded = openpyxl.load_workbook(path)
    ws = reloaded[SHEET_NAME]

    assert new_row == 3
    assert ws.cell(row=1, column=9).value == "Latitude"
    assert ws.cell(row=1, column=10).value == "Longitude"
    assert ws.cell(row=3, column=1).value == "456/2026"
    assert ws.cell(row=3, column=9).value == "-22.01"
    assert ws.cell(row=3, column=10).value == "-47.89"
    assert (tmp_path / BACKUP_FOLDER_NAME).exists()


def test_delete_record_shift_up_removes_row(tmp_path):
    path = tmp_path / "compensacoes.xlsx"
    build_workbook(path)

    service = ExcelService()
    service.load(str(path))
    service.add_new(make_record())

    service.delete_record_shift_up(2)

    reloaded = openpyxl.load_workbook(path)
    ws = reloaded[SHEET_NAME]

    assert ws.max_row == 2
    assert ws.cell(row=2, column=1).value == "456/2026"


def test_read_all_requires_loaded_path():
    service = ExcelService()

    try:
        service.read_all()
        assert False, "Era esperado ValueError quando path nao estiver carregado"
    except ValueError as exc:
        assert "Nenhum arquivo Excel carregado" in str(exc)
