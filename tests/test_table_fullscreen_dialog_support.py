import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QStandardItemModel
from PySide6.QtWidgets import QApplication, QComboBox, QTableView, QWidget

from app.application.use_cases.table_fullscreen_filters import TableFullscreenFiltersUseCases
from app.application.use_cases.table_fullscreen_layout import TableFullscreenLayoutUseCases
from app.ui.components.table_fullscreen_dialog_support import (
    apply_fullscreen_filter_state_to_dialog,
    apply_fullscreen_filter_state_to_main,
    apply_fullscreen_preferred_widths,
    blocked_qt_signals,
    build_fullscreen_filter_state_from_dialog,
    build_fullscreen_filter_state_from_main,
    build_fullscreen_header_widths,
    capture_fullscreen_table_layout,
    combo_items,
    resolve_fullscreen_primary_table,
    resolve_fullscreen_visible_columns,
    restore_fullscreen_table_layout,
)
from app.ui.components.widgets import CheckableComboBox


def get_app():
    return QApplication.instance() or QApplication([])


def _make_window_and_dialog():
    get_app()
    filter_use_cases = TableFullscreenFiltersUseCases()

    window = SimpleNamespace()
    window.search = SimpleNamespace(text=lambda: "Gregorio", setText=lambda value: setattr(window, "_search", value))
    window.data_tab = SimpleNamespace(
        filter_status=QComboBox(),
        filter_year=QComboBox(),
        filter_micro=CheckableComboBox("Todas"),
        filter_eletronico=CheckableComboBox("Todos"),
    )
    window.data_tab.filter_status.addItems(["Todos", "Pendentes"])
    window.data_tab.filter_status.setCurrentText("Pendentes")
    window.data_tab.filter_year.addItems(["Todos", "2026"])
    window.data_tab.filter_year.setCurrentText("2026")
    window.data_tab.filter_micro.set_items(["Gregorio", "Medeiros"])
    window.data_tab.filter_micro.set_checked_items(["Gregorio"], all_selected=False)
    window.data_tab.filter_eletronico.set_items(["Eletrônico", "Físico"])
    window.data_tab.filter_eletronico.set_checked_items(["Eletrônico"], all_selected=False)

    dialog = SimpleNamespace(
        search_fs=SimpleNamespace(text=lambda: "Medeiros", setText=lambda value: setattr(dialog, "_search", value)),
        filter_status_fs=QComboBox(),
        filter_year_fs=QComboBox(),
        filter_micro_fs=CheckableComboBox("Todas"),
        filter_eletronico_fs=CheckableComboBox("Todos"),
    )
    dialog.filter_status_fs.addItems(["Todos", "Pendentes"])
    dialog.filter_status_fs.setCurrentText("Todos")
    dialog.filter_year_fs.addItems(["Todos", "2025", "2026"])
    dialog.filter_year_fs.setCurrentText("Todos")
    dialog.filter_micro_fs.set_items(["Gregorio", "Medeiros"])
    dialog.filter_micro_fs.set_checked_items(["Medeiros"], all_selected=False)
    dialog.filter_eletronico_fs.set_items(["Eletrônico", "Físico"])
    dialog.filter_eletronico_fs.set_checked_items(["Físico"], all_selected=False)

    return window, dialog, filter_use_cases


def test_table_fullscreen_dialog_support_roundtrips_filter_state():
    window, dialog, filter_use_cases = _make_window_and_dialog()

    main_state = build_fullscreen_filter_state_from_main(window, filter_use_cases)
    dialog_state = build_fullscreen_filter_state_from_dialog(dialog, filter_use_cases)
    apply_fullscreen_filter_state_to_dialog(dialog, main_state)
    apply_fullscreen_filter_state_to_main(window, dialog_state)

    assert combo_items(dialog.filter_status_fs) == ["Todos", "Pendentes"]
    assert dialog.filter_status_fs.currentText() == "Pendentes"
    assert dialog.filter_micro_fs.checked_items() == ["Gregorio"]
    assert getattr(window, "_search", "") == "Medeiros"
    assert window.data_tab.filter_year.currentText() == "Todos"
    assert window.data_tab.filter_eletronico.checked_items() == ["Físico"]


def test_table_fullscreen_dialog_support_handles_table_layout():
    get_app()
    container = QWidget()
    main_table = QTableView(container)
    secondary_table = QTableView(container)
    main_table.setModel(QStandardItemModel(2, 6))
    secondary_table.setModel(QStandardItemModel(2, 2))
    main_table.show()
    secondary_table.show()
    main_table.resize(1200, 600)
    main_table.setColumnHidden(1, True)

    layout_use_cases = TableFullscreenLayoutUseCases()
    primary = resolve_fullscreen_primary_table(container)
    snapshot = capture_fullscreen_table_layout(primary, layout_use_cases.capture_header_layout)
    visible_columns = resolve_fullscreen_visible_columns(primary, layout_use_cases.visible_columns)
    header_widths = build_fullscreen_header_widths(primary, visible_columns)

    apply_fullscreen_preferred_widths(primary, {0: 180, 2: 240})
    restore_fullscreen_table_layout(primary, snapshot)

    assert primary is main_table
    assert 1 not in visible_columns
    assert 0 in header_widths


def test_table_fullscreen_dialog_support_blocks_and_restores_signals():
    class Dummy:
        def __init__(self):
            self.calls = []

        def blockSignals(self, flag):
            self.calls.append(flag)

    a = Dummy()
    b = Dummy()

    with blocked_qt_signals(a, b):
        pass

    assert a.calls == [True, False]
    assert b.calls == [True, False]
