import os
from contextlib import contextmanager
from typing import Dict, Optional

from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QMessageBox

from app.models.compensacao import Compensacao
from app.services.error_service import friendly_error_message
from app.services.plantio_service import (
    clone_plantios,
    deserialize_plantios_state,
    serialize_plantios_state,
    summarize_plantios,
    sync_legacy_plantio_fields,
    validate_record_plantios,
)
from app.services.records_service import safe_upper
from app.services.validation import validate_compensacao
from app.ui.components.dialogs import PlantiosDialog
from app.ui.components.ui_utils import msg_confirm


class FormController:
    _MISSING_PLANTIO_ERROR = "Preencha Endereco Plantio para salvar um registro compensado."
    _LOCKED_COMPENSADO_ERROR = "Limpe Endereco Plantio antes de desmarcar Compensado."
    _DIRTY_GROUP_TITLE = "Cadastro / Edição *"
    _CLEAN_GROUP_TITLE = "Cadastro / Edição"

    def __init__(self, window):
        self.window = window
        self._history = []
        self._history_index = -1
        self._tracking_suspended = 0
        self._clean_state: Optional[Dict[str, object]] = None

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
        return checked.text() if checked else ""

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
            self.window.data_tab.in_caixa.setEnabled(not is_arquivado)
            if is_arquivado:
                self.window.data_tab.in_caixa.setValidator(None)
            else:
                from PySide6.QtGui import QIntValidator

                self.window.data_tab.in_caixa.setValidator(QIntValidator(0, 999999))
            self.window.data_tab.in_caixa.setText(caixa)

            self.window.data_tab.in_avtec.setText(str(state.get("av_tec", "")))
            self.window.data_tab.in_comp.setText(str(state.get("compensacao", "")))
            self.window.data_tab.in_end.setText(str(state.get("endereco", "")))

            plantios_state = deserialize_plantios_state(state.get("plantios", ()))
            self._set_form_plantios(plantios_state, block_signals=False)
            if not self.window.form_plantios:
                self.window.data_tab.in_end_plantio.setText(str(state.get("endereco_plantio", "")))

            self.window.data_tab.in_micro.setCurrentText(str(state.get("microbacia", "")))

            is_compensado = bool(state.get("compensado"))
            self.window.data_tab.chk_compensado.setChecked(is_compensado)
            self.window.data_tab.in_end_plantio.setEnabled(is_compensado)
            self.window.data_tab.btn_manage_plantios.setEnabled(is_compensado)

            target_eletronico = safe_upper(str(state.get("eletronico", "")))
            self.window.data_tab.eletronico_group.setExclusive(False)
            for btn in self.window.data_tab.eletronico_group.buttons():
                btn.setChecked(safe_upper(btn.text()) == target_eletronico and bool(target_eletronico))
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
                "eletronico": record.eletronico,
            }
        )
        self.reset_history()

    def check_duplicate_av_tec(self, av_tec: str, current_uid: str) -> Optional[int]:
        if not av_tec:
            return None
        target = av_tec.strip().upper()
        for record in self.window.records:
            if record.uid != current_uid and record.av_tec.strip().upper() == target:
                actual = self.window.excel._find_row_by_uid(record.uid)
                return actual if actual else record.excel_row
        return None

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
            eletronico=self._checked_eletronico_value(),
            uid=self.window.selected.uid if self.window.selected else "",
            plantios=clone_plantios(self.window.form_plantios),
        )
        return sync_legacy_plantio_fields(record)

    def add_new(self):
        if not self.window.excel.path:
            return
        record = self.read_form()
        error = validate_compensacao(record)
        if error:
            QMessageBox.warning(self.window, "Erro", error)
            return
        duplicate = self.check_duplicate_av_tec(record.av_tec, "")
        if duplicate and not msg_confirm(
            self.window,
            "Duplicado",
            f"A Av. Tec. '{record.av_tec}' já existe na linha {duplicate - 1}. Cadastrar mesmo assim?",
        ):
            return
        self.window.excel.add_new(record)
        self.window.reload()
        self.clear_form(force=True)
        QMessageBox.information(self.window, "Sucesso", "Adicionado com sucesso.")

    def save_edit(self):
        if not self.window.excel.path or not self.window.selected:
            return
        record = self.read_form()
        plantio_error = validate_record_plantios(record)
        if plantio_error:
            QMessageBox.warning(self.window, "Erro", plantio_error)
            return
        error = validate_compensacao(record)
        if error:
            QMessageBox.warning(self.window, "Erro", error)
            return
        duplicate = self.check_duplicate_av_tec(record.av_tec, record.uid)
        if duplicate and not msg_confirm(
            self.window,
            "Duplicado",
            f"A Av. Tec. '{record.av_tec}' já existe na linha {duplicate - 1}. Salvar mesmo assim?",
        ):
            return
        self.window.excel.save_edit(record)
        try:
            reload_result = self.window.reload(confirm_discard=False)
        except TypeError:
            reload_result = self.window.reload()
        if reload_result is False:
            return
        QMessageBox.information(self.window, "Sucesso", "Salvo com sucesso.")

    def delete_selected(self):
        if self.window.selected and msg_confirm(self.window, "Excluir", "Deseja excluir este registro?"):
            try:
                self.window.excel.delete_record_shift_up(self.window.selected.excel_row, self.window.selected.uid)
            except Exception as exc:
                title, message = friendly_error_message(exc, "excluir o registro")
                QMessageBox.critical(self.window, title, message)
                return
            self.window.reload()
            self.clear_form(force=True)
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
                btn.setChecked(False)
            self.window.data_tab.eletronico_group.setExclusive(True)
            self.window.data_tab.chk_compensado.setChecked(False)
            self.window.data_tab.chk_sn.setChecked(False)
            self.window.data_tab.chk_arquivado.setChecked(False)
            self.window.data_tab.in_oficio.setEnabled(True)
            self.window.data_tab.in_caixa.setEnabled(True)
            self.window.data_tab.in_end_plantio.setEnabled(False)
            self.window.data_tab.btn_manage_plantios.setEnabled(False)
            self.window.data_tab.in_avtec.setStyleSheet("")
            self.window.data_tab.in_avtec.setToolTip("")
            self.window.data_tab.table.clearSelection()
            self.window.last_marker_coords = None
            self.window.data_tab.btn_street_view.setEnabled(False)

        self.window._update_address_search_enabled()
        self.update_form_action_buttons()
        self.window.statusBar().showMessage("Novo registro")
        self.reset_history()
        return True
