from app.application.use_cases.import_preview_presenter import ImportPreviewRowView
from app.ui.components.import_preview_dialog_support import (
    build_import_preview_button_plan,
    build_import_preview_row_values,
    resolve_import_preview_current_key,
    resolve_import_preview_target_index,
)


def test_import_preview_button_plan_blocks_import_when_there_are_invalid_rows():
    blocked = build_import_preview_button_plan(total_invalid=1)
    allowed = build_import_preview_button_plan(total_invalid=0)

    assert blocked.allows_import is False
    assert allowed.allows_import is True
    assert allowed.accept_label == "Importar"


def test_import_preview_support_restores_selection_by_row_key():
    rows = (
        ImportPreviewRowView("2", "uid-1", "AT-1", "Novo", "Pronto"),
        ImportPreviewRowView("3", "uid-2", "AT-2", "UID existente", "Duplicado"),
    )

    current_key = resolve_import_preview_current_key(rows, current_row=1)
    values = build_import_preview_row_values(rows[0])
    target_index = resolve_import_preview_target_index(rows, current_key=current_key)

    assert current_key == rows[1].key()
    assert values == ("2", "uid-1", "AT-1", "Novo", "Pronto")
    assert target_index == 1
