from app.config import APP_WINDOW_TITLE
from app.ui.controllers.window_shell_support import (
    COMPENSACOES_SEARCH_PLACEHOLDER,
    TCRA_SEARCH_PLACEHOLDER,
    build_window_chrome_snapshot,
)


def test_window_shell_support_builds_professional_window_chrome_snapshot():
    availability = type(
        "Availability",
        (),
        {
            "display_label": "Banco local",
            "detail_message": "Banco SQLite local disponível em Banco local.",
        },
    )()
    write_status = type(
        "WriteStatus",
        (),
        {
            "status": "sqlite_primary",
            "operation": "import",
            "finalized": True,
            "issues": (),
        },
    )()
    selected = type(
        "SelectedRecord",
        (),
        {
            "av_tec": "AT-1",
            "oficio_processo": "123/2026",
            "excel_row": 2,
        },
    )()

    snapshot = build_window_chrome_snapshot(
        APP_WINDOW_TITLE,
        session_path="session://banco-local",
        availability=availability,
        total_records=4,
        filtered_records=2,
        search_text="Gregorio",
        selected=selected,
        write_status=write_status,
    )

    assert snapshot.window_title.endswith("Banco local (2/4)")
    assert snapshot.file_label == "Banco: Banco local"
    assert "Banco SQLite local" in snapshot.file_tooltip
    assert snapshot.records_label == "Registros: 2 de 4"
    assert snapshot.records_tooltip == "Busca atual: Gregorio"
    assert snapshot.write_label == "Escrita: SQLite -> espelho"
    assert "Última mutação: import" in snapshot.write_tooltip
    assert "Identidade final reconciliada após gravação." in snapshot.write_tooltip
    assert snapshot.selection_label == "Selecionado: AT-1"
    assert snapshot.selection_tooltip == "Registro atualmente carregado no formulário."
    assert "ofício" in COMPENSACOES_SEARCH_PLACEHOLDER.lower()
    assert "órgão" in TCRA_SEARCH_PLACEHOLDER.lower()
