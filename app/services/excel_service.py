import os
import shutil
import glob
from datetime import datetime
from typing import List, Optional
import openpyxl
from openpyxl.worksheet.worksheet import Worksheet
# ADICIONE ESTA LINHA ABAIXO:
from openpyxl.cell.cell import MergedCell
from app.models.compensacao import Compensacao

MAX_BACKUPS = 10
BACKUP_FOLDER_NAME = "backups_historico"


class ExcelService:
    def __init__(self):
        self.path: Optional[str] = None
        self.wb: Optional[openpyxl.Workbook] = None
        self.ws: Optional[Worksheet] = None
        self.headers: dict = {}

    def load(self, path: str) -> List[Compensacao]:
        if not os.path.exists(path): raise FileNotFoundError(f"Arquivo não encontrado: {path}")
        self.path = path
        self._create_rotating_backup()

        self.wb = openpyxl.load_workbook(path, data_only=False)
        self.ws = self.wb.active

        # Garante cabeçalhos para Lat/Lon se não existirem (Colunas 9 e 10)
        if self.ws.max_column < 10:
            self.ws.cell(row=1, column=9, value="Latitude")
            self.ws.cell(row=1, column=10, value="Longitude")
            self.wb.save(self.path)

        records = []
        for row_idx, row_cells in enumerate(self.ws.iter_rows(min_row=2, values_only=False), start=2):
            vals = [c.value for c in row_cells]
            if not vals or all(v is None or str(v).strip() == "" for v in vals[:8]): continue

            def get_v(i):
                return vals[i] if i < len(vals) else None

            c = Compensacao(
                excel_row=row_idx,
                oficio_processo=self._str(get_v(0)),
                eletronico=self._str(get_v(1)),
                caixa=self._str(get_v(2)),
                av_tec=self._str(get_v(3)),
                compensacao=get_v(4),
                endereco=self._str(get_v(5)),
                microbacia=self._str(get_v(6)),
                compensado=self._str(get_v(7)),
                latitude=self._str(get_v(8)),
                longitude=self._str(get_v(9))
            )
            records.append(c)
        return records

    def _create_rotating_backup(self):
        if not self.path: return
        base_dir = os.path.dirname(self.path)
        backup_dir = os.path.join(base_dir, BACKUP_FOLDER_NAME)
        os.makedirs(backup_dir, exist_ok=True)
        filename = os.path.basename(self.path)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        backup_name = f"{os.path.splitext(filename)[0]}_{timestamp}.xlsx"
        backup_path = os.path.join(backup_dir, backup_name)
        try:
            shutil.copy2(self.path, backup_path)
        except Exception as e:
            print(f"Aviso: Não foi possível criar backup: {e}")
        files = glob.glob(os.path.join(backup_dir, "*.xlsx"))
        files.sort(key=os.path.getmtime)
        while len(files) > MAX_BACKUPS:
            oldest = files.pop(0)
            try:
                os.remove(oldest)
            except Exception:
                pass

    def add_new(self, c: Compensacao) -> int:
        self._create_rotating_backup()
        new_row = self.ws.max_row + 1
        self._write_row(new_row, c)
        self.wb.save(self.path)
        return new_row

    def save_edit(self, c: Compensacao):
        self._create_rotating_backup()
        self._write_row(c.excel_row, c)
        self.wb.save(self.path)

    def delete_record_shift_up(self, row_idx: int):
        self._create_rotating_backup()
        self.ws.delete_rows(row_idx, 1)
        self.wb.save(self.path)

    def read_all(self) -> List[Compensacao]:
        return self.load(self.path)

    # Em app/services/excel_service.py
    from openpyxl.cell.cell import MergedCell

    def _write_row(self, row: int, c: Compensacao):
        # Mapeamento dos dados para as colunas 1 a 10
        dados = [
            c.oficio_processo, c.eletronico, c.caixa, c.av_tec,
            c.compensacao, c.endereco, c.microbacia, c.compensado,
            c.latitude, c.longitude
        ]

        for col_idx, valor in enumerate(dados, start=1):
            cell = self.ws.cell(row=row, column=col_idx)

            # Agora que MergedCell foi importado, isinstance funcionará
            if not isinstance(cell, MergedCell):
                cell.value = valor
            else:
                # Log opcional para o console para saber quais linhas têm problemas
                print(f"Linha {row}, Col {col_idx}: Célula mesclada ignorada.")

    def _str(self, v) -> str:
        return "" if v is None else str(v).strip()