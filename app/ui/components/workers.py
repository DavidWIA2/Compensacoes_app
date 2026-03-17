import time
from PySide6.QtCore import QThread, Signal
from app.services.geocode_service import geocode_address_arcgis
from app.utils.logger import logger

class GeocodeWorker(QThread):
    progress_update = Signal(int, str)
    finished_process = Signal(object)

    def __init__(self, records_to_process):
        super().__init__()
        self.records = records_to_process
        self.is_running = True
        self.resultados = {}  # {excel_row: {"main": (lat, lon), "plantio": (lat, lon)}}

    def run(self):
        total = len(self.records)
        for i, r in enumerate(self.records):
            if not self.is_running:
                break
            
            res = {}
            lat_m = str(getattr(r, "latitude", "")).strip()
            lon_m = str(getattr(r, "longitude", "")).strip()
            lat_p = str(getattr(r, "latitude_plantio", "")).strip()
            lon_p = str(getattr(r, "longitude_plantio", "")).strip()
            micro = str(getattr(r, "microbacia", "")).strip()
            has_main_coords = bool(lat_m and lon_m)
            has_plantio_coords = bool(lat_p and lon_p)

            if (r.endereco or "").strip():
                if not has_main_coords:
                    self.progress_update.emit(i, f"Principal ({i + 1}/{total}): {str(r.endereco)[:30]}...")
                    try:
                        coords = self._geocode_api(r.endereco)
                        if coords:
                            res["main"] = coords
                    except Exception as e:
                        logger.error(f"[GEOCODE] Erro ao buscar endereço principal (linha {r.excel_row}): {e}")
                    time.sleep(0.3)
                elif not micro:
                    res["main"] = (float(lat_m), float(lon_m))

            if (r.endereco_plantio or "").strip():
                if not has_plantio_coords:
                    self.progress_update.emit(i, f"Plantio ({i + 1}/{total}): {str(r.endereco_plantio)[:30]}...")
                    try:
                        coords = self._geocode_api(r.endereco_plantio)
                        if coords:
                            res["plantio"] = coords
                    except Exception as e:
                        logger.error(f"[GEOCODE] Erro ao buscar endereço de plantio (linha {r.excel_row}): {e}")
                    time.sleep(0.3)
                elif not micro and not res.get("main"):
                    res["plantio"] = (float(lat_p), float(lon_p))

            if res:
                self.resultados[r.excel_row] = res

        self.finished_process.emit(self.resultados)

    def stop(self):
        self.is_running = False

    def _geocode_api(self, address: str):
        return geocode_address_arcgis(address, timeout=8)

class UpdaterWorker(QThread):
    update_available = Signal(str, str) # version, release_notes

    def run(self):
        try:
            # Simulação de requisição HTTP para a API do GitHub ou Servidor Interno
            import random
            
            # Espera não-bloqueante de 3 segundos
            for _ in range(30):
                if self.isInterruptionRequested():
                    return
                self.msleep(100)
            
            if random.random() > 0.5:
                # Simulando que a versão atual é 1.0 e achamos a 2.0
                self.update_available.emit(
                    "v2.0.0", 
                    "- Novo Dashboard Interativo\n- Máquina do Tempo de Backups\n- Mapas Offline via Cache"
                )
        except Exception:
            pass
