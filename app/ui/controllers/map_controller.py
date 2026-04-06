import json
from typing import Dict

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox

from app.application.use_cases.authoritative_persistence import AuthoritativePersistenceUseCases
from app.application.use_cases.batch_geocode_operations import BatchGeocodeOperationsUseCases
from app.application.use_cases.map_interactions import MapInteractionsUseCases
from app.application.use_cases.map_layer_operations import MapLayerOperationsUseCases
from app.application.use_cases.map_rendering import MapRenderingUseCases
from app.models.compensacao import Compensacao
from app.services.geocode_service import geocode_address_arcgis
from app.services.geocode_update_service import (
    build_cached_microbacia_finder,
)
from app.services.plantio_service import (
    clone_plantios,
    record_plantio_items,
)
from app.ui.components.dialogs import MapFullScreenDialog, TableFullScreenDialog
from app.ui.components.job_specs import BackgroundJobSpec, build_disconnect_callback
from app.ui.components.ui_utils import msg_confirm, resource_path
from app.ui.components.workers import GeocodeWorker
from app.utils.logger import get_logger


logger = get_logger("UI.Map")

BATCH_GEOCODE_JOB_NAME = "batch_geocode"


class MapController:
    def __init__(self, window):
        self.window = window
        self.geocode_worker_factory = None
        self.batch_geocode_use_cases = BatchGeocodeOperationsUseCases()
        self.map_use_cases = MapInteractionsUseCases()
        self.map_rendering_use_cases = MapRenderingUseCases()
        self.map_layer_use_cases = MapLayerOperationsUseCases(self.map_rendering_use_cases)
        session_runtime = getattr(window, "session_runtime", None)
        self.persistence = getattr(window, "authoritative_persistence", None) or AuthoritativePersistenceUseCases(
            session_runtime,
            window.audit_service,
            getattr(window, "persistence_service", None),
        )
        self.local_record_queries = self.persistence.local_record_queries
        self.local_mutation_sync = self.persistence.local_mutation_sync
        self.local_write_authority = self.persistence.local_write_authority
        self.authoritative_write = self.persistence.authoritative_write

    def _current_session_path(self) -> str:
        if hasattr(self.window, "shell_controller"):
            return self.window.shell_controller.current_session_path()
        runtime = getattr(self.window, "session_runtime", None)
        if runtime is None:
            return ""
        return str(getattr(runtime, "session_path", getattr(runtime, "path", "")) or "").strip()

    def _bind_runtime_persistence_service(self) -> None:
        self.persistence.bind_runtime_window(self.window)

    def _store_local_mutation_status(self, status) -> None:
        self.persistence.store_local_mutation_status(self.window, status)

    def _store_authoritative_write_status(self, status) -> None:
        self.persistence.store_authoritative_write_status(self.window, status)

    def _log_authoritative_write_issues(self, operation: str, issues) -> None:
        self.persistence.log_preparation_issues(operation, issues)

    def _current_form_plantios(self):
        return clone_plantios(self.window.form_plantios)

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
        plan = self.map_use_cases.build_street_view_plan(
            main_address=self.window.data_tab.in_end.text().strip(),
            plantios=self._current_form_plantios(),
            marker_coords=self.window.last_marker_coords,
        )

        if not plan.choices:
            if plan.marker_fallback:
                lat, lon = plan.marker_fallback
                QDesktopServices.openUrl(QUrl(self.map_use_cases.build_street_view_url(lat=lat, lon=lon)))
                logger.info(f"Street View aberto para marcador manual {lat}, {lon}")
                return

            QMessageBox.warning(self.window, plan.empty_title, plan.empty_message)
            return

        if len(plan.choices) == 1:
            target_address = plan.choices[0].address
        else:
            labels = [choice.label for choice in plan.choices]
            selected, ok = QInputDialog.getItem(
                self.window,
                plan.chooser_title,
                plan.chooser_prompt,
                labels,
                0,
                False,
            )
            if not ok or not selected:
                return
            target_address = self.map_use_cases.resolve_choice(plan, selected)

        if target_address:
            self.window.statusBar().showMessage(
                self.map_use_cases.build_geocoding_status(target_address, purpose="street_view")
            )
            coords = geocode_address_arcgis(target_address)
            if coords:
                lat, lon = coords
                self.set_map_marker(lat, lon)
                QDesktopServices.openUrl(QUrl(self.map_use_cases.build_street_view_url(lat=lat, lon=lon)))
                logger.info(f"Street View aberto para {lat}, {lon} ({target_address})")
            else:
                failure = self.map_use_cases.build_street_view_lookup_failure(target_address)
                QMessageBox.warning(self.window, failure.warning_title, failure.warning_message)

    def load_custom_layer(self):
        path, _ = QFileDialog.getOpenFileName(
            self.window,
            "Adicionar Camada GIS",
            "",
            "Arquivos GIS (*.geojson *.json *.kml)",
        )
        if not path:
            return

        self.window.statusBar().showMessage(self.map_layer_use_cases.build_custom_layer_loading_message(path))
        try:
            presentation = self.map_layer_use_cases.load_custom_layer(
                path,
                geojson_loader=self._read_custom_layer_geojson,
            )
            self.run_map_js(presentation.command.script, presentation.command.context)
            QMessageBox.information(self.window, presentation.success_title, presentation.success_message)
            logger.info(f"Camada GIS carregada: {path}")
        except Exception as exc:
            logger.error(f"Erro ao carregar camada GIS: {exc}")
            QMessageBox.critical(self.window, "Erro", f"Nao foi possivel ler o arquivo GIS:\n{exc}")
        finally:
            self.window.statusBar().showMessage("Pronto")

    def on_map_loaded(self, ok):
        if ok:
            self.window._initial_map_sync_timer.start(500)

    def initial_map_sync(self):
        self.window._apply_theme_to_map()
        heatmap_points = self._current_heatmap_points()
        commands = self.map_rendering_use_cases.build_initial_sync_commands(
            theme="dark" if self.window.is_dark_mode else "light",
            geojson_data=self.window.gis.to_geojson_obj() if self.window.gis else None,
            current_layer=self.window.settings_controller.current_map_layer(),
            marker_coords=self.window.last_marker_coords,
            heatmap_points=heatmap_points if self.window.data_tab.chk_heatmap.isChecked() else None,
        )
        for command in commands:
            self.run_map_js(command.script, command.context)

    def load_microbacias_layer(self):
        if self.window.gis:
            command = self.map_rendering_use_cases.build_microbacias_command(self.window.gis.to_geojson_obj())
            self.run_map_js(command.script, command.context)

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
        command = self.map_rendering_use_cases.build_marker_command(lat, lon)
        self.run_map_js(command.script, command.context)
        self.update_address_search_enabled()

    def highlight_microbacia(self, name: str):
        command = self.map_rendering_use_cases.build_highlight_command(self.window.MICROB_NAME_FIELD, name)
        self.run_map_js(command.script, command.context)

    def set_map_status(self, message: str):
        command = self.map_rendering_use_cases.build_status_command(message)
        self.run_map_js(command.script, command.context)

    def search_on_map(self):
        addr = self.window.data_tab.in_end.text().strip()
        if not addr:
            QMessageBox.warning(self.window, "Atencao", "Digite um endereco para pesquisar.")
            return
        self.window.statusBar().showMessage(self.map_use_cases.build_geocoding_status(addr, purpose="main_search"))
        self.perform_geocode(addr)

    def search_on_map_plantio(self):
        plan = self.map_use_cases.build_plantio_search_plan(self._current_form_plantios())
        if not plan.choices:
            QMessageBox.warning(self.window, plan.empty_title, plan.empty_message)
            return

        if len(plan.choices) == 1:
            target_address = plan.choices[0].address
        else:
            labels = [choice.label for choice in plan.choices]
            selected, ok = QInputDialog.getItem(
                self.window,
                plan.chooser_title,
                plan.chooser_prompt,
                labels,
                0,
                False,
            )
            if not ok or not selected:
                return
            target_address = self.map_use_cases.resolve_choice(plan, selected)

        self.window.statusBar().showMessage(
            self.map_use_cases.build_geocoding_status(target_address, purpose="plantio_search")
        )
        self.perform_geocode(target_address)

    def perform_geocode(self, address: str):
        coords = geocode_address_arcgis(address)
        if coords:
            self.set_map_marker(coords[0], coords[1])
            if self.window.gis:
                micro = self.window.gis.find_microbacia(*coords)
            else:
                micro = ""
            presentation = self.map_use_cases.build_geocode_presentation(
                address=address,
                coords=coords,
                microbacia=str(micro or ""),
            )
            if presentation.microbacia:
                self.window.data_tab.in_micro.setCurrentText(presentation.microbacia)
                self.highlight_microbacia(presentation.microbacia)
            self.window.statusBar().showMessage(presentation.status_message)
            self.window._update_form_action_buttons()
            return

        presentation = self.map_use_cases.build_geocode_presentation(address=address, coords=None, microbacia="")
        QMessageBox.warning(self.window, presentation.warning_title, presentation.warning_message)
        self.window.statusBar().showMessage(presentation.status_message)

    def open_map_fullscreen(self):
        path = resource_path("app", "ui", "map_leaflet.html")
        dialog = MapFullScreenDialog(
            self.window,
            path,
            self.window.gis.to_geojson_obj() if self.window.gis else None,
            "dark" if self.window.is_dark_mode else "light",
            self.window.last_marker_coords,
            self.window.gis,
            self.window.settings_controller.current_map_layer(),
            self._current_heatmap_points(),
        )
        dialog.exec()

    def open_table_fullscreen(self):
        splitter = self.window.data_tab.splitter
        left_panel = self.window.data_tab.left_panel
        target_index = splitter.indexOf(left_panel)
        previous_sizes = splitter.sizes()

        def restore_panel(widget):
            splitter.insertWidget(target_index if target_index >= 0 else 0, widget)
            QTimer.singleShot(0, lambda: splitter.setSizes(previous_sizes))

        dialog = TableFullScreenDialog(self.window, left_panel, restore_panel)
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

        self._bind_runtime_persistence_service()
        workbook_path = self._current_session_path()
        preparation = self.persistence.prepare_base(
            workbook_path,
            fallback_records=self.window.records,
        )
        self._log_authoritative_write_issues("batch_geocode", preparation.issues)
        authoritative_records = list(preparation.base_records)
        projected_records = list(preparation.base_records)
        micro_finder = build_cached_microbacia_finder(self.window.gis.find_microbacia) if self.window.gis else None
        persistence_plan = self.batch_geocode_use_cases.apply_results(
            projected_records,
            results,
            micro_finder=micro_finder,
        )
        if not persistence_plan.updated_records:
            return 0

        write_result = self.persistence.execute_batch_geocode(
            authoritative_records=authoritative_records,
            projected_records=projected_records,
            updated_records=list(persistence_plan.updated_records),
        )
        self.persistence.publish_write_result(self.window, write_result)
        save_result = write_result.excel_result
        if isinstance(save_result, int):
            return save_result
        return persistence_plan.total_updated_records

    def _on_batch_geocode_progress(self, current: int, message: str):
        self.window.update_busy_operation(current, message)

    def _clear_geocode_worker(self):
        self.window.release_background_worker(BATCH_GEOCODE_JOB_NAME)
        self.window.geo_worker = None

    def cancel_batch_geocode(self):
        worker = self.window.geo_worker
        if worker is None:
            return
        self.window.statusBar().showMessage("Cancelando geocodificacao em lote...")
        if hasattr(worker, "stop"):
            worker.stop()

    def on_geocode_cancelled(self, message: str):
        resolved_message = self.batch_geocode_use_cases.build_cancelled_message(message)
        self._clear_geocode_worker()
        self.window.mark_job_cancelled(BATCH_GEOCODE_JOB_NAME, resolved_message)
        self.window.end_busy_operation(resolved_message)
        QMessageBox.information(
            self.window,
            "Concluido",
            resolved_message,
        )

    def run_batch_geocode(self):
        plan = self.batch_geocode_use_cases.build_batch_plan(
            self.window.records,
            needs_batch_geocode=self.record_needs_batch_geocode,
        )
        if not plan.pending_records:
            QMessageBox.information(self.window, "Sucesso", plan.empty_message)
            return
        if msg_confirm(self.window, plan.confirmation_title, plan.confirmation_message):
            self.window.start_background_job(self._build_batch_geocode_job_spec(list(plan.pending_records)))

    def _build_batch_geocode_job_spec(self, pending) -> BackgroundJobSpec:
        worker = self._create_geocode_worker(pending)
        worker.progress_update.connect(self._on_batch_geocode_progress)
        worker.finished_process.connect(self.on_geocode_finished)

        disconnect_callbacks = [
            build_disconnect_callback(worker.progress_update, self._on_batch_geocode_progress),
            build_disconnect_callback(worker.finished_process, self.on_geocode_finished),
        ]
        if hasattr(worker, "cancelled_process"):
            worker.cancelled_process.connect(self.on_geocode_cancelled)
            disconnect_callbacks.append(
                build_disconnect_callback(worker.cancelled_process, self.on_geocode_cancelled)
            )

        return BackgroundJobSpec(
            name=BATCH_GEOCODE_JOB_NAME,
            worker=worker,
            disconnect_callbacks=disconnect_callbacks,
            stop_callback=getattr(worker, "stop", None),
            wait_ms=10000,
            busy_message="Iniciando geocodificacao em lote...",
            total=len(pending),
            cancellable=True,
            cancel_callback=self.cancel_batch_geocode,
            on_tracked=self._track_geocode_worker,
        )

    def _track_geocode_worker(self, worker) -> None:
        self.window.geo_worker = worker

    def _create_geocode_worker(self, pending):
        factory = self.geocode_worker_factory or GeocodeWorker
        return factory(pending)

    def on_geocode_finished(self, results):
        self._clear_geocode_worker()
        self.window.end_busy_operation("Geoprocessamento concluido.")

        try:
            updated = self.persist_batch_geocode_results(results)
        except Exception as exc:
            root_exc = self.persistence.unwrap_write_exception(self.window, exc)
            self.window.mark_job_failed(
                BATCH_GEOCODE_JOB_NAME,
                self.batch_geocode_use_cases.build_failure_runtime_message(root_exc),
            )
            logger.error(f"Falha ao salvar geocodificacao em lote: {root_exc}", exc_info=True)
            QMessageBox.critical(self.window, "Erro", f"Falha ao salvar coordenadas do GPS em lote: {root_exc}")
            return

        presentation = self.batch_geocode_use_cases.build_completion_presentation(
            results or {},
            updated_count=updated,
        )
        self.window.mark_job_completed(BATCH_GEOCODE_JOB_NAME, presentation.runtime_message)
        QMessageBox.information(self.window, presentation.dialog_title, presentation.dialog_message)
        if presentation.should_reload:
            self.window.reload()

    def toggle_heatmap(self):
        command = self.map_rendering_use_cases.build_heatmap_command(
            self._current_heatmap_points(),
            context="update-heatmap" if self.window.data_tab.chk_heatmap.isChecked() else "clear-heatmap",
        )
        self.run_map_js(command.script, command.context)

    def _current_heatmap_points(self) -> list[list[float]]:
        records = (
            self.window.shell_controller.visible_records()
            if hasattr(self.window, "shell_controller")
            else list(self.window.filtered_records)
        )
        return self.map_rendering_use_cases.build_heatmap_points(
            records,
            self.window.data_tab.combo_heatmap_type.currentText(),
            enabled=self.window.data_tab.chk_heatmap.isChecked(),
        )

    @staticmethod
    def _read_custom_layer_geojson(path: str) -> dict:
        import fiona
        import geopandas as gpd

        fiona.drvsupport.supported_drivers["KML"] = "rw"
        gdf = gpd.read_file(path)
        if gdf.crs and gdf.crs.to_epsg() != 4326:
            gdf = gdf.to_crs(epsg=4326)
        return json.loads(gdf.to_json())
