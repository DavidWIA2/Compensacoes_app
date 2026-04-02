import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QAbstractItemView

from app.models.plantio_item import PlantioItem
from app.ui.components.dialogs import PlantiosDialog


def get_app():
    return QApplication.instance() or QApplication([])


def test_plantios_dialog_exposes_explicit_row_editing():
    get_app()
    dialog = PlantiosDialog(
        None,
        [PlantioItem(sequence=1, endereco="Rua XV de Novembro, 100", qtd_mudas="8")],
        "8",
    )

    assert dialog.btn_edit_row.text() == "Editar Linha"
    assert dialog.table.editTriggers() == QAbstractItemView.NoEditTriggers

    dialog.close()


def test_plantios_dialog_edit_button_opens_row_editor_and_updates_values(monkeypatch):
    get_app()
    dialog = PlantiosDialog(
        None,
        [PlantioItem(sequence=1, endereco="Rua XV de Novembro, 100", qtd_mudas="8")],
        "8",
    )
    captured = {}

    class FakeRowEditor:
        def __init__(self, parent, endereco="", qtd_mudas=""):
            captured["initial"] = (endereco, qtd_mudas)

        def exec(self):
            return True

        def values(self):
            return "Rua Nova, 50", "12"

    monkeypatch.setattr(
        "app.ui.components.dialogs.PlantioRowEditorDialog",
        FakeRowEditor,
    )

    dialog.table.setCurrentCell(0, 1)
    dialog.edit_selected_row()

    assert captured["initial"] == ("Rua XV de Novembro, 100", "8")
    assert dialog.table.item(0, 0).text() == "Rua Nova, 50"
    assert dialog.table.item(0, 1).text() == "12"

    dialog.close()


def test_plantios_dialog_updates_total_and_validates_before_accept(monkeypatch):
    get_app()
    dialog = PlantiosDialog(
        None,
        [PlantioItem(sequence=1, endereco="Rua XV de Novembro, 100", qtd_mudas="8")],
        "8",
    )
    warnings = []

    monkeypatch.setattr(
        "app.ui.components.dialogs.QMessageBox.warning",
        lambda *args, **kwargs: warnings.append(args[2]),
    )

    dialog.table.item(0, 1).setText("12")
    assert dialog.lbl_total.text() == "Soma dos plantios: 12 mudas | Compensacao: 8"

    dialog._accept_with_validation()

    assert dialog.plantios[0].qtd_mudas == "12"
    assert warnings == []

    dialog.table.item(0, 1).setText("0")
    dialog._accept_with_validation()

    assert warnings[-1] == "A quantidade de mudas do Plantio 1 deve ser maior que zero."
    dialog.close()
