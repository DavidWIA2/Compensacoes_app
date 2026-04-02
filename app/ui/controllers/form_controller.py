import os
from copy import deepcopy
from contextlib import contextmanager
from typing import Dict, Iterable, Optional, cast

from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QMessageBox

from app.application.use_cases.local_mutation_sync import LocalMutationSyncUseCases
from app.application.use_cases.local_record_queries import LocalRecordQueriesUseCases
from app.application.use_cases.local_write_authority import LocalWriteAuthorityUseCases
from app.application.use_cases.record_mutations import RecordMutationUseCases
from app.models.compensacao import Compensacao
from app.services.audit_service import serialize_record
from app.services.error_service import friendly_error_message
from app.services.plantio_service import (
    clone_plantios,
    deserialize_plantios_state,
    serialize_plantios_state,
    summarize_plantios,
    sync_legacy_plantio_fields,
    validate_record_plantios,
)
from app.services.records_service import display_tipo_value, safe_upper, storage_tipo_value
from app.ui.components.dialogs import PlantiosDialog
from app.ui.components.ui_utils import msg_confirm
from app.utils.logger import get_logger


logger = get_logger("UI.Form")


class FormController:
    _MISSING_PLANTIO_ERROR = "Preencha Endereco Plantio para salvar um registro compensado."
    _LOCKED_COMPENSADO_ERROR = "Limpe Endereco Plantio antes de desmarcar Compensado."
    _STALE_SELECTION_ERROR = "Nao foi possivel localizar o registro atual. Recarregue a planilha e tente novamente."
    _DIRTY_GROUP_TITLE = "Cadastro / Edição *"
    _CLEAN_GROUP_TITLE = "Cadastro / Edição"

    def __init__(self, window):
        self.window = window
        self.record_use_cases = RecordMutationUseCases(window.excel)
        self.local_mutation_sync = LocalMutationSyncUseCases(getattr(window, "persistence_service", None))
        self.local_record_queries = LocalRecordQueriesUseCases(getattr(window, "persistence_service", None))
        self.local_write_authority = LocalWriteAuthorityUseCases(self.local_record_queries)
        self._history = []
        self._history_index = -1
        self._tracking_suspended = 0
        self._clean_state: Optional[Dict[str, object]] = None

    def _sync_local_mutation(self, *, operation: str, records) -> None:
        status = self.local_mutation_sync.sync_projected_records(
            workbook_path=str(getattr(self.window.excel, "path", "") or ""),
            records=records,
            operation=operation,
        )
        self._store_local_mutation_status(status)

    def _store_local_mutation_status(self, status) -> None:
        self.window._local_mutation_sync_status = status
        if status.issues:
            logger.warning(
                "Falha ao sincronizar mutacao '%s' no espelho local: %s",
                getattr(status, "operation", "mutacao"),
                " | ".join(status.issues),
            )

    def _log_authoritative_write_issues(self, operation: str, issues) -> None:
        normalized_issues = tuple(str(issue or "").strip() for issue in issues or () if str(issue or "").strip())
        if not normalized_issues:
            return
        logger.warning(
            "Contexto autoritativo de escrita (%s) consultado com fallback/local issues: %s",
            operation,
            " | ".join(normalized_issues),
        )

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
        if not self.window.excel.path:
            return
        self.window.audit_service.append_event(
            workbook_path=self.window.excel.path,
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
        return {
            "oficio_processo": self.window.data_tab.in_oficio.text().strip(),
            "caixa": self.window.data_tab.in_caixa.text().strip(),
            "av_tec": self.window.data_tab.in_avtec.text().strip(),
            "compensacao": self.window.data_tab.in_comp.text().strip(),
            "endereco": self.window.data_tab.in_end.text().strip(),
            "endereco_plantio": self.window.data_tab.in_end_plantio.text().strip(),
            "plantios": serialize_plantios_state(self.window.form_plantios),
            "microbacia": self.window.data_tab.in_micro.currentText().strip(),
            "compensado": self.window.data_tab.chk_compensado.isChecked(),
            "sn": self.window.data_tab.chk_sn.isChecked(),
            "arquivado": self.window.data_tab.chk_arquivado.isChecked(),
            "eletronico": self._checked_eletronico_value(),
        }

    def _apply_state_to_form(self, state: Dict[str, object]):
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

            is_sn = bool(state.get("sn"))
            oficio = str(state.get("oficio_processo", ""))
            self.window.data_tab.chk_sn.setChecked(is_sn)
            self.window.data_tab.in_oficio.setEnabled(not is_sn)
            self.window.data_tab.in_oficio.setText(oficio)

            is_arquivado = bool(state.get("arquivado"))
            caixa = str(state.get("caixa", ""))
            self.window.data_tab.chk_arquivado.setChecked(is_arquivado)
            self.window.data_tab.in_caixa.setText(caixa)

            self.window.data_tab.in_avtec.setText(str(state.get("av_tec", "")))
            self.window.data_tab.in_comp.setText(str(state.get("compensacao", "")))
            self.window.data_tab.in_end.setText(str(state.get("endereco", "")))

            serialized_plantios = cast(
                Iterable[tuple[int, str, str, str, str]],
                state.get("plantios", ()),
            )
            plantios_state = deserialize_plantios_state(serialized_plantios)
            self._set_form_plantios(plantios_state, block_signals=False)
            if not self.window.form_plantios:
                self.window.data_tab.in_end_plantio.setText(str(state.get("endereco_plantio", "")))

            self.window.data_tab.in_micro.setCurrentText(str(state.get("microbacia", "")))

            is_compensado = bool(state.get("compensado"))
            self.window.data_tab.chk_compensado.setChecked(is_compensado)
            self.window.data_tab.in_end_plantio.setEnabled(is_compensado)
            self.window.data_tab.btn_manage_plantios.setEnabled(is_compensado)

            target_eletronico = display_tipo_value(str(state.get("eletronico", "")))
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
        is_dirty = self.has_pending_changes()
        self.window.data_tab.form_group.setTitle(self._DIRTY_GROUP_TITLE if is_dirty else self._CLEAN_GROUP_TITLE)
        self.window.form_state_label.setText("Alterações pendentes" if is_dirty else "Sem alterações")
        self.window.setWindowModified(is_dirty)
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
        background_color = palette.color(QPalette.ColorRole.Base).name()
        text_color = palette.color(QPalette.ColorRole.Text).name()
        return (
            "QLineEdit { "
            "border: 2px solid #e74c3c; "
            f"background-color: {background_color}; "
            f"color: {text_color}; "
            "}"
        )

    def update_form_action_buttons(self):
        has_excel = bool(self.window.excel.path and os.path.exists(self.window.excel.path))
        has_selected = self.window.selected is not None
        is_dirty = self.has_pending_changes()
        plantio_error = validate_record_plantios(self.read_form()) if has_selected else ""
        self.window.data_tab.btn_add.setEnabled(has_excel)
        self.window.data_tab.btn_save_edit.setEnabled(
            has_excel and has_selected and is_dirty and not plantio_error
        )
        self.window.data_tab.btn_delete.setEnabled(has_excel and has_selected)
        self.window.data_tab.btn_ficha_pdf.setEnabled(has_excel and has_selected)

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
        sync_legacy_plantio_fields(record)
        self._apply_state_to_form(
            {
                "oficio_processo": (record.oficio_processo or "").strip(),
                "caixa": (record.caixa or "").strip(),
                "av_tec": record.av_tec,
                "compensacao": str(record.compensacao or ""),
                "endereco": record.endereco,
                "endereco_plantio": record.endereco_plantio,
                "plantios": serialize_plantios_state(record.plantios),
                "microbacia": record.microbacia,
                "compensado": safe_upper(record.compensado) == "SIM",
                "sn": (record.oficio_processo or "").strip().upper() == "S/N",
                "arquivado": (record.caixa or "").strip().upper() == "ARQUIVADO",
                "eletronico": display_tipo_value(record.eletronico),
            }
        )
        self.reset_history()

    def check_duplicate_av_tec(self, av_tec: str, current_uid: str) -> Optional[int]:
        duplicate_result = self.local_record_queries.resolve_duplicate_av_tec(
            str(getattr(self.window.excel, "path", "") or ""),
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

        result = self.local_record_queries.resolve_selected_record(
            str(getattr(self.window.excel, "path", "") or ""),
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

        result = self.local_record_queries.resolve_authoritative_record_source(
            str(getattr(self.window.excel, "path", "") or ""),
            fallback_records=fallback_records,
        )
        if result.issues:
            logger.warning(
                "Base autoritativa de mutacao consultada com fallback/local issues: %s",
                " | ".join(result.issues),
            )
        return list(result.records)

    def read_form(self) -> Compensacao:
        record = Compensacao(
            excel_row=self.window.selected.excel_row if self.window.selected else -1,
            oficio_processo=self.window.data_tab.in_oficio.text().strip(),
            caixa=self.window.data_tab.in_caixa.text().strip(),
            av_tec=self.window.data_tab.in_avtec.text().strip(),
            compensacao=self.window.data_tab.in_comp.text().strip(),
            endereco=self.window.data_tab.in_end.text().strip(),
            endereco_plantio=self.window.data_tab.in_end_plantio.text().strip(),
            microbacia=self.window.data_tab.in_micro.currentText().strip(),
            compensado="SIM" if self.window.data_tab.chk_compensado.isChecked() else "",
            eletronico=storage_tipo_value(self._checked_eletronico_value()),
            uid=self.window.selected.uid if self.window.selected else "",
            plantios=clone_plantios(self.window.form_plantios),
        )
        return sync_legacy_plantio_fields(record)

    def add_new(self):
        if not self.window.excel.path:
            return
        try:
            self.window.excel.ensure_workbook_is_current()
            record = self.read_form()
            preparation = self.local_write_authority.prepare_create(
                str(getattr(self.window.excel, "path", "") or ""),
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
            backup_path = self.window.excel.create_operation_backup("add") or ""
            self.record_use_cases.add_new(record)
            self._append_audit_event(
                action="add",
                summary=f"Registro cadastrado: {record.av_tec or record.oficio_processo}",
                backup_path=backup_path,
                after_record=record,
            )
            mutation_result = self.local_mutation_sync.apply_after_add(
                workbook_path=str(getattr(self.window.excel, "path", "") or ""),
                existing_records=authoritative_records,
                added_record=record,
            )
            self._store_local_mutation_status(mutation_result.status)
            self.window.data_controller.refresh_runtime_after_mutation(list(mutation_result.records))
            QMessageBox.information(self.window, "Sucesso", "Adicionado com sucesso.")
        except Exception as exc:
            title, message = friendly_error_message(exc, "adicionar o registro")
            QMessageBox.critical(self.window, title, message)

    def save_edit(self):
        if not self.window.excel.path or not self.window.selected:
            return
        try:
            self.window.excel.ensure_workbook_is_current()
            self._save_edit_impl()
        except Exception as exc:
            title, message = friendly_error_message(exc, "salvar o registro")
            QMessageBox.critical(self.window, title, message)

    def _save_edit_impl(self):
        draft_record = self.read_form()
        preparation = self.local_write_authority.prepare_update(
            str(getattr(self.window.excel, "path", "") or ""),
            fallback_records=self.window.records,
            fallback_selected=self.window.selected,
            draft_record=draft_record,
        )
        self._log_authoritative_write_issues("edicao", preparation.issues)
        authoritative_selected = preparation.selected_record
        if authoritative_selected is None:
            QMessageBox.warning(self.window, "Erro", self._STALE_SELECTION_ERROR)
            return
        before_record = deepcopy(authoritative_selected)
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
        backup_path = self.window.excel.create_operation_backup("edit") or ""
        self.record_use_cases.save_edit(record)
        self._append_audit_event(
            action="edit",
            summary=f"Registro alterado: {record.av_tec or record.oficio_processo}",
            backup_path=backup_path,
            before_record=before_record,
            after_record=record,
        )
        mutation_result = self.local_mutation_sync.apply_after_edit(
            workbook_path=str(getattr(self.window.excel, "path", "") or ""),
            existing_records=authoritative_records,
            updated_record=record,
        )
        self._store_local_mutation_status(mutation_result.status)
        refresh_result = self.window.data_controller.refresh_runtime_after_mutation(list(mutation_result.records))
        if refresh_result is False:
            return
        QMessageBox.information(self.window, "Sucesso", "Salvo com sucesso.")

    def delete_selected(self):
        if self.window.selected and msg_confirm(self.window, "Excluir", "Deseja excluir este registro?"):
            try:
                self.window.excel.ensure_workbook_is_current()
                preparation = self.local_write_authority.prepare_delete(
                    str(getattr(self.window.excel, "path", "") or ""),
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
                backup_path = self.window.excel.create_operation_backup("delete") or ""
                self.record_use_cases.delete(authoritative_selected)
            except Exception as exc:
                title, message = friendly_error_message(exc, "excluir o registro")
                QMessageBox.critical(self.window, title, message)
                return
            self._append_audit_event(
                action="delete",
                summary=f"Registro excluido: {deleted_record.av_tec or deleted_record.oficio_processo}",
                backup_path=backup_path,
                before_record=deleted_record,
            )
            mutation_result = self.local_mutation_sync.apply_after_delete(
                workbook_path=str(getattr(self.window.excel, "path", "") or ""),
                existing_records=authoritative_records,
                deleted_record=deleted_record,
            )
            self._store_local_mutation_status(mutation_result.status)
            self.window.data_controller.refresh_runtime_after_mutation(list(mutation_result.records))
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
