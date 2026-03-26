import json
import os
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox

from app.models.compensacao import Compensacao
from app.services.coordinates import build_heatmap_points
from app.services.geocode_service import geocode_address_arcgis
from app.services.geocode_update_service import (
    apply_geocode_to_record,
    build_cached_microbacia_finder,
    find_record_by_excel_row,
)
from app.services.plantio_service import (
    clone_plantios,
    plantio_choice_label,
    record_plantio_items,
    sync_legacy_plantio_fields,
)
from app.ui.components.ui_utils import msg_confirm, resource_path
from app.ui.components.workers import GeocodeWorker
from app.utils.logger import logger


class MapController:
    def __init__(self, window):
        self.window = window

    def _main_window_module(self):
        from app.ui import main_window as main_window_module

        return main_window_module

    def _current_form_plantios(self):
        return clone_plantios(self.window.form_plantios)

    def _choose_plantio_item(self, title: str, prompt: str, plantios):
        options = [plantio_choice_label(item, index) for index, item in enumerate(plantios, start=1)]
        selected, ok = QInputDialog.getItem(self.window, title, prompt, options, 0, False)
        if not ok or not selected:
            return None
        selected_index = options.index(selected)
        return plantios[selected_index]

    def update_address_search_enabled(self):
        has_end = bool(self.window.data_tab.in_end.text().strip())
        has_plantio = bool(self._current_form_plantios() or self.window.data_tab.in_end_plantio.text().strip())
        self.window.data_tab.btn_maps.setEnabled(self.window.data_tab.in_end.isEnabled() and has_end)
        self.window.data_tab.btn_maps_plantio.setEnabled(
            self.window.data_tab.btn_manage_plantios.isEnabled() and has_plantio
        )
        self.window.data_tab.btn_street_view.setEnabled(
            self.window.last_marker_coords is not None or has_end or has_plantio
        )

    def open_street_view(self):
        end_principal = self.window.data_tab.in_end.text().strip()
        plantios = self._current_form_plantios()

        choices = []
        if end_principal:
            choices.append(("Endereço Principal", end_principal))
        for index, item in enumerate(plantios, start=1):
            if item.endereco:
                choices.append((plantio_choice_label(item, index), item.endereco))

        target_address = None
        if not choices:
            if self.window.last_marker_coords:
                lat, lon = self.window.last_marker_coords
                url = f"https://www.google.com/maps/@?api=1&map_action=pano&viewpoint={lat},{lon}"
                QDesktopServices.openUrl(QUrl(url))
                logger.info(f"Street View aberto para marcador manual {lat}, {lon}")
                return

            QMessageBox.warning(
                self.window,
                "Atenção",
                "Nenhum endereço ou ponto no mapa selecionado para o Street View.",
            )
            return

        if len(choices) == 1:
            target_address = choices[0][1]
        else:
            labels = [label for label, _address in choices]
            selected, ok = QInputDialog.getItem(
                self.window,
                "Escolha o Endereço",
                "Qual endereço você deseja visualizar no Street View?",
                labels,
                0,
                False,
            )
            if not ok or not selected:
                return
            target_address = dict(choices).get(selected)

        if target_address:
            self.window.statusBar().showMessage(f"Geocodificando para Street View: {target_address}...")
            coords = geocode_address_arcgis(target_address)
            if coords:
                lat, lon = coords
                self.set_map_marker(lat, lon)
                url = f"https://www.google.com/maps/@?api=1&map_action=pano&viewpoint={lat},{lon}"
                QDesktopServices.openUrl(QUrl(url))
                logger.info(f"Street View aberto para {lat}, {lon} ({target_address})")
            else:
                QMessageBox.warning(self.window, "Erro", f"Não foi possível localizar o endereço: {target_address}")

    def load_custom_layer(self):
        path, _ = QFileDialog.getOpenFileName(
            self.window,
            "Adicionar Camada GIS",
            "",
            "Arquivos GIS (*.geojson *.json *.kml)",
        )
        if not path:
            return

        self.window.statusBar().showMessage(f"Carregando camada: {os.path.basename(path)}...")
        try:
            import fiona
            import geopandas as gpd

            fiona.drvsupport.supported_drivers["KML"] = "rw"
            gdf = gpd.read_file(path)
            if gdf.crs and gdf.crs.to_epsg() != 4326:
                gdf = gdf.to_crs(epsg=4326)

            geojson_obj = json.loads(gdf.to_json())
            script = f"""
            if(window.map) {{
                if(window.customLayer) window.map.removeLayer(window.customLayer);
                window.customLayer = L.geoJSON({json.dumps(geojson_obj)}, {{
                    style: function(feature) {{
                        return {{color: "#e74c3c", weight: 2, fillOpacity: 0.1, dashArray: '5, 5'}};
                    }}
                }}).addTo(window.map);
                window.map.fitBounds(window.customLayer.getBounds());
            }}
            """
            self.run_map_js(script, "load-custom-layer")
            QMessageBox.information(self.window, "Sucesso", "Camada carregada com sucesso.")
            logger.info(f"Camada GIS carregada: {path}")
        except Exception as exc:
            logger.error(f"Erro ao carregar camada GIS: {exc}")
            QMessageBox.critical(self.window, "Erro", f"Não foi possível ler o arquivo GIS:\n{exc}")
        finally:
            self.window.statusBar().showMessage("Pronto")

    def on_map_loaded(self, ok):
        if ok:
            self.window._initial_map_sync_timer.start(500)

    def initial_map_sync(self):
        self.window._apply_theme_to_map()
        layer = self.window.settings_controller.current_map_layer()
        self.run_map_js(f"if(window.setBaseLayer) window.setBaseLayer('{layer}');", "restore-layer")
        if self.window.gis:
            self.load_microbacias_layer()
        self.toggle_heatmap()

    def load_microbacias_layer(self):
        if self.window.gis:
            geojson = self.window.gis.to_geojson_obj()
            self.run_map_js(
                f"if(window.setMicrobacias) window.setMicrobacias({json.dumps(geojson)});",
                "load-microbacias",
            )

    def run_map_js(self, script: str, context: str):
        try:
            self.window.data_tab.web.page().runJavaScript(script)
        except Exception as exc:
            logger.error(f"[MAP JS] Falha em {context}: {exc}")

    def on_map_click(self, lat, lon):
        self.window.last_marker_coords = (lat, lon)
        self.set_map_marker(lat, lon)
        if self.window.gis:
            micro = self.window.gis.find_microbacia(lat, lon)
            if micro:
                self.window.data_tab.in_micro.setCurrentText(micro)
                self.highlight_microbacia(micro)
                self.set_map_status(f"Ponto dentro de: {micro}")
                self.window.statusBar().showMessage(f"Ponto capturado. Microbacia: {micro}")
            else:
                self.set_map_status("Fora de microbacia conhecida.")
                self.window.statusBar().showMessage(f"Ponto capturado: {lat:.5f}, {lon:.5f}")
        self.window._update_form_action_buttons()
        self.update_address_search_enabled()

    def set_map_marker(self, lat, lon):
        lat = float(lat)
        lon = float(lon)
        self.window.last_marker_coords = (lat, lon)
        self.run_map_js(f"if(window.setMarker) window.setMarker({lat}, {lon});", "marker")
        self.update_address_search_enabled()

    def highlight_microbacia(self, name: str):
        self.run_map_js(
            f"if(window.highlightGeoJsonByName) window.highlightGeoJsonByName('{self.window.MICROB_NAME_FIELD}', {json.dumps(name)});",
            "highlight",
        )

    def set_map_status(self, message: str):
        self.run_map_js(f"if(window.setStatus) window.setStatus({json.dumps(message)});", "status")

    def search_on_map(self):
        addr = self.window.data_tab.in_end.text().strip()
        if not addr:
            QMessageBox.warning(self.window, "Atenção", "Digite um endereço para pesquisar.")
            return
        self.window.statusBar().showMessage("Pesquisando endereço...")
        self.perform_geocode(addr)

    def search_on_map_plantio(self):
        plantios = self._current_form_plantios()
        if not plantios:
            QMessageBox.warning(self.window, "Atenção", "Cadastre ao menos um endereço de plantio para pesquisar.")
            return

        if len(plantios) == 1:
            target = plantios[0]
        else:
            target = self._choose_plantio_item(
                "Escolher Plantio",
                "Qual endereço de plantio você deseja buscar?",
                plantios,
            )
            if target is None:
                return

        self.window.statusBar().showMessage("Pesquisando endereço de plantio...")
        self.perform_geocode(target.endereco)

    def perform_geocode(self, address: str):
        main_window_module = self._main_window_module()
        coords = main_window_module.geocode_address_arcgis(address)
        if coords:
            self.set_map_marker(coords[0], coords[1])
            if self.window.gis:
                micro = self.window.gis.find_microbacia(*coords)
                if micro:
                    self.window.data_tab.in_micro.setCurrentText(micro)
                    self.highlight_microbacia(micro)
                    self.window.statusBar().showMessage(f"Localizado. Microbacia: {micro}")
                else:
                    self.window.statusBar().showMessage("Localizado (fora de microbacia)")
            self.window._update_form_action_buttons()
        else:
            QMessageBox.warning(self.window, "Não encontrado", "Não consegui localizar esse endereço.")
            self.window.statusBar().showMessage("Endereço não encontrado")

    def open_map_fullscreen(self):
        main_window_module = self._main_window_module()
        path = resource_path("app", "ui", "map_leaflet.html")
        dialog = main_window_module.MapFullScreenDialog(
            self.window,
            path,
            self.window.gis.to_geojson_obj() if self.window.gis else None,
            "dark" if self.window.is_dark_mode else "light",
            self.window.last_marker_coords,
            self.window.gis,
            self.window.settings_controller.current_map_layer(),
            [],
        )
        dialog.exec()

    def open_table_fullscreen(self):
        main_window_module = self._main_window_module()
        splitter = self.window.data_tab.splitter
        left_panel = self.window.data_tab.left_panel
        target_index = splitter.indexOf(left_panel)
        previous_sizes = splitter.sizes()

        def restore_panel(widget):
            splitter.insertWidget(target_index if target_index >= 0 else 0, widget)
            main_window_module.QTimer.singleShot(0, lambda: splitter.setSizes(previous_sizes))

        dialog = main_window_module.TableFullScreenDialog(self.window, left_panel, restore_panel)
        dialog.exec()

    def record_needs_batch_geocode(self, record: Compensacao) -> bool:
        has_main_address = bool((record.endereco or "").strip())
        has_main_coords = bool(str(getattr(record, "latitude", "")).strip() and str(getattr(record, "longitude", "")).strip())
        has_micro = bool((record.microbacia or "").strip())

        needs_main = has_main_address and (not has_main_coords or not has_micro)
        if needs_main:
            return True

        for plantio in record_plantio_items(record):
            has_address = bool((plantio.endereco or "").strip())
            has_coords = bool(str(plantio.latitude).strip() and str(plantio.longitude).strip())
            if has_address and (not has_coords or (not has_micro and not has_main_address)):
                return True
        return False

    def persist_batch_geocode_results(self, results: Dict[int, Dict[str, object]]) -> int:
        if not results:
            return 0

        micro_finder = build_cached_microbacia_finder(self.window.gis.find_microbacia) if self.window.gis else None
        updated_records: List[Compensacao] = []

        for excel_row, geocode_data in results.items():
            record = find_record_by_excel_row(self.window.records, excel_row)
            if not record:
                continue

            changed = False
            main_coords = geocode_data.get("main")
            if main_coords:
                lat, lon = float(main_coords[0]), float(main_coords[1])
                apply_geocode_to_record(record, lat, lon, micro_finder)
                changed = True

            plantio_coords = geocode_data.get("plantios", {}) or {}
            legacy_plantio_coords = geocode_data.get("plantio")
            if legacy_plantio_coords:
                first_plantio = next(iter(record_plantio_items(record)), None)
                if first_plantio:
                    plantio_coords[int(first_plantio.sequence)] = legacy_plantio_coords
            if plantio_coords:
                updated_plantios = []
                for plantio in record_plantio_items(record):
                    coords = plantio_coords.get(int(plantio.sequence))
                    if coords:
                        plantio.latitude = str(float(coords[0]))
                        plantio.longitude = str(float(coords[1]))
                        changed = True
                    updated_plantios.append(plantio)
                record.plantios = updated_plantios
                sync_legacy_plantio_fields(record)

                if not (record.microbacia or "").strip() and not main_coords and micro_finder:
                    first_coords = next(iter(plantio_coords.values()), None)
                    if first_coords:
                        try:
                            micro = micro_finder(float(first_coords[0]), float(first_coords[1]))
                        except Exception:
                            micro = ""
                        if micro and str(micro).strip():
                            record.microbacia = str(micro).strip()

            if changed:
                updated_records.append(record)

        return self.window.excel.save_batch_edits(updated_records)

    def run_batch_geocode(self):
        pending = [record for record in self.window.records if self.record_needs_batch_geocode(record)]
        if not pending:
            QMessageBox.information(self.window, "Sucesso", "Tudo georreferenciado!")
            return
        if msg_confirm(self.window, "GPS em Lote", f"Deseja buscar coordenadas para {len(pending)} registros?"):
            self.window.progress_bar.setVisible(True)
            self.window.progress_bar.setRange(0, len(pending))
            self.window.progress_bar.setValue(0)
            self.window.statusBar().showMessage("Iniciando geocodificação em lote...")
            self.window.geo_worker = GeocodeWorker(pending)
            self.window.geo_worker.progress_update.connect(
                lambda i, msg: (self.window.progress_bar.setValue(i), self.window.statusBar().showMessage(msg))
            )
            self.window.geo_worker.finished_process.connect(self.on_geocode_finished)
            self.window.geo_worker.start()

    def on_geocode_finished(self, results):
        self.window.progress_bar.setVisible(False)
        self.window.statusBar().showMessage("Geoprocessamento concluído.")
        if not results:
            QMessageBox.information(self.window, "Concluído", "Nenhum endereço pôde ser processado.")
            return

        try:
            updated = self.persist_batch_geocode_results(results)
        except Exception as exc:
            logger.error(f"Falha ao salvar geocodificação em lote: {exc}", exc_info=True)
            QMessageBox.critical(self.window, "Erro", f"Falha ao salvar coordenadas do GPS em lote: {exc}")
            return

        if updated:
            QMessageBox.information(self.window, "Concluído", f"{updated} registros tiveram coordenadas salvas.")
            self.window.reload()
        else:
            QMessageBox.information(self.window, "Concluído", "Nenhuma coordenada nova foi salva.")

    def toggle_heatmap(self):
        if not self.window.data_tab.chk_heatmap.isChecked():
            self.run_map_js("if(window.setHeatmap) window.setHeatmap([]);", "clear-heatmap")
            return

        typ = self.window.data_tab.combo_heatmap_type.currentText()
        points = []
        for record in self.window.filtered_records:
            points.extend(build_heatmap_points(record, typ))
        self.run_map_js(f"if(window.setHeatmap) window.setHeatmap({json.dumps(points)});", "update-heatmap")
