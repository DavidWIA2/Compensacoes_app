# --- TEMAS VISUAIS ---
THEME_LIGHT = {
    "bg_main": "#f5f6f8",
    "bg_panel": "#ffffff",
    "text": "#1f2328",
    "muted": "#5b6472",
    "input_bg": "#ffffff",
    "input_border": "#c9cfd8",
    "input_text": "#111827",
    "placeholder": "#8a94a6",
    "btn_primary": "#2176ff",
    "btn_primary_hover": "#1b64db",
    "btn_primary_pressed": "#1553b7",
    "btn_text": "#ffffff",
    "btn_danger": "#d32f2f",
    "btn_danger_hover": "#b62828",
    "btn_danger_pressed": "#941f1f",
    "btn_success": "#2e7d32",
    "btn_success_hover": "#256528",
    "btn_success_pressed": "#1d5120",
    "btn_secondary_bg": "#f8fafc",
    "btn_secondary_hover": "#eef4ff",
    "btn_secondary_pressed": "#dbeafe",
    "btn_disabled_bg": "#eef1f5",
    "table_header": "#e9edf3",
    "table_alt": "#f7f9fc",
    "table_sel_bg": "#dbeafe",
    "table_sel_fg": "#111827",
    "tab_sel": "#ffffff",
    "tab_unsel": "#e9edf3",
    "kpi_bg": "#ffffff",
    "kpi_border": "#d8dee9",
    "splitter_handle": "#c9cfd8",
    "shadow": "rgba(0,0,0,0.06)",
}

THEME_DARK = {
    "bg_main": "#1f2126",
    "bg_panel": "#2a2d34",
    "text": "#e9e9ea",
    "muted": "#b0b6c2",
    "input_bg": "#343844",
    "input_border": "#5a5f6e",
    "input_text": "#f2f2f2",
    "placeholder": "#a7afbf",
    "btn_primary": "#2d8cff",
    "btn_primary_hover": "#2373d6",
    "btn_primary_pressed": "#1c5cac",
    "btn_text": "#ffffff",
    "btn_danger": "#e04b4b",
    "btn_danger_hover": "#c43d3d",
    "btn_danger_pressed": "#a43333",
    "btn_success": "#35a55a",
    "btn_success_hover": "#2b8a4b",
    "btn_success_pressed": "#226f3c",
    "btn_secondary_bg": "#343844",
    "btn_secondary_hover": "#3b4150",
    "btn_secondary_pressed": "#334155",
    "btn_disabled_bg": "#262a32",
    "table_header": "#3a3f4c",
    "table_alt": "#2f3340",
    "table_sel_bg": "#334155",
    "table_sel_fg": "#f8fafc",
    "tab_sel": "#2a2d34",
    "tab_unsel": "#1f2126",
    "kpi_bg": "#2a2d34",
    "kpi_border": "#3a3f4c",
    "splitter_handle": "#5a5f6e",
    "shadow": "rgba(0,0,0,0.35)",
}

COLS = [
    "Ofício/ Processo", "Eletrônico", "Caixa", "Av. Tec.",
    "Compensação", "Endereço", "Microbacia", "Compensado",
    "Endereço do Plantio"
]

