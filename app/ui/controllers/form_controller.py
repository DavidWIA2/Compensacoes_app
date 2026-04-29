from copy import deepcopy
from contextlib import contextmanager
from typing import Dict, Iterable, Optional, cast

from PySide6.QtCore import QTimer
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QMessageBox, QLineEdit

from app.application.use_cases.authoritative_persistence import AuthoritativePersistenceUseCases
from app.application.use_cases.authoritative_persistence_write_support import (
    generate_unique_uid,
    next_excel_row,
)
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
from app.services.records_service import (
    TIPO_ELETRONICO,
    TIPO_NULO,
    TIPO_OFICIO,
    display_tipo_value,
    storage_tipo_value,
)
from app.ui.components.dialogs import CompensacaoBulkActionDialog, PlantiosDialog
from app.ui.components.timer_utils import schedule_owned_single_shot
from app.ui.components.ui_utils import msg_confirm
from app.ui.controllers.form_controller_support import (
    FormStateSnapshot,
    FormValidationPresentation,
    build_field_feedback_stylesheet,
    build_dirty_state_view,
    build_duplicate_highlight_stylesheet,
    build_form_action_state,
    build_form_record,
    build_form_state_snapshot,
    build_form_validation_presentation,
    build_prefill_form_state,
    normalize_caixa_value,
    normalize_microbacia_value,
    resolve_before_record_for_audit,
    same_record_identity,
)
from app.utils.logger import get_logger


logger = get_logger("UI.Form")


