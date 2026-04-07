from copy import deepcopy
from contextlib import contextmanager
from typing import Dict, Iterable, Optional, cast

from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QMessageBox

from app.application.use_cases.authoritative_persistence import AuthoritativePersistenceUseCases
from app.models.compensacao import Compensacao
from app.services.audit_service import serialize_record
from app.services.error_service import friendly_error_message
from app.services.plantio_service import (
    clone_plantios,
    deserialize_plantios_state,
    serialize_plantios_state,
    summarize_plantios,
    validate_record_plantios,
)
from app.services.records_service import display_tipo_value
from app.ui.components.dialogs import PlantiosDialog
from app.ui.components.ui_utils import msg_confirm
from app.ui.controllers.form_controller_support import (
    FormStateSnapshot,
    build_dirty_state_view,
    build_duplicate_highlight_stylesheet,
    build_form_action_state,
    build_form_record,
    build_form_state_snapshot,
    build_prefill_form_state,
    resolve_before_record_for_audit,
    same_record_identity,
)
from app.utils.logger import get_logger


logger = get_logger("UI.Form")


class FormController:
    _MISSING_PLANTIO_ERROR = "Preencha Endereço Plantio para salvar um registro compensado."
    _LOCKED_COMPENSADO_ERROR = "Limpe Endereço Plantio antes de desmarcar Compensado."
    _STALE_SELECTION_ERROR = "Não foi possível localizar o registro atual. Recarregue a planilha e tente novamente."
    _DIRTY_GROUP_TITLE = "Cadastro / Edição *"
    _CLEAN_GROUP_TITLE = "Cadastro / Edição"

    def __init__(self, window):
        self.window = window
        session_runtime = getattr(window, "session_runtime", None)
        self.persistence = getattr(window, "authoritative_persistence", None) or AuthoritativePersistenceUseCases(
            session_runtime,
            window.audit_service,
            getattr(window, "persistence_service", None),
        )
        self.record_use_cases = self.persistence.record_mutations
        self.local_mutation_sync = self.persistence.local_mutation_sync
        self.local_record_queries = self.persistence.local_record_queries
        self.local_write_authority = self.persistence.local_write_authority
        self.authoritative_write = self.persistence.authoritative_write
        self._history = []
        self._history_index = -1
        self._tracking_suspended = 0
        self._clean_state: Optional[Dict[str, object]] = None

    def _current_session_path(self) -> str:
        if hasattr(self.window, "shell_controller"):
            return self.window.shell_controller.current_session_path()
        runtime = getattr(self.window, "session_runtime", None)
        if runtime is None:
            return ""
        return str(getattr(runtime, "session_path", getattr(runtime, "path", "")) or "").strip()

    def _bind_runtime_persistence_service(self) -> None:
        self.persistence.bind_runtime_window(self.window)

    def _sync_local_mutation(self, *, operation: str, records) -> None:
        self._bind_runtime_persistence_service()
        status = self.local_mutation_sync.sync_projected_records(
            workbook_path=self._current_session_path(),
            records=records,
            operation=operation,
        )
        self._store_local_mutation_status(status)

    def _store_local_mutation_status(self, status) -> None:
        self.persistence.store_local_mutation_status(self.window, status)

    def _store_authoritative_write_status(self, status) -> None:
        self.persistence.store_authoritative_write_status(self.window, status)

    def _log_authoritative_write_issues(self, operation: str, issues) -> None:
        self.persistence.log_preparation_issues(operation, issues)

    def _append_audit_event(
        self,
        *,
        action: str,
        summary: str,
        backup_path: str = "",
        before_record: Optional[Compensacao] = None,
        after_record: Optional[Compensacao] = None,
        metadata: Optional[Dict[str, object]] = None,
    ) -> None:
        self.persistence._append_audit_event_safely(
            action=action,
            summary=summary,
            backup_path=backup_path,
            metadata=dict(metadata or {}),
            before=serialize_record(before_record) if before_record else None,
            after=serialize_record(after_record) if after_record else None,
        )

    @contextmanager
    def suspend_tracking(self):
        self._tracking_suspended += 1
        try:
            yield
        finally:
            self._tracking_suspended = max(0, self._tracking_suspended - 1)

    def setup_form_state_ui(self):
        self.window.data_tab.form_group.setTitle(self._CLEAN_GROUP_TITLE)
        self.window.form_state_label.setText("Sem alterações")
        self.window.setWindowModified(False)
        self.reset_history()
        self.window._refresh_window_chrome()

    def _checked_eletronico_value(self) -> str:
        checked = self.window.data_tab.eletronico_group.checkedButton()
        return display_tipo_value(checked.text() if checked else "")

    def _set_form_plantios(self, plantios, *, block_signals: bool = False):
        self.window.form_plantios = clone_plantios(plantios)
        summary = summarize_plantios(self.window.form_plantios)
        if block_signals:
            self.window.data_tab.in_end_plantio.blockSignals(True)
        self.window.data_tab.in_end_plantio.setText(summary)
        if block_signals:
            self.window.data_tab.in_end_plantio.blockSignals(False)

    def capture_form_state(self) -> Dict[str, object]:
        return build_form_state_snapshot(
            oficio_processo=self.window.data_tab.in_oficio.text(),
            caixa=self.window.data_tab.in_caixa.text(),
            av_tec=self.window.data_tab.in_avtec.text(),
            compensacao=self.window.data_tab.in_comp.text(),
            endereco=self.window.data_tab.in_end.text(),
            endereco_plantio=self.window.data_tab.in_end_plantio.text(),
            plantios=serialize_plantios_state(self.window.form_plantios),
            microbacia=self.window.data_tab.in_micro.currentText(),
            compensado=self.window.data_tab.chk_compensado.isChecked(),
            sn=self.window.data_tab.chk_sn.isChecked(),
            arquivado=self.window.data_tab.chk_arquivado.isChecked(),
            eletronico=self._checked_eletronico_value(),
        ).to_dict()

    def _apply_state_to_form(self, state: Dict[str, object]):
        snapshot = FormStateSnapshot.from_mapping(state)
        with self.suspend_tracking():
            self.window.data_tab.in_oficio.blockSignals(True)
            self.window.data_tab.in_caixa.blockSignals(True)
            self.window.data_tab.in_avtec.blockSignals(True)
            self.window.data_tab.in_comp.blockSignals(True)
            self.window.data_tab.in_end.blockSignals(True)
            self.window.data_tab.in_end_plantio.blockSignals(True)
            self.window.data_tab.in_micro.blockSignals(True)
            self.window.data_tab.chk_sn.blockSignals(True)
            self.window.data_tab.chk_arquivado.blockSignals(True)
            self.window.data_tab.chk_compensado.blockSignals(True)

            is_sn = snapshot.sn
            oficio = snapshot.oficio_processo
            self.window.data_tab.chk_sn.setChecked(is_sn)
            self.window.data_tab.in_oficio.setEnabled(not is_sn)
            self.window.data_tab.in_oficio.setText(oficio)

            is_arquivado = snapshot.arquivado
            caixa = snapshot.caixa
            self.window.data_tab.chk_arquivado.setChecked(is_arquivado)
            self.window.data_tab.in_caixa.setText(caixa)

            self.window.data_tab.in_avtec.setText(snapshot.av_tec)
            self.window.data_tab.in_comp.setText(snapshot.compensacao)
            self.window.data_tab.in_end.setText(snapshot.endereco)

            serialized_plantios = cast(Iterable[tuple[int, str, str, str, str]], snapshot.plantios)
            plantios_state = deserialize_plantios_state(serialized_plantios)
            self._set_form_plantios(plantios_state, block_signals=False)
            if not self.window.form_plantios:
                self.window.data_tab.in_end_plantio.setText(snapshot.endereco_plantio)

            self.window.data_tab.in_micro.setCurrentText(snapshot.microbacia)

            is_compensado = snapshot.compensado
            self.window.data_tab.chk_compensado.setChecked(is_compensado)
            self.window.data_tab.in_end_plantio.setEnabled(is_compensado)
            self.window.data_tab.btn_manage_plantios.setEnabled(is_compensado)

            target_eletronico = display_tipo_value(snapshot.eletronico)
            self.window.data_tab.eletronico_group.setExclusive(False)
            for btn in self.window.data_tab.eletronico_group.buttons():
                btn.setChecked(btn.text() == target_eletronico)
            self.window.data_tab.eletronico_group.setExclusive(True)

            self.window.data_tab.in_oficio.blockSignals(False)
            self.window.data_tab.in_caixa.blockSignals(False)
            self.window.data_tab.in_avtec.blockSignals(False)
            self.window.data_tab.in_comp.blockSignals(False)
            self.window.data_tab.in_end.blockSignals(False)
            self.window.data_tab.in_end_plantio.blockSignals(False)
            self.window.data_tab.in_micro.blockSignals(False)
            self.window.data_tab.chk_sn.blockSignals(False)
            self.window.data_tab.chk_arquivado.blockSignals(False)
            self.window.data_tab.chk_compensado.blockSignals(False)

        self.window._update_address_search_enabled()
        self.window.shell_controller.refresh_tipo_controls()
        self.window._update_form_action_buttons()
        self._refresh_dirty_state()

    def reset_history(self):
        state = self.capture_form_state()
        self._history = [state]
        self._history_index = 0
        self._clean_state = dict(state)
        self._refresh_dirty_state()
        self.update_form_action_buttons()

    def remember_current_state(self):
        if self._tracking_suspended:
            return
        state = self.capture_form_state()
        if self._history and state == self._history[self._history_index]:
            self._refresh_dirty_state()
            return

        self._history = self._history[: self._history_index + 1]
        self._history.append(state)
        self._history_index = len(self._history) - 1
        if len(self._history) > 100:
            overflow = len(self._history) - 100
            self._history = self._history[overflow:]
            self._history_index = len(self._history) - 1
        self._refresh_dirty_state()

    def can_undo(self) -> bool:
        return self._history_index > 0

    def can_redo(self) -> bool:
        return self._history_index + 1 < len(self._history)

    def undo(self):
        if not self.can_undo():
            return
        self._history_index -= 1
        self._apply_state_to_form(self._history[self._history_index])

    def redo(self):
        if not self.can_redo():
            return
        self._history_index += 1
        self._apply_state_to_form(self._history[self._history_index])

    def has_pending_changes(self) -> bool:
        if self._clean_state is None:
            return False
        return self.capture_form_state() != self._clean_state

    def _refresh_dirty_state(self):
        state_view = build_dirty_state_view(
            is_dirty=self.has_pending_changes(),
            dirty_group_title=self._DIRTY_GROUP_TITLE,
            clean_group_title=self._CLEAN_GROUP_TITLE,
        )
        self.window.data_tab.form_group.setTitle(state_view.group_title)
        self.window.form_state_label.setText(state_view.status_label)
        self.window.setWindowModified(state_view.window_modified)
        self.window._refresh_window_chrome()

    def confirm_discard_changes(self, action_text: str) -> bool:
        if not self.has_pending_changes():
            return True
        return msg_confirm(
                self.window,
            "Alterações pendentes",
            f"Existem alterações não salvas. Deseja descartá-las para {action_text}?",
        )

    def validate_as_you_type(self):
        av_tec = self.window.data_tab.in_avtec.text().strip()
        uid = self.window.selected.uid if self.window.selected else ""
        dup = self.check_duplicate_av_tec(av_tec, uid)

        if dup:
            self.window.data_tab.in_avtec.setStyleSheet(self._duplicate_av_tec_stylesheet())
            self.window.data_tab.in_avtec.setToolTip(f"Esta Av. Técnica já existe na linha {dup - 1}.")
        else:
            self.window.data_tab.in_avtec.setStyleSheet("")
            self.window.data_tab.in_avtec.setToolTip("")

    def _duplicate_av_tec_stylesheet(self) -> str:
        palette = self.window.data_tab.in_avtec.palette()
        return build_duplicate_highlight_stylesheet(
            background_color=palette.color(QPalette.ColorRole.Base).name(),
            text_color=palette.color(QPalette.ColorRole.Text).name(),
        )

    def update_form_action_buttons(self):
        workbook_path = (
            self.window.shell_controller.current_session_path()
            if hasattr(self.window, "shell_controller")
            else self._current_session_path()
        )
        has_session = bool(workbook_path)
        has_selected = self.window.selected is not None
        is_dirty = self.has_pending_changes()
        plantio_error = validate_record_plantios(self.read_form()) if has_selected else ""
        action_state = build_form_action_state(
            has_session=has_session,
            has_selected=has_selected,
            is_dirty=is_dirty,
            plantio_error=plantio_error,
        )
        self.window.data_tab.btn_add.setEnabled(action_state.enable_add)
        self.window.data_tab.btn_save_edit.setEnabled(action_state.enable_save)
        self.window.data_tab.btn_delete.setEnabled(action_state.enable_delete)
        self.window.data_tab.btn_ficha_pdf.setEnabled(action_state.enable_ficha)

    def on_compensado_toggled(self, checked: bool):
        if not checked and self.window.form_plantios:
            with self.suspend_tracking():
                self.window.data_tab.chk_compensado.blockSignals(True)
                self.window.data_tab.chk_compensado.setChecked(True)
                self.window.data_tab.chk_compensado.blockSignals(False)
            self.window.data_tab.in_end_plantio.setEnabled(True)
            self.window.data_tab.btn_manage_plantios.setEnabled(True)
            self.window.data_tab.in_end_plantio.setFocus()
            QMessageBox.warning(self.window, "Aviso", self._LOCKED_COMPENSADO_ERROR)
            self.update_form_action_buttons()
            self.window._update_address_search_enabled()
            return

        self.window.data_tab.in_end_plantio.setEnabled(checked)
        self.window.data_tab.btn_manage_plantios.setEnabled(checked)
        self.remember_current_state()
        self.update_form_action_buttons()
        self.window._update_address_search_enabled()

    def open_plantios_dialog(self):
        if not self.window.data_tab.chk_compensado.isChecked():
            return

        dialog = PlantiosDialog(
            self.window,
            self.window.form_plantios,
            self.window.data_tab.in_comp.text().strip(),
        )
        if dialog.exec():
            self._set_form_plantios(dialog.plantios, block_signals=True)
            self.remember_current_state()
            self.update_form_action_buttons()
            self.window._update_address_search_enabled()

    def fill_form(self, record: Compensacao):
        self._apply_state_to_form(build_prefill_form_state(record).to_dict())
        self.reset_history()

    def check_duplicate_av_tec(self, av_tec: str, current_uid: str) -> Optional[int]:
        self._bind_runtime_persistence_service()
        duplicate_result = self.persistence.resolve_duplicate_av_tec(
            self._current_session_path(),
            fallback_records=self.window.records,
            av_tec=av_tec,
            current_uid=current_uid,
        )
        return duplicate_result.duplicate_row

    def _resolve_authoritative_selected_record(self) -> Optional[Compensacao]:
        selected = self.window.selected
        if selected is None:
            return None

        fallback_records = list(self.window.records)
        if not fallback_records:
            fallback_records = [selected]
        elif not any(
            str(getattr(record, "uid", "") or "").strip() == str(getattr(selected, "uid", "") or "").strip()
            or int(getattr(record, "excel_row", 0) or 0) == int(getattr(selected, "excel_row", 0) or 0)
            for record in fallback_records
        ):
            fallback_records.append(selected)

        self._bind_runtime_persistence_service()
        result = self.persistence.resolve_selected_record(
            self._current_session_path(),
            fallback_records=fallback_records,
            uid=str(getattr(selected, "uid", "") or ""),
            excel_row=int(getattr(selected, "excel_row", 0) or 0),
        )
        if result.issues:
            logger.warning(
                "Selecao atual consultada com fallback/local issues: %s",
                " | ".join(result.issues),
            )
        return result.record

    def _resolve_authoritative_runtime_records(self) -> list[Compensacao]:
        fallback_records = list(self.window.records)
        selected = self.window.selected
        if selected is not None and not any(
            str(getattr(record, "uid", "") or "").strip() == str(getattr(selected, "uid", "") or "").strip()
            or int(getattr(record, "excel_row", 0) or 0) == int(getattr(selected, "excel_row", 0) or 0)
            for record in fallback_records
        ):
            fallback_records.append(selected)

        self._bind_runtime_persistence_service()
        result = self.persistence.resolve_authoritative_record_source(
            self._current_session_path(),
            fallback_records=fallback_records,
        )
        if result.issues:
            logger.warning(
                "Base autoritativa de mutacao consultada com fallback/local issues: %s",
                " | ".join(result.issues),
            )
        return list(result.records)

    @staticmethod
    def _next_excel_row(records: Iterable[Compensacao]) -> int:
        return AuthoritativePersistenceUseCases._next_excel_row(list(records))

    @staticmethod
    def _generate_unique_uid(used_uids: set[str]) -> str:
        return AuthoritativePersistenceUseCases._generate_unique_uid(used_uids)

    def _assign_provisional_add_identity(
        self,
        record: Compensacao,
        *,
        existing_records: Iterable[Compensacao],
    ) -> None:
        self.persistence.assign_provisional_add_identity(
            record,
            existing_records=list(existing_records),
        )

    @staticmethod
    def _same_record_identity(left: Compensacao | None, right: Compensacao | None) -> bool:
        return same_record_identity(left, right)

    def _resolve_before_record_for_audit(
        self,
        authoritative_record: Compensacao | None,
        selected_record: Compensacao | None,
    ) -> Compensacao | None:
        return resolve_before_record_for_audit(authoritative_record, selected_record)

    def read_form(self) -> Compensacao:
        return build_form_record(
            selected_record=self.window.selected,
            oficio_processo=self.window.data_tab.in_oficio.text(),
            caixa=self.window.data_tab.in_caixa.text(),
            av_tec=self.window.data_tab.in_avtec.text(),
            compensacao=self.window.data_tab.in_comp.text(),
            endereco=self.window.data_tab.in_end.text(),
            endereco_plantio=self.window.data_tab.in_end_plantio.text(),
            microbacia=self.window.data_tab.in_micro.currentText(),
            compensado_checked=self.window.data_tab.chk_compensado.isChecked(),
            eletronico_value=self._checked_eletronico_value(),
            plantios=clone_plantios(self.window.form_plantios),
        )

    def add_new(self):
        if not (
            self.window.shell_controller.current_session_path()
            if hasattr(self.window, "shell_controller")
            else self._current_session_path()
        ):
            return
        try:
            self._bind_runtime_persistence_service()
            record = self.read_form()
            preparation = self.persistence.prepare_create(
                self._current_session_path(),
                fallback_records=self.window.records,
                draft_record=record,
            )
            self._log_authoritative_write_issues("cadastro", preparation.issues)
            authoritative_records = list(preparation.base_records)
            validation = self.record_use_cases.validate_for_create(record, authoritative_records)
            if validation.error_message:
                QMessageBox.warning(self.window, "Erro", validation.error_message)
                return
            duplicate = preparation.duplicate_row
            if duplicate and not msg_confirm(
                self.window,
                "Duplicado",
            f"A Av. Tec. '{record.av_tec}' já existe na linha {duplicate - 1}. Cadastrar mesmo assim?",
            ):
                return
            write_result = self.persistence.execute_add(
                record,
                authoritative_records=authoritative_records,
            )
            self.persistence.publish_write_result(self.window, write_result)
            self.window.data_controller.refresh_runtime_after_mutation(list(write_result.records))
            QMessageBox.information(self.window, "Sucesso", "Adicionado com sucesso.")
        except Exception as exc:
            root_exc = self.persistence.unwrap_write_exception(self.window, exc)
            title, message = friendly_error_message(root_exc, "adicionar o registro")
            QMessageBox.critical(self.window, title, message)

    def save_edit(self):
        workbook_path = (
            self.window.shell_controller.current_session_path()
            if hasattr(self.window, "shell_controller")
            else self._current_session_path()
        )
        if not workbook_path or not self.window.selected:
            return
        try:
            self._bind_runtime_persistence_service()
            self._save_edit_impl()
        except Exception as exc:
            root_exc = self.persistence.unwrap_write_exception(self.window, exc)
            title, message = friendly_error_message(root_exc, "salvar o registro")
            QMessageBox.critical(self.window, title, message)

    def _save_edit_impl(self):
        draft_record = self.read_form()
        preparation = self.persistence.prepare_update(
            self._current_session_path(),
            fallback_records=self.window.records,
            fallback_selected=self.window.selected,
            draft_record=draft_record,
        )
        self._log_authoritative_write_issues("edicao", preparation.issues)
        authoritative_selected = preparation.selected_record
        if authoritative_selected is None:
            QMessageBox.warning(self.window, "Erro", self._STALE_SELECTION_ERROR)
            return
        before_record = self._resolve_before_record_for_audit(authoritative_selected, self.window.selected)
        record = preparation.effective_record or draft_record
        authoritative_records = list(preparation.base_records)
        plantio_error = validate_record_plantios(record)
        if plantio_error:
            QMessageBox.warning(self.window, "Erro", plantio_error)
            return
        validation = self.record_use_cases.validate_for_update(record, authoritative_records)
        if validation.error_message:
            QMessageBox.warning(self.window, "Erro", validation.error_message)
            return
        duplicate = preparation.duplicate_row
        if duplicate and not msg_confirm(
            self.window,
            "Duplicado",
            f"A Av. Tec. '{record.av_tec}' já existe na linha {duplicate - 1}. Salvar mesmo assim?",
        ):
            return
        write_result = self.persistence.execute_edit(
            record,
            authoritative_records=authoritative_records,
            before_record=before_record,
        )
        self.persistence.publish_write_result(self.window, write_result)
        refresh_result = self.window.data_controller.refresh_runtime_after_mutation(list(write_result.records))
        if refresh_result is False:
            return
        QMessageBox.information(self.window, "Sucesso", "Salvo com sucesso.")

    def delete_selected(self):
        if self.window.selected and msg_confirm(self.window, "Excluir", "Deseja excluir este registro?"):
            try:
                self._bind_runtime_persistence_service()
                preparation = self.persistence.prepare_delete(
                    self._current_session_path(),
                    fallback_records=self.window.records,
                    fallback_selected=self.window.selected,
                )
                self._log_authoritative_write_issues("exclusao", preparation.issues)
                authoritative_selected = preparation.selected_record
                if authoritative_selected is None:
                    QMessageBox.warning(self.window, "Erro", self._STALE_SELECTION_ERROR)
                    return
                authoritative_records = list(preparation.base_records)
                deleted_record = deepcopy(authoritative_selected)
                write_result = self.persistence.execute_delete(
                    deleted_record,
                    authoritative_records=authoritative_records,
                )
            except Exception as exc:
                root_exc = self.persistence.unwrap_write_exception(self.window, exc)
                title, message = friendly_error_message(root_exc, "excluir o registro")
                QMessageBox.critical(self.window, title, message)
                return
            self.persistence.publish_write_result(self.window, write_result)
            self.window.data_controller.refresh_runtime_after_mutation(list(write_result.records))
            self.window.statusBar().showMessage("Registro excluído")

    def clear_form(self, force: bool = False):
        if not force and not self.confirm_discard_changes("limpar o formulário"):
            return False

        self.window.selected = None
        with self.suspend_tracking():
            for widget in [
                self.window.data_tab.in_oficio,
                self.window.data_tab.in_avtec,
                self.window.data_tab.in_comp,
                self.window.data_tab.in_end,
                self.window.data_tab.in_caixa,
            ]:
                widget.clear()
            self._set_form_plantios([], block_signals=True)
            self.window.data_tab.in_micro.setCurrentIndex(-1)
            self.window.data_tab.in_micro.setEditText("")
            self.window.data_tab.eletronico_group.setExclusive(False)
            for btn in self.window.data_tab.eletronico_group.buttons():
                btn.setChecked(btn.text() == "Nulo")
            self.window.data_tab.eletronico_group.setExclusive(True)
            self.window.data_tab.chk_compensado.setChecked(False)
            self.window.data_tab.chk_sn.setChecked(False)
            self.window.data_tab.chk_arquivado.setChecked(False)
            self.window.data_tab.in_oficio.setEnabled(True)
            self.window.data_tab.in_end_plantio.setEnabled(False)
            self.window.data_tab.btn_manage_plantios.setEnabled(False)
            self.window.data_tab.in_avtec.setStyleSheet("")
            self.window.data_tab.in_avtec.setToolTip("")
            self.window.data_tab.table.clearSelection()
            self.window.last_marker_coords = None
            self.window.data_tab.btn_street_view.setEnabled(False)

        self.window.shell_controller.refresh_tipo_controls()
        self.window._update_address_search_enabled()
        self.update_form_action_buttons()
        self.window.statusBar().showMessage("Novo registro")
        self.reset_history()
        return True
