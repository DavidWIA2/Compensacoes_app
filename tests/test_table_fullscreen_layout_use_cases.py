from app.application.use_cases.table_fullscreen_layout import TableFullscreenLayoutUseCases


def test_build_width_plan_prioritizes_address_columns():
    use_cases = TableFullscreenLayoutUseCases()

    width_plan = use_cases.build_width_plan(
        visible_columns=list(range(9)),
        header_widths={
            0: 140,
            1: 90,
            2: 70,
            3: 95,
            4: 100,
            5: 140,
            6: 110,
            7: 110,
            8: 160,
        },
        available_width=1600,
        scale_factor=1.0,
        base_widths={0: 180, 1: 115, 2: 110, 3: 120, 4: 110, 5: 300, 6: 150, 7: 120, 8: 330},
        extra_weights={0: 0.9, 1: 0.3, 2: 0.25, 3: 0.35, 4: 0.25, 5: 1.8, 6: 0.5, 7: 0.3, 8: 2.1},
    )

    assert not width_plan.use_stretch_fallback
    assert width_plan.widths[5] > width_plan.widths[1]
    assert width_plan.widths[8] > width_plan.widths[4]
    assert width_plan.widths[8] > width_plan.widths[2]


def test_build_width_plan_uses_stretch_fallback_without_available_width():
    use_cases = TableFullscreenLayoutUseCases()

    width_plan = use_cases.build_width_plan(
        visible_columns=[0, 1],
        header_widths={0: 100, 1: 100},
        available_width=0,
    )

    assert width_plan.use_stretch_fallback
    assert width_plan.widths == {}


def test_capture_header_layout_preserves_resize_modes_and_sizes():
    use_cases = TableFullscreenLayoutUseCases()

    snapshot = use_cases.capture_header_layout(
        stretch_last_section=True,
        resize_modes=[0, 1, 2],
        section_sizes=[100, 200, 300],
    )

    assert snapshot.stretch_last_section is True
    assert snapshot.resize_modes == (0, 1, 2)
    assert snapshot.section_sizes == (100, 200, 300)