def get_app_qss(t: dict, sf: float = 1.0) -> str:
    """Gera o código CSS (QSS) completo, escalado e com suporte total a temas."""
    font_size = int(12 * sf)
    padding_v = max(3, int(5 * sf))
    padding_h = max(6, int(10 * sf))
    radius = int(8 * sf)
    min_h_input = int(24 * sf)
    min_h_btn = int(30 * sf)
    
    return f"""
        /* ===== Base ===== */
        QWidget {{
            color: {t['text']};
        }}

        QMainWindow, QDialog {{
            background-color: {t['bg_main']};
            color: {t['text']};
            font-family: 'Segoe UI', Arial;
            font-size: {font_size}px;
        }}

        QLabel {{ color: {t['text']}; }}
        QCheckBox, QRadioButton {{ color: {t['text']}; background: transparent; }}

        QGroupBox {{
            font-weight: 800;
            border: 1px solid {t['input_border']};
            border-radius: {radius}px;
            margin-top: {int(10*sf)}px;
            padding-top: {int(12*sf)}px;
            background-color: {t['bg_panel']};
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: {int(10*sf)}px;
            padding: 0 {int(6*sf)}px;
            color: {t['text']};
        }}
        QGroupBox#formGroup {{
            margin-top: {int(16*sf)}px;
            padding-top: {int(18*sf)}px;
        }}
        QGroupBox#formGroup::title {{
            left: {int(12*sf)}px;
            padding: 0 {int(8*sf)}px;
        }}
        QGroupBox#formGroup QLineEdit,
        QGroupBox#formGroup QComboBox {{
            min-height: {max(int(24*sf), 24)}px;
            max-height: {max(int(24*sf), 24)}px;
            padding: {max(int(2*sf), 2)}px {padding_h}px;
        }}

        QTabWidget::pane {{
            border: 1px solid {t['input_border']};
            background-color: {t['bg_panel']};
            border-radius: {radius}px;
        }}
        QTabBar::tab {{
            background-color: {t['tab_unsel']};
            color: {t['text']};
            padding: {int(7*sf)}px {int(16*sf)}px;
            border-top-left-radius: {int(8*sf)}px;
            border-top-right-radius: {int(8*sf)}px;
            margin-right: {int(4*sf)}px;
        }}
        QTabBar::tab:selected {{
            background-color: {t['tab_sel']};
            font-weight: 800;
            border-bottom: {int(3*sf)}px solid {t['btn_primary']};
        }}

        QLineEdit, QComboBox {{
            background-color: {t['input_bg']};
            border: 1px solid {t['input_border']};
            border-radius: {radius}px;
            padding: {padding_v}px {padding_h}px;
            color: {t['input_text']};
            min-height: {min_h_input}px;
        }}
        QLineEdit::placeholder {{ color: {t['placeholder']}; }}
        
        QComboBox QAbstractItemView {{
            background-color: {t['input_bg']};
            color: {t['input_text']};
            selection-background-color: {t['btn_primary']};
            border: 1px solid {t['input_border']};
        }}

        QPushButton {{
            background-color: {t['btn_secondary_bg']};
            border: 1px solid {t['input_border']};
            border-radius: {radius}px;
            padding: {padding_v}px {padding_h}px;
            color: {t['text']};
            font-weight: 700;
            min-height: {min_h_btn}px;
        }}
        QPushButton:hover:!disabled {{
            border: 1px solid {t['btn_primary']};
            background-color: {t['btn_secondary_hover']};
        }}
        QPushButton:pressed:!disabled {{
            border: 1px solid {t['btn_primary']};
            background-color: {t['btn_secondary_pressed']};
        }}

        QPushButton[kind="primary"] {{
            background-color: {t['btn_primary']};
            color: {t['btn_text']};
            border: 1px solid {t['btn_primary']};
            font-weight: 900;
        }}
        QPushButton[kind="primary"]:hover:!disabled {{ background-color: {t['btn_primary_hover']}; }}
        QPushButton[kind="primary"]:pressed:!disabled {{ background-color: {t['btn_primary_pressed']}; }}

        QPushButton[kind="success"] {{
            background-color: {t['btn_success']};
            color: #ffffff;
            border: 1px solid {t['btn_success']};
            font-weight: 900;
        }}
        QPushButton[kind="success"]:hover:!disabled {{
            background-color: {t['btn_success_hover']};
            border: 1px solid {t['btn_success_hover']};
        }}
        QPushButton[kind="success"]:pressed:!disabled {{
            background-color: {t['btn_success_pressed']};
            border: 1px solid {t['btn_success_pressed']};
        }}

        QPushButton[kind="danger"] {{
            background-color: {t['btn_danger']};
            color: #ffffff;
            border: 1px solid {t['btn_danger']};
            font-weight: 900;
        }}
        QPushButton[kind="danger"]:hover:!disabled {{
            background-color: {t['btn_danger_hover']};
            border: 1px solid {t['btn_danger_hover']};
        }}
        QPushButton[kind="danger"]:pressed:!disabled {{
            background-color: {t['btn_danger_pressed']};
            border: 1px solid {t['btn_danger_pressed']};
        }}

        QPushButton[kind="secondary"] {{
            background-color: {t['btn_secondary_bg']};
            color: {t['text']};
            border: 1px solid {t['input_border']};
            font-weight: 700;
        }}
        QPushButton[kind="secondary"]:hover:!disabled {{
            background-color: {t['btn_secondary_hover']};
            border: 1px solid {t['btn_primary']};
        }}
        QPushButton[kind="secondary"]:pressed:!disabled {{
            background-color: {t['btn_secondary_pressed']};
            border: 1px solid {t['btn_primary']};
        }}

        QPushButton:disabled,
        QPushButton[kind="primary"]:disabled,
        QPushButton[kind="secondary"]:disabled,
        QPushButton[kind="success"]:disabled,
        QPushButton[kind="danger"]:disabled {{
            background-color: {t['btn_disabled_bg']};
            color: {t['placeholder']};
            border: 1px solid {t['input_border']};
        }}

        QTableView {{
            background-color: {t['input_bg']};
            alternate-background-color: {t['table_alt']};
            gridline-color: {t['input_border']};
            color: {t['text']};
            selection-background-color: {t['table_sel_bg']};
            selection-color: {t['table_sel_fg']};
            border-radius: {radius}px;
            border: 1px solid {t['input_border']};
        }}
        QHeaderView::section {{
            background-color: {t['table_header']};
            color: {t['text']};
            padding: {int(5*sf)}px;
            border: 1px solid {t['input_border']};
            font-weight: 800;
        }}

        QSplitter::handle {{ background: {t['splitter_handle']}; }}
        QMenu {{ background-color: {t['bg_panel']}; color: {t['text']}; border: 1px solid {t['input_border']}; }}
        QMenu::item:selected {{ background-color: {t['table_sel_bg']}; color: {t['table_sel_fg']}; }}
    """
