from app.application.use_cases.table_fullscreen_filters import TableFullscreenFiltersUseCases


def test_build_state_preserves_options_and_normalizes_selected_items():
    use_cases = TableFullscreenFiltersUseCases()

    state = use_cases.build_state(
        search_text="Gregorio",
        status_options=["Todos", "Pendentes"],
        status_current_text="Pendentes",
        year_options=["Todos", "2026"],
        year_current_text="2026",
        micro_items=["Gregorio", "Medeiros"],
        micro_checked_items=["gregorio", "desconhecida"],
        micro_all_selected=False,
        eletronico_items=["SIM", "NAO"],
        eletronico_checked_items=["SIM"],
        eletronico_all_selected=False,
        caixa_items=["Arquivado", "CX-3"],
        caixa_checked_items=["cx-3"],
        caixa_all_selected=False,
    )

    assert state.search_text == "Gregorio"
    assert state.status.options == ("Todos", "Pendentes")
    assert state.status.current_text == "Pendentes"
    assert state.micro.checked_items == ("Gregorio",)
    assert state.eletronico.items == ("Eletrônico", "Físico")
    assert state.eletronico.checked_items == ("Eletrônico",)
    assert state.caixa.checked_items == ("CX-3",)


def test_build_cleared_state_resets_search_and_selects_all():
    use_cases = TableFullscreenFiltersUseCases()
    state = use_cases.build_state(
        search_text="Medeiros",
        status_options=["Todos", "Pendentes"],
        status_current_text="Pendentes",
        year_options=["Todos", "2025"],
        year_current_text="2025",
        micro_items=["Gregorio", "Medeiros"],
        micro_checked_items=["Medeiros"],
        micro_all_selected=False,
        eletronico_items=["SIM", "NAO"],
        eletronico_checked_items=["NAO"],
        eletronico_all_selected=False,
        caixa_items=["Arquivado", "CX-3"],
        caixa_checked_items=["Arquivado"],
        caixa_all_selected=False,
    )

    cleared = use_cases.build_cleared_state(state)

    assert cleared.search_text == ""
    assert cleared.status.current_text == "Todos"
    assert cleared.year.current_text == "Todos"
    assert cleared.micro.all_selected is True
    assert cleared.micro.checked_items == ()
    assert cleared.eletronico.all_selected is True
    assert cleared.eletronico.checked_items == ()
    assert cleared.caixa.all_selected is True
    assert cleared.caixa.checked_items == ()