class FormController:
    FORM_DRAFT_AUTOSAVE_MS = 700
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
        self._pending_new_form_draft = self._load_saved_form_draft()
        self._last_draft_saved_payload: Optional[Dict[str, object]] = None
        self._autosave_timer = QTimer(window)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.timeout.connect(self._save_form_draft)

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
        self._reset_inline_feedback()
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

    def _reset_line_edit_display_position(self, line_edit: Optional[QLineEdit]) -> None:
        if line_edit is None:
            return
        line_edit.deselect()
        line_edit.setCursorPosition(0)

    def _reset_form_display_positions(self) -> None:
        self._reset_line_edit_display_position(self.window.data_tab.in_oficio)
        self._reset_line_edit_display_position(self.window.data_tab.in_caixa)
        self._reset_line_edit_display_position(self.window.data_tab.in_avtec)
        self._reset_line_edit_display_position(self.window.data_tab.in_comp)
        self._reset_line_edit_display_position(self.window.data_tab.in_end)
        self._reset_line_edit_display_position(self.window.data_tab.in_end_plantio)
        self._reset_line_edit_display_position(self.window.data_tab.in_micro.lineEdit())

    def _load_saved_form_draft(self) -> Optional[Dict[str, object]]:
        settings_controller = getattr(self.window, "settings_controller", None)
        draft_loader = getattr(settings_controller, "compensacoes_form_draft", None)
        if not callable(draft_loader):
            return None
        draft = draft_loader()
        return dict(draft) if draft else None

    def _clear_saved_form_draft(self) -> None:
        self._last_draft_saved_payload = None
        self._pending_new_form_draft = None
        self._autosave_timer.stop()
        settings_controller = getattr(self.window, "settings_controller", None)
        draft_clearer = getattr(settings_controller, "clear_compensacoes_form_draft", None)
        if callable(draft_clearer):
            draft_clearer()

    def clear_saved_form_draft(self) -> None:
        self._clear_saved_form_draft()
        self.window.statusBar().showMessage("Rascunho local removido")

    def _queue_form_autosave(self) -> None:
        self._autosave_timer.start(self.FORM_DRAFT_AUTOSAVE_MS)

    def queue_form_autosave(self) -> None:
        self._queue_form_autosave()

    def persist_form_draft_now(self) -> None:
        if self._autosave_timer.isActive():
            self._autosave_timer.stop()
        self._save_form_draft()

    def _save_form_draft(self) -> None:
        if self.window.selected is not None:
            return
        payload = self.capture_form_state()
        payload["uid"] = ""
        has_content = any(
            [
                str(payload.get("oficio_processo") or "").strip(),
                str(payload.get("caixa") or "").strip(),
                str(payload.get("av_tec") or "").strip(),
                str(payload.get("compensacao") or "").strip(),
                str(payload.get("endereco") or "").strip(),
                str(payload.get("endereco_plantio") or "").strip(),
                str(payload.get("microbacia") or "").strip(),
                payload.get("plantios"),
                bool(payload.get("compensado")),
                bool(payload.get("sn")),
                bool(payload.get("arquivado")),
                str(payload.get("eletronico") or "").strip() not in {"", TIPO_NULO},
            ]
        )
        if not has_content or not self.has_pending_changes():
            self._clear_saved_form_draft()
            return
        if payload == self._last_draft_saved_payload:
            return
        settings_controller = getattr(self.window, "settings_controller", None)
        draft_setter = getattr(settings_controller, "set_compensacoes_form_draft", None)
        if not callable(draft_setter):
            return
        draft_setter(payload)
        self._pending_new_form_draft = dict(payload)
        self._last_draft_saved_payload = dict(payload)
        self.window.form_state_label.setText("Rascunho automático salvo")

    def _restore_new_form_draft_if_available(self) -> bool:
        draft = dict(self._pending_new_form_draft or {})
        if draft.get("uid"):
            return False
        has_content = any(
            [
                str(draft.get("oficio_processo") or "").strip(),
                str(draft.get("caixa") or "").strip(),
                str(draft.get("av_tec") or "").strip(),
                str(draft.get("compensacao") or "").strip(),
                str(draft.get("endereco") or "").strip(),
                str(draft.get("endereco_plantio") or "").strip(),
                str(draft.get("microbacia") or "").strip(),
                draft.get("plantios"),
                bool(draft.get("compensado")),
                bool(draft.get("sn")),
                bool(draft.get("arquivado")),
                str(draft.get("eletronico") or "").strip() not in {"", TIPO_NULO},
            ]
        )
        if not has_content:
            return False
        self._apply_state_to_form(draft)
        self.update_form_action_buttons()
        self.validate_as_you_type()
        return True

    def restore_saved_new_record_draft(self) -> bool:
        if self.window.selected is not None:
            return False
        restored = self._restore_new_form_draft_if_available()
        if restored:
            self.window.statusBar().showMessage("Rascunho local restaurado")
        return restored

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

            self.window.shell_controller.select_form_microbacia(snapshot.microbacia)

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
        self._reset_form_display_positions()
        schedule_owned_single_shot(self.window.data_tab, 0, self._reset_form_display_positions)
        self._refresh_dirty_state()

    def reset_history(self):
        state = self.capture_form_state()
        self._history = [state]
        self._history_index = 0
        self._clean_state = dict(state)
        self._refresh_dirty_state()
        self.update_form_action_buttons()
        self.validate_as_you_type()

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
        self._queue_form_autosave()

    def _selected_table_rows(self) -> list[int]:
        selection_model = self.window.data_tab.table.selectionModel()
        if selection_model is None:
            return []
        selected_rows: set[int] = set()
        for index in selection_model.selectedRows():
            source_index = self.window.data_tab.proxy.mapToSource(index)
            if source_index.isValid():
                selected_rows.add(source_index.row())
        return sorted(selected_rows)

    def selected_table_records(self) -> list[Compensacao]:
        rows = self._selected_table_rows()
        return [self.window.filtered_records[row] for row in rows if 0 <= row < len(self.window.filtered_records)]

    def _bulk_action_target_summary(self, record: Compensacao) -> str:
        return str(record.oficio_processo or record.av_tec or record.uid or f"linha {record.excel_row}").strip()

    def _build_bulk_updated_record(self, record: Compensacao, values: Dict[str, object]) -> Compensacao:
        action = str(values.get("action", "") or "").strip()
        updated = deepcopy(record)
        if action == "tipo":
            target_tipo = display_tipo_value(values.get("tipo", ""))
            updated.eletronico = storage_tipo_value(target_tipo)
            if str(updated.caixa or "").strip().upper() != "ARQUIVADO":
                if target_tipo == TIPO_OFICIO:
                    updated.caixa = normalize_caixa_value("Ofícios")
                elif target_tipo == TIPO_ELETRONICO:
                    updated.caixa = normalize_caixa_value("Eletrônico")
                elif str(updated.caixa or "").strip().upper() in {
                    normalize_caixa_value("Ofícios"),
                    normalize_caixa_value("Eletrônico"),
                }:
                    updated.caixa = ""
        elif action == "microbacia":
            resolver = getattr(self.window.shell_controller, "resolve_microbacia_display_name", None)
            updated.microbacia = normalize_microbacia_value(values.get("microbacia", ""), resolver=resolver)
        elif action == "caixa":
            updated.caixa = normalize_caixa_value(values.get("caixa", ""))
        elif action == "compensado":
            updated.compensado = "SIM" if bool(values.get("checked")) else ""
        elif action == "arquivado":
            updated.caixa = normalize_caixa_value(updated.caixa, arquivado_checked=bool(values.get("checked")))
        return updated

    def apply_bulk_action(self) -> bool:
        selected_records = self.selected_table_records()
        if not selected_records:
            QMessageBox.warning(
                self.window,
                "Aviso",
                "Selecione ao menos um registro na tabela para aplicar uma ação em lote.",
            )
            return False
        if self.has_pending_changes() and not self.confirm_discard_changes("aplicar ações em lote"):
            return False

        microbacia_options = [
            self.window.data_tab.in_micro.itemText(index)
            for index in range(self.window.data_tab.in_micro.count())
            if self.window.data_tab.in_micro.itemText(index).strip()
        ]
        dialog = CompensacaoBulkActionDialog(
            self.window,
            selected_count=len(selected_records),
            microbacia_options=microbacia_options,
        )
        if not dialog.exec():
            return False

        values = dialog.values()
        action = str(values.get("action", "") or "").strip()
        if action in {"microbacia", "caixa"} and not str(values.get(action, "") or "").strip():
            QMessageBox.warning(self.window, "Aviso", "Preencha o valor da ação em lote antes de continuar.")
            return False

        workbook_path = (
            self.window.shell_controller.current_session_path()
            if hasattr(self.window, "shell_controller")
            else self._current_session_path()
        )
        if not workbook_path:
            return False

        updated_records = list(self.window.records)
        last_write_result = None
        try:
            self._bind_runtime_persistence_service()
            for selected_record in selected_records:
                draft_record = self._build_bulk_updated_record(selected_record, values)
                preparation = self.persistence.prepare_update(
                    workbook_path,
                    fallback_records=updated_records,
                    fallback_selected=selected_record,
                    draft_record=draft_record,
                )
                self._log_authoritative_write_issues("lote_edicao", preparation.issues)
                authoritative_selected = preparation.selected_record
                if authoritative_selected is None:
                    QMessageBox.warning(
                        self.window,
                        "Erro",
                        f"Não foi possível localizar {self._bulk_action_target_summary(selected_record)} para atualização em lote.",
                    )
                    return False
                before_record = resolve_before_record_for_audit(authoritative_selected, selected_record)
                effective_record = preparation.effective_record or draft_record
                plantio_error = validate_record_plantios(effective_record)
                if plantio_error:
                    QMessageBox.warning(
                        self.window,
                        "Aviso",
                        f"{self._bulk_action_target_summary(selected_record)}: {plantio_error}",
                    )
                    return False
                validation = self.record_use_cases.validate_for_update(
                    effective_record,
                    list(preparation.base_records),
                )
                if validation.error_message:
                    QMessageBox.warning(
                        self.window,
                        "Aviso",
                        f"{self._bulk_action_target_summary(selected_record)}: {validation.error_message}",
                    )
                    return False
                last_write_result = self.persistence.execute_edit(
                    effective_record,
                    authoritative_records=list(preparation.base_records),
                    before_record=before_record,
                )
                updated_records = list(last_write_result.records)
        except Exception as exc:
            root_exc = self.persistence.unwrap_write_exception(self.window, exc)
            title, message = friendly_error_message(root_exc, "aplicar a ação em lote")
            QMessageBox.critical(self.window, title, message)
            return False

        if last_write_result is None:
            return False
        self.persistence.publish_write_result(self.window, last_write_result)
        self._clear_saved_form_draft()
        self.window.data_controller.refresh_runtime_after_mutation(updated_records)
        QMessageBox.information(
            self.window,
            "Sucesso",
            f"Ação em lote aplicada em {len(selected_records)} registro(s).",
        )
        return True

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

    def _field_widgets(self) -> Dict[str, object]:
        return {
            "oficio_processo": self.window.data_tab.in_oficio,
            "caixa": self.window.data_tab.in_caixa,
            "av_tec": self.window.data_tab.in_avtec,
            "compensacao": self.window.data_tab.in_comp,
            "endereco": self.window.data_tab.in_end,
            "endereco_plantio": self.window.data_tab.in_end_plantio,
            "microbacia": self.window.data_tab.in_micro,
        }

    @staticmethod
    def _repolish_widget(widget) -> None:
        try:
            style = widget.style()
            if style is not None:
                style.unpolish(widget)
                style.polish(widget)
            widget.update()
        except RuntimeError:
            return

    @staticmethod
    def _base_tooltip_for_widget(widget) -> str:
        cached = widget.property("_base_tooltip")
        if cached is None:
            cached = widget.toolTip()
            widget.setProperty("_base_tooltip", cached)
        return str(cached or "").strip()

    def _set_widget_tooltip_feedback(self, widget, feedback_message: str = "") -> None:
        base_tooltip = self._base_tooltip_for_widget(widget)
        feedback_message = str(feedback_message or "").strip()
        if base_tooltip and feedback_message:
            widget.setToolTip(f"{base_tooltip}\n\n{feedback_message}")
        else:
            widget.setToolTip(feedback_message or base_tooltip)

    @staticmethod
    def _compact_toolbar_feedback_text(
        *,
        summary_text: str,
        geocode_text: str = "",
        detail_text: str = "",
        duplicate_text: str = "",
    ) -> str:
        parts = [str(summary_text or "").strip()]
        normalized_geocode = str(geocode_text or detail_text or "").strip()
        if normalized_geocode:
            if "geocod" in normalized_geocode.lower():
                parts.append("Geocodificação: revisar ponto principal")
            else:
                parts.append(normalized_geocode)
        normalized_duplicate = str(duplicate_text or "").strip()
        if normalized_duplicate:
            parts.append(normalized_duplicate)
        return " | ".join(part for part in parts if part)

    def _reset_inline_feedback(self) -> None:
        if hasattr(self.window.data_tab, "lbl_form_feedback"):
            self.window.data_tab.lbl_form_feedback.clear()
            self.window.data_tab.lbl_form_feedback.setToolTip("")
            self.window.data_tab.lbl_form_feedback.setProperty("role", "helper")
            self.window.data_tab.lbl_form_feedback.setVisible(False)
            self._repolish_widget(self.window.data_tab.lbl_form_feedback)
        if hasattr(self.window.data_tab, "lbl_form_geocode"):
            self.window.data_tab.lbl_form_geocode.clear()
            self.window.data_tab.lbl_form_geocode.setToolTip("")
            self.window.data_tab.lbl_form_geocode.setProperty("role", "status-note")
            self.window.data_tab.lbl_form_geocode.setVisible(False)
            self._repolish_widget(self.window.data_tab.lbl_form_geocode)

        seen_widgets = set()
        for widget in self._field_widgets().values():
            widget_id = id(widget)
            if widget_id in seen_widgets:
                continue
            seen_widgets.add(widget_id)
            widget.setStyleSheet("")
            self._set_widget_tooltip_feedback(widget, "")
            self._repolish_widget(widget)

    def _focus_field(self, field_name: str) -> None:
        widget = self._field_widgets().get(str(field_name or "").strip())
        if widget is None:
            return
        line_edit = widget.lineEdit() if hasattr(widget, "lineEdit") and callable(widget.lineEdit) else None
        if line_edit is not None:
            line_edit.setFocus()
            line_edit.selectAll()
            return
        if hasattr(widget, "setFocus"):
            widget.setFocus()
        if hasattr(widget, "selectAll"):
            widget.selectAll()

    def _apply_validation_feedback(self, presentation: FormValidationPresentation) -> None:
        self._reset_inline_feedback()

        severity = str(presentation.severity or "info").strip().lower()
        role = {
            "error": "feedback-error",
            "warning": "feedback-warning",
            "info": "feedback-info",
            "success": "feedback-success",
        }.get(severity, "helper")

        feedback_lines = [str(presentation.summary_text or "").strip()]
        detail_text = str(presentation.detail_text or "").strip()
        duplicate_text = str(presentation.duplicate_text or "").strip()
        if detail_text:
            feedback_lines.append(detail_text)
        if duplicate_text:
            feedback_lines.append(duplicate_text)
        feedback_lines = [line for line in feedback_lines if line]

        if hasattr(self.window.data_tab, "lbl_form_feedback") and feedback_lines:
            full_feedback_text = "\n".join(feedback_lines)
            compact_feedback_text = self._compact_toolbar_feedback_text(
                summary_text=str(presentation.summary_text or "").strip(),
                detail_text=detail_text,
                duplicate_text=duplicate_text,
                geocode_text=str(presentation.geocode_text or "").strip(),
            )
            self.window.data_tab.lbl_form_feedback.setText(compact_feedback_text)
            self.window.data_tab.lbl_form_feedback.setToolTip(full_feedback_text)
            self.window.data_tab.lbl_form_feedback.setProperty("role", role)
            self.window.data_tab.lbl_form_feedback.setVisible(True)
            self.window.data_tab.lbl_form_feedback.updateGeometry()
            self._repolish_widget(self.window.data_tab.lbl_form_feedback)

        geocode_text = str(presentation.geocode_text or "").strip()
        if hasattr(self.window.data_tab, "lbl_form_geocode") and geocode_text:
            compact_geocode_text = " ".join(geocode_text.split())
            self.window.data_tab.lbl_form_geocode.setText(compact_geocode_text)
            self.window.data_tab.lbl_form_geocode.setToolTip(geocode_text)
            self.window.data_tab.lbl_form_geocode.setVisible(False)
            self._repolish_widget(self.window.data_tab.lbl_form_geocode)

        for field_name, feedback in dict(presentation.field_feedback or {}).items():
            widget = self._field_widgets().get(field_name)
            if widget is None:
                continue
            palette = widget.palette()
            widget.setStyleSheet(
                build_field_feedback_stylesheet(
                    background_color=palette.color(QPalette.ColorRole.Base).name(),
                    text_color=palette.color(QPalette.ColorRole.Text).name(),
                    severity=feedback.severity,
                )
            )
            self._set_widget_tooltip_feedback(widget, feedback.message)
            self._repolish_widget(widget)

    def confirm_discard_changes(self, action_text: str) -> bool:
        if not self.has_pending_changes():
            return True
        return msg_confirm(
            self.window,
            "Alterações pendentes",
            f"Existem alterações não salvas. Deseja descartá-las para {action_text}?",
        )

    def validate_as_you_type(self):
        if self.window.selected is None:
            self._reset_inline_feedback()
            return

        record = self.read_form()
        uid = self.window.selected.uid
        duplicate_row = self.check_duplicate_av_tec(str(record.av_tec or "").strip(), uid)
        presentation = build_form_validation_presentation(
            record=record,
            duplicate_row=duplicate_row,
        )
        self._apply_validation_feedback(presentation)

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
        if hasattr(self.window.data_tab, "btn_open_cadastro_window"):
            self.window.data_tab.btn_open_cadastro_window.setEnabled(has_selected)
        if hasattr(self.window.data_tab, "refresh_cadastro_review"):
            self.window.data_tab.refresh_cadastro_review()

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
            self.validate_as_you_type()
            self.update_form_action_buttons()
            self.window._update_address_search_enabled()
            return

        self.window.data_tab.in_end_plantio.setEnabled(checked)
        self.window.data_tab.btn_manage_plantios.setEnabled(checked)
        self.remember_current_state()
        self.validate_as_you_type()
        self.update_form_action_buttons()
        self.window._update_address_search_enabled()
        if hasattr(self.window.data_tab, "refresh_cadastro_review"):
            self.window.data_tab.refresh_cadastro_review()

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
            self.validate_as_you_type()
            if hasattr(self.window.data_tab, "show_form_feedback"):
                self.window.data_tab.show_form_feedback("Plantios atualizados.", role="feedback-success")
            if hasattr(self.window.data_tab, "refresh_cadastro_review"):
                self.window.data_tab.refresh_cadastro_review()
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
        return next_excel_row(list(records))

    @staticmethod
    def _generate_unique_uid(used_uids: set[str]) -> str:
        return generate_unique_uid(used_uids)

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
            sn_checked=self.window.data_tab.chk_sn.isChecked(),
            arquivado_checked=self.window.data_tab.chk_arquivado.isChecked(),
            microbacia_resolver=getattr(
                getattr(self.window, "shell_controller", None),
                "resolve_microbacia_display_name",
                None,
            ),
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
                self.validate_as_you_type()
                presentation = build_form_validation_presentation(
                    record=record,
                    duplicate_row=preparation.duplicate_row,
                )
                if presentation.focus_field:
                    self._focus_field(presentation.focus_field)
                QMessageBox.warning(self.window, "Erro", validation.error_message)
                return
            duplicate = preparation.duplicate_row
            if duplicate and not msg_confirm(
                self.window,
                "Possível duplicidade",
                (
                    f"A Av. Tec. '{record.av_tec}' já aparece na linha {duplicate - 1}. "
                    "Revise o cadastro atual e continue apenas se realmente for um novo processo."
                ),
            ):
                self.validate_as_you_type()
                self._focus_field("av_tec")
                return
            write_result = self.persistence.execute_add(
                record,
                authoritative_records=authoritative_records,
            )
            self.persistence.publish_write_result(self.window, write_result)
            self._clear_saved_form_draft()
            self.window.data_controller.refresh_runtime_after_mutation(list(write_result.records))
            if hasattr(self.window.data_tab, "show_form_feedback"):
                self.window.data_tab.show_form_feedback("Cadastro adicionado com sucesso.", role="feedback-success")
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
            self.validate_as_you_type()
            self._focus_field("endereco_plantio")
            QMessageBox.warning(self.window, "Erro", plantio_error)
            return
        validation = self.record_use_cases.validate_for_update(record, authoritative_records)
        if validation.error_message:
            self.validate_as_you_type()
            presentation = build_form_validation_presentation(
                record=record,
                duplicate_row=preparation.duplicate_row,
            )
            if presentation.focus_field:
                self._focus_field(presentation.focus_field)
            QMessageBox.warning(self.window, "Erro", validation.error_message)
            return
        duplicate = preparation.duplicate_row
        if duplicate and not msg_confirm(
            self.window,
            "Possível duplicidade",
            (
                f"A Av. Tec. '{record.av_tec}' já aparece na linha {duplicate - 1}. "
                "Revise antes de salvar e continue só se a duplicidade for esperada."
            ),
        ):
            self.validate_as_you_type()
            self._focus_field("av_tec")
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
        if hasattr(self.window.data_tab, "show_form_feedback"):
            self.window.data_tab.show_form_feedback("Alterações salvas com sucesso.", role="feedback-success")
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
            if hasattr(self.window.data_tab, "show_form_feedback"):
                self.window.data_tab.show_form_feedback("Registro excluído.", role="feedback-success")
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
            self.window.data_tab.table.clearSelection()
            self.window.last_marker_coords = None
            self.window.data_tab.btn_street_view.setEnabled(False)

        if hasattr(self.window.data_tab, "update_record_summary"):
            self.window.data_tab.update_record_summary(None)
        if hasattr(self.window.data_tab, "refresh_cadastro_review"):
            self.window.data_tab.refresh_cadastro_review(None)
        self._reset_inline_feedback()
        self.window.shell_controller.refresh_tipo_controls()
        self.window._update_address_search_enabled()
        self.update_form_action_buttons()
        if hasattr(self.window.data_tab, "show_form_feedback"):
            self.window.data_tab.show_form_feedback("Formulário pronto para novo cadastro.", role="feedback-info")
        self.window.statusBar().showMessage("Novo registro")
        self.reset_history()
        return True
