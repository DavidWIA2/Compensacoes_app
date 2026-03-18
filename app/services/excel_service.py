import os
import shutil
import glob
import tempfile
import time
import uuid
from datetime import datetime
from typing import List, Optional, Dict

import openpyxl
from openpyxl.cell.cell import MergedCell
from openpyxl.worksheet.worksheet import Worksheet

from app.models.compensacao import Compensacao
from app.models.display_columns import DISPLAY_COLUMNS
from app.utils.logger import logger

MAX_BACKUPS = 10
BACKUP_FOLDER_NAME = "backups_historico"
SHEET_NAME = "Compensa\u00e7\u00f5es"

# Mapeamento de nomes de colunas esperados para facilitar a localiza\u00e7\u00e3o din\u00e2mica
EXPECTED_HEADERS = {
    **{attr: label for label, attr in DISPLAY_COLUMNS},
    "latitude_plantio": "Lat_Plantio",
    "longitude_plantio": "Lon_Plantio",
    "latitude": "Latitude",
    "longitude": "Longitude",
    "uid": "UID",
}


class InvalidFileError(Exception):
    """Excecao levantada quando o arquivo nao e um Excel valido."""
    pass

class ExcelService:
    def __init__(self):
        self.path: Optional[str] = None
        self.wb: Optional[openpyxl.Workbook] = None
        self.ws: Optional[Worksheet] = None
        self.col_map: Dict[str, int] = {}  # Mapeia nome interno para indice da coluna (1-based)
        self.uid_to_row: Dict[str, int] = {} # Cache de UID para numero da linha
        self.last_backup_time = 0
        self.merged_cells_warning = False

    def _is_valid_zip_signature(self, path: str) -> bool:
        """Verifica os Magic Numbers de arquivos ZIP (como .xlsx)"""
        try:
            with open(path, 'rb') as f:
                header = f.read(4)
                return header == b'PK\x03\x04'
        except Exception:
            return False

    def _save_workbook(self) -> None:
        if not self.wb or not self.path:
            raise ValueError("Nenhuma planilha carregada para salvar.")

        target_dir = os.path.dirname(os.path.abspath(self.path)) or "."
        fd, tmp_path = tempfile.mkstemp(prefix="compensacoes_", suffix=".xlsx", dir=target_dir)
        os.close(fd)
        try:
            self.wb.save(tmp_path)
            os.replace(tmp_path, self.path)
        except Exception:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                logger.warning(f"[EXCEL] Nao foi possivel remover arquivo temporario: {tmp_path}")
            raise

    def load(self, path: str) -> List[Compensacao]:
        if not os.path.exists(path):
            raise FileNotFoundError(f"Arquivo nao encontrado: {path}")
            
        if not self._is_valid_zip_signature(path):
            raise InvalidFileError(f"O arquivo nao parece ser uma planilha Excel valida (.xlsx corrompido ou formato incorreto): {path}")

        self.path = path
        from zipfile import BadZipFile
        try:
            self.wb = openpyxl.load_workbook(path, data_only=False)
        except BadZipFile:
            raise InvalidFileError("O arquivo Excel esta corrompido ou nao pode ser lido (Erro interno de ZIP).")
        except Exception as e:
            raise RuntimeError(f"Erro inesperado ao abrir a planilha: {e}")

        nome_aba_alvo = SHEET_NAME
        if nome_aba_alvo in self.wb.sheetnames:
            self.ws = self.wb[nome_aba_alvo]
        else:
            self.ws = self.wb.active

        self._ensure_tracking_headers()
        self._build_column_map()

        records = []
        needs_save = False
        self.uid_to_row.clear()
        self.merged_cells_warning = False
        
        seen_uids = set()

        for row_idx, row_cells in enumerate(self.ws.iter_rows(min_row=2, values_only=False), start=2):
            # Extrai valores usando o mapa de colunas
            def get_val(key):
                col = self.col_map.get(key)
                if col and col <= len(row_cells):
                    return row_cells[col-1].value
                return None

            # Verifica se a linha esta vazia (nos campos principais)
            main_vals = [get_val(k) for k in ["oficio_processo", "eletronico", "caixa", "av_tec"]]
            if all(v is None or str(v).strip() == "" for v in main_vals):
                continue

            uid_val = self._str(get_val("uid"))
            
            # PROTECAO: Se o UID for nulo ou DUPLICADO (ex: copy-paste no Excel), gera um novo
            if not uid_val or uid_val in seen_uids:
                uid_val = uuid.uuid4().hex
                col_uid = self.col_map.get("uid")
                if col_uid:
                    self.ws.cell(row=row_idx, column=col_uid).value = uid_val
                    needs_save = True
            
            seen_uids.add(uid_val)
            self.uid_to_row[uid_val] = row_idx

            records.append(
                Compensacao(
                    excel_row=row_idx,
                    oficio_processo=self._str(get_val("oficio_processo")),
                    eletronico=self._str(get_val("eletronico")),
                    caixa=self._str(get_val("caixa")),
                    av_tec=self._str(get_val("av_tec")),
                    compensacao=get_val("compensacao"),
                    endereco=self._str(get_val("endereco")),
                    microbacia=self._str(get_val("microbacia")),
                    compensado=self._str(get_val("compensado")),
                    endereco_plantio=self._str(get_val("endereco_plantio")),
                    latitude_plantio=self._str(get_val("latitude_plantio")),
                    longitude_plantio=self._str(get_val("longitude_plantio")),
                    latitude=self._str(get_val("latitude")),
                    longitude=self._str(get_val("longitude")),
                    uid=uid_val
                )
            )
        
        if needs_save:
            try:
                self._save_workbook()
            except Exception as e:
                logger.warning(f"[EXCEL] Nao foi possivel salvar novos UIDs gerados na leitura: {e}")

        return records

    def _build_column_map(self):
        """Mapeia os cabecalhos reais do Excel para as chaves internas do App com tolerância a variações."""
        self.col_map.clear()
        if not self.ws:
            return

        headers = [str(cell.value).strip() if cell.value else "" for cell in self.ws[1]]
        
        from app.services.records_service import remove_accents
        def normalize(t):
            return remove_accents(str(t)).strip().upper()

        normalized_headers = [normalize(h) for h in headers]
        
        for key, expected_name in EXPECTED_HEADERS.items():
            norm_expected = normalize(expected_name)
            try:
                # Tenta busca exata normalizada
                idx = normalized_headers.index(norm_expected) + 1
                self.col_map[key] = idx
            except ValueError:
                # Tenta busca parcial (se o cabeçalho contém o nome esperado)
                found = False
                for i, h in enumerate(normalized_headers):
                    if norm_expected in h or h in norm_expected:
                        self.col_map[key] = i + 1
                        found = True
                        break
                if not found:
                    logger.warning(f"[EXCEL] Coluna '{expected_name}' nao mapeada.")

    def _create_rotating_backup(self):
        if not self.path:
            return

        now = time.time()
        if now - self.last_backup_time < 300:
            return
        self.last_backup_time = now

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
            logger.warning(f"[EXCEL] Nao foi possivel criar backup: {e}")

        files = glob.glob(os.path.join(backup_dir, "*.xlsx"))
        files.sort(key=os.path.getmtime)
        while len(files) > MAX_BACKUPS:
            oldest = files.pop(0)
            try:
                os.remove(oldest)
            except Exception as exc:
                logger.warning(f"[EXCEL] Nao foi possivel remover backup antigo '{oldest}': {exc}")

    def _find_row_by_uid(self, uid: str) -> Optional[int]:
        if not self.ws or not uid:
            return None
        
        col_uid = self.col_map.get("uid")
        if not col_uid:
            return None

        # Primeiro tenta o cache rapido
        if uid in self.uid_to_row:
            row = self.uid_to_row[uid]
            # Valida se o UID ainda esta la
            try:
                if self.ws.cell(row=row, column=col_uid).value == uid:
                    return row
            except Exception:
                pass
        
        # Se falhou, faz a busca lenta (O(N)) e atualiza o cache
        for row_idx, row_cells in enumerate(self.ws.iter_rows(min_row=2, min_col=col_uid, max_col=col_uid, values_only=True), start=2):
            if row_cells[0] == uid:
                self.uid_to_row[uid] = row_idx
                return row_idx
        return None

    def _row_has_values(self, row_idx: int) -> bool:
        if not self.ws:
            return False

        for col_idx in range(1, self.ws.max_column + 1):
            value = self.ws.cell(row=row_idx, column=col_idx).value
            if value is None:
                continue
            if isinstance(value, str) and not value.strip():
                continue
            return True
        return False

    def add_new(self, c: Compensacao) -> int:
        self._create_rotating_backup()
        # Encontra a primeira linha realmente vazia para evitar sobrescrever linhas parciais.
        new_row = 2
        while self._row_has_values(new_row):
            new_row += 1
            
        if not c.uid:
            c.uid = uuid.uuid4().hex
        c.excel_row = new_row
        self._write_row(new_row, c)
        self.uid_to_row[c.uid] = new_row
        self._save_workbook()
        return new_row

    def save_edit(self, c: Compensacao):
        self._create_rotating_backup()
        target_row = self._resolve_target_row(c)
        self._write_row(target_row, c)
        self._save_workbook()

    def save_batch_edits(self, records: List[Compensacao]) -> int:
        if not records:
            return 0

        self._create_rotating_backup()
        updated = 0
        for record in records:
            target_row = self._resolve_target_row(record)
            self._write_row(target_row, record)
            updated += 1
        self._save_workbook()
        return updated

    def delete_record_shift_up(self, row_idx: int, uid: str = ""):
        self._create_rotating_backup()
        target_row = row_idx
        if uid:
            found_row = self._find_row_by_uid(uid)
            if not found_row:
                raise LookupError("Nao foi possivel localizar o registro pelo UID. Recarregue a planilha e tente novamente.")
            target_row = found_row
            if uid in self.uid_to_row:
                del self.uid_to_row[uid]
                 
        self.ws.delete_rows(target_row, 1)
        # Invalida o cache pois as linhas mudaram de posicao
        self.uid_to_row.clear()
        self._save_workbook()

    def read_all(self) -> List[Compensacao]:
        if not self.path:
            raise ValueError("Nenhum arquivo Excel carregado.")
        return self.load(self.path)

    def _write_row(self, row: int, c: Compensacao):
        # Mapeia os dados do objeto para as chaves internas
        data_map = {
            "oficio_processo": c.oficio_processo,
            "eletronico": c.eletronico,
            "caixa": c.caixa,
            "av_tec": c.av_tec,
            "compensacao": c.compensacao,
            "endereco": c.endereco,
            "microbacia": c.microbacia,
            "compensado": c.compensado,
            "endereco_plantio": c.endereco_plantio,
            "latitude_plantio": c.latitude_plantio,
            "longitude_plantio": c.longitude_plantio,
            "latitude": c.latitude,
            "longitude": c.longitude,
            "uid": c.uid
        }

        for key, valor in data_map.items():
            col_idx = self.col_map.get(key)
            if not col_idx:
                continue
                
            cell = self.ws.cell(row=row, column=col_idx)
            if not isinstance(cell, MergedCell):
                cell.value = valor
            else:
                self.merged_cells_warning = True

    def _resolve_target_row(self, c: Compensacao) -> int:
        target_row = c.excel_row
        if c.uid:
            found_row = self._find_row_by_uid(c.uid)
            if found_row:
                target_row = found_row
                c.excel_row = found_row
        return target_row

    def _ensure_tracking_headers(self):
        """Verifica e corrige a estrutura basica dos cabecalhos."""
        if not self.ws:
            return

        headers = [str(cell.value).strip() if cell.value else "" for cell in self.ws[1]]
        from app.services.records_service import remove_accents

        def normalize(text: str) -> str:
            return remove_accents(str(text)).strip().upper()

        normalized_headers = {normalize(header) for header in headers if header}
        
        # Migracao: Se faltarem colunas criticas, insere ao final
        for key, label in EXPECTED_HEADERS.items():
            if normalize(label) not in normalized_headers:
                new_col = len(headers) + 1
                self.ws.cell(row=1, column=new_col).value = label
                headers.append(label)
                normalized_headers.add(normalize(label))

    def _str(self, v) -> str:
        return "" if v is None else str(v).strip()
