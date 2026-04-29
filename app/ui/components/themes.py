from app.models.display_columns import DISPLAY_COLUMN_LABELS
from app.ui.components.ui_utils import resource_path


# --- TEMAS VISUAIS ---
THEME_LIGHT = {
    "bg_main": "#f5f6f8",
    "bg_panel": "#ffffff",
    "bg_subtle": "#f8fafc",
    "bg_toolbar": "#f7f9fc",
    "bg_sidebar": "#fbfcfe",
    "bg_hero": "#f3f7fd",
    "border_strong": "#bcc6d4",
    "text": "#1f2328",
    "muted": "#5b6472",
    "muted_soft": "#728094",
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
    "table_header": "#e3e8f0",
    "table_alt": "#f1f5fb",
    "table_grid": "#d9e0ea",
    "table_hover": "#eef4ff",
    "table_sel_bg": "#dbeafe",
    "table_sel_fg": "#111827",
    "tab_sel": "#ffffff",
    "tab_unsel": "#e9edf3",
    "kpi_bg": "#ffffff",
    "kpi_border": "#d8dee9",
    "splitter_handle": "#c9cfd8",
    "status_bg": "#f7f9fc",
    "status_border": "#d4dbe6",
    "status_accent_bg": "#eef4ff",
    "shadow": "rgba(0,0,0,0.06)",
}

THEME_DARK = {
    "bg_main": "#1f2126",
    "bg_panel": "#2a2d34",
    "bg_subtle": "#313640",
    "bg_toolbar": "#2b3038",
    "bg_sidebar": "#2d3139",
    "bg_hero": "#27303b",
    "border_strong": "#667085",
    "text": "#e9e9ea",
    "muted": "#b0b6c2",
    "muted_soft": "#98a2b3",
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
    "table_header": "#404654",
    "table_alt": "#333947",
    "table_grid": "#4b5362",
    "table_hover": "#394252",
    "table_sel_bg": "#334155",
    "table_sel_fg": "#f8fafc",
    "tab_sel": "#2a2d34",
    "tab_unsel": "#1f2126",
    "kpi_bg": "#2a2d34",
    "kpi_border": "#3a3f4c",
    "splitter_handle": "#5a5f6e",
    "status_bg": "#2d323b",
    "status_border": "#464d5a",
    "status_accent_bg": "#334155",
    "shadow": "rgba(0,0,0,0.35)",
}

COLS = DISPLAY_COLUMN_LABELS

def get_app_qss(t: dict, sf: float = 1.0) -> str:
    """Gera o código CSS (QSS) completo, escalado e com suporte total a temas."""
    font_size = int(12 * sf)
    padding_v = max(3, int(5 * sf))
    padding_h = max(6, int(10 * sf))
    radius = int(8 * sf)
    chip_radius = int(14 * sf)
    min_h_input = int(24 * sf)
    min_h_btn = int(30 * sf)
    
    # Caminhos para os SVGs usados pelos controles customizados.
    t_off = resource_path("assets", "toggle_off.svg").replace("\\", "/")
    t_on = resource_path("assets", "toggle_on.svg").replace("\\", "/")
    r_off = resource_path("assets", "radio_off.svg").replace("\\", "/")
    r_on = resource_path("assets", "radio_on.svg").replace("\\", "/")
    spin_up = resource_path("assets", "spin_up.svg").replace("\\", "/")
    spin_down = resource_path("assets", "spin_down.svg").replace("\\", "/")
    
    return f"""
        /* ===== Base ===== */
        QWidget {{
            color: {t['text']};
        }}

        QWidget#ShellToolbar,
        QFrame[panel="toolbar"],
        QFrame[panel="section"],
        QFrame[panel="sidebar"],
        QFrame[panel="hero"] {{
            background-color: {t['bg_panel']};
            border: 1px solid {t['input_border']};
            border-radius: {int(10 * sf)}px;
        }}

        QFrame[panel="toolbar"] {{
            background-color: {t['bg_toolbar']};
            border-color: {t['border_strong']};
        }}

        QFrame[panel="section"],
        QFrame[panel="sidebar"] {{
            border-color: {t['kpi_border']};
        }}

        QFrame[panel="sidebar"] {{
            background-color: {t['bg_sidebar']};
        }}

        QFrame[panel="hero"] {{
            background-color: {t['bg_hero']};
            border-color: {t['kpi_border']};
        }}

        QFrame[panel="glass"] {{
            background-color: {t['bg_panel']};
            border: 1px solid {t['kpi_border']};
            border-radius: {int(12 * sf)}px;
        }}

        QFrame[panel="micro"] {{
            background-color: {t['status_accent_bg']};
            border: 1px solid {t['status_border']};
            border-radius: {int(10 * sf)}px;
        }}

        QFrame[panel="subtle"] {{
            background-color: {t['bg_subtle']};
            border: 1px solid {t['input_border']};
            border-radius: {radius}px;
        }}

        QFrame[reviewState="ok"] {{
            border-left: {max(int(3 * sf), 3)}px solid {t['btn_success']};
            background-color: rgba(45, 138, 95, 0.10);
        }}

        QFrame[reviewState="warning"] {{
            border-left: {max(int(3 * sf), 3)}px solid #d97706;
            background-color: rgba(217, 119, 6, 0.11);
        }}

        QFrame[reviewState="neutral"] {{
            border-left: {max(int(3 * sf), 3)}px solid {t['status_border']};
        }}

        QMainWindow, QDialog {{
            background-color: {t['bg_main']};
            color: {t['text']};
            font-family: 'Segoe UI', Arial;
            font-size: {font_size}px;
        }}

        QStatusBar::item {{
            border: none;
        }}

        QMenuBar {{
            background-color: transparent;
            color: {t['text']};
            border: none;
            spacing: {max(int(6 * sf), 6)}px;
        }}
        QMenuBar::item {{
            padding: {max(int(5 * sf), 5)}px {max(int(10 * sf), 10)}px;
            border-radius: {int(7 * sf)}px;
            background: transparent;
        }}
        QMenuBar::item:selected {{
            background-color: {t['btn_secondary_hover']};
        }}
        QMenuBar::item:pressed {{
            background-color: {t['btn_secondary_pressed']};
        }}

        QStatusBar {{
            background-color: {t['bg_panel']};
            border-top: 1px solid {t['input_border']};
            padding: {max(int(2 * sf), 2)}px {max(int(4 * sf), 4)}px;
        }}

        QToolTip {{
            background-color: {t['bg_subtle']};
            color: {t['text']};
            border: 1px solid {t['input_border']};
            padding: {max(int(6 * sf), 6)}px {max(int(8 * sf), 8)}px;
            border-radius: {int(6 * sf)}px;
        }}
        
        /* ===== Toggle (CheckBox) ===== */
        QCheckBox {{ 
            color: {t['text']}; 
            spacing: {max(int(10 * sf), 10)}px;
            font-weight: 500;
        }}
        
        QCheckBox::indicator {{
            width: {max(int(40 * sf), 40)}px;
            height: {max(int(20 * sf), 20)}px;
            background: transparent;
            border: none;
        }}
        
        QCheckBox::indicator:unchecked {{
            image: url("{t_off}");
        }}
        
        QCheckBox::indicator:checked {{
            image: url("{t_on}");
        }}
        
        QCheckBox::indicator:hover {{
            opacity: 0.9;
        }}

        /* ===== Radio Button ===== */
        QRadioButton {{ 
            color: {t['text']}; 
            spacing: {max(int(8 * sf), 8)}px;
            font-weight: 500;
        }}
        
        QRadioButton::indicator {{
            width: {max(int(20 * sf), 20)}px;
            height: {max(int(20 * sf), 20)}px;
            background: transparent;
            border: none;
        }}
        
        QRadioButton::indicator:unchecked {{
            image: url("{r_off}");
        }}
        
        QRadioButton::indicator:checked {{
            image: url("{r_on}");
        }}
        
        QRadioButton::indicator:hover {{
            opacity: 0.9;
        }}

        /* Resto dos estilos */
        QGroupBox {{
            font-weight: 800;
            border: 1px solid {t['kpi_border']};
            border-radius: {radius}px;
            margin-top: {int(10*sf)}px;
            padding-top: {int(11*sf)}px;
            background-color: {t['bg_panel']};
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: {int(10*sf)}px;
            padding: 0 {int(6*sf)}px;
            color: {t['muted']};
            font-weight: 800;
        }}
        QGroupBox#formGroup {{
            margin-top: {int(10*sf)}px;
            padding-top: {int(10*sf)}px;
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
        QGroupBox#formGroup QPushButton {{
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
            padding: {int(5*sf)}px {int(13*sf)}px;
            border-top-left-radius: {int(8*sf)}px;
            border-top-right-radius: {int(8*sf)}px;
            margin-right: {int(4*sf)}px;
            min-height: {max(int(28 * sf), 28)}px;
        }}
        QTabBar::tab:hover {{
            background-color: {t['btn_secondary_hover']};
        }}
        QTabBar::tab:selected {{
            background-color: {t['tab_sel']};
            font-weight: 800;
            border-bottom: {int(3*sf)}px solid {t['btn_primary']};
        }}

        QLineEdit, QComboBox, QTextEdit, QPlainTextEdit, QAbstractSpinBox {{
            background-color: {t['input_bg']};
            border: 1px solid {t['input_border']};
            border-radius: {radius}px;
            padding: {padding_v}px {padding_h}px;
            color: {t['input_text']};
            min-height: {min_h_input}px;
        }}
        QLineEdit:focus, QComboBox:focus, QTextEdit:focus, QPlainTextEdit:focus, QAbstractSpinBox:focus {{
            border: 1px solid {t['btn_primary']};
            background-color: {t['bg_panel']};
        }}
        QTextEdit:read-only, QPlainTextEdit:read-only {{
            background-color: {t['bg_subtle']};
            border-color: {t['kpi_border']};
        }}
        QAbstractSpinBox QLineEdit {{
            background-color: transparent;
            border: none;
            padding: 0px;
            color: {t['input_text']};
            selection-background-color: {t['btn_primary']};
            selection-color: {t['btn_text']};
        }}
        QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{
            background-color: transparent;
            border: none;
            width: {max(int(22 * sf), 22)}px;
        }}
        QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {{
            background-color: {t['btn_secondary_hover']};
        }}
        QAbstractSpinBox::up-button:pressed, QAbstractSpinBox::down-button:pressed {{
            background-color: {t['btn_secondary_pressed']};
        }}
        QAbstractSpinBox::up-arrow, QAbstractSpinBox::down-arrow {{
            width: {max(int(10 * sf), 10)}px;
            height: {max(int(10 * sf), 10)}px;
        }}
        QAbstractSpinBox::up-arrow {{
            image: url("{spin_up}");
        }}
        QAbstractSpinBox::down-arrow {{
            image: url("{spin_down}");
        }}
        QLineEdit::placeholder, QTextEdit::placeholder, QPlainTextEdit::placeholder {{ color: {t['placeholder']}; }}

        QLineEdit[contextState="quiet"] {{
            color: {t['muted']};
            background-color: {t['bg_subtle']};
        }}
        
        QComboBox QAbstractItemView {{
            background-color: {t['input_bg']};
            color: {t['input_text']};
            selection-background-color: {t['btn_primary']};
            border: 1px solid {t['input_border']};
            padding: {max(int(4 * sf), 4)}px;
        }}

        QComboBox::drop-down {{
            width: {max(int(24 * sf), 24)}px;
            border: none;
        }}

        QComboBox::down-arrow {{
            width: {max(int(10 * sf), 10)}px;
            height: {max(int(10 * sf), 10)}px;
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
        QToolButton {{
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
        QToolButton:hover:!disabled {{
            border: 1px solid {t['btn_primary']};
            background-color: {t['btn_secondary_hover']};
        }}
        QPushButton:pressed:!disabled {{
            border: 1px solid {t['btn_primary']};
            background-color: {t['btn_secondary_pressed']};
        }}
        QToolButton:pressed:!disabled {{
            border: 1px solid {t['btn_primary']};
            background-color: {t['btn_secondary_pressed']};
        }}
        QToolButton::menu-indicator {{
            width: 0px;
            image: none;
        }}

        QPushButton[kind="primary"] {{
            background-color: {t['btn_primary']};
            color: {t['btn_text']};
            border: 1px solid {t['btn_primary']};
            font-weight: 900;
        }}
        QPushButton[kind="primary"]:hover:!disabled {{ background-color: {t['btn_primary_hover']}; }}
        QPushButton[kind="primary"]:pressed:!disabled {{ background-color: {t['btn_primary_pressed']}; }}

        QPushButton[recommended="true"]:!disabled {{
            border: 2px solid {t['btn_primary']};
            padding: {max(padding_v - 1, 2)}px {max(padding_h - 1, 6)}px;
        }}

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

        QPushButton[kind="secondary"]:checked {{
            background-color: {t['btn_secondary_pressed']};
            color: {t['btn_primary']};
            border: 1px solid {t['btn_primary']};
        }}

        QPushButton[kind="ghost"] {{
            background-color: transparent;
            color: {t['btn_primary']};
            border: 1px solid transparent;
            font-weight: 700;
            padding-left: {max(int(8 * sf), 8)}px;
            padding-right: {max(int(8 * sf), 8)}px;
        }}
        QPushButton[kind="ghost"]:hover:!disabled {{
            background-color: {t['btn_secondary_hover']};
            border: 1px solid {t['input_border']};
        }}
        QPushButton[kind="ghost"]:pressed:!disabled {{
            background-color: {t['btn_secondary_pressed']};
            border: 1px solid {t['btn_primary']};
        }}

        QPushButton[kind="chip"] {{
            min-height: {max(int(26 * sf), 26)}px;
            padding: {max(int(2 * sf), 2)}px {int(12 * sf)}px;
            border-radius: {chip_radius}px;
            background-color: {t['btn_secondary_bg']};
            color: {t['text']};
            border: 1px solid {t['input_border']};
            font-weight: 700;
        }}
        QPushButton[kind="chip"]:hover:!disabled {{
            background-color: {t['btn_secondary_hover']};
            border: 1px solid {t['btn_primary']};
        }}
        QPushButton[kind="chip"]:checked {{
            background-color: {t['btn_secondary_pressed']};
            color: {t['btn_primary']};
            border: 1px solid {t['btn_primary']};
        }}

        QPushButton[kind="chip-quiet"] {{
            min-height: {max(int(24 * sf), 24)}px;
            padding: {max(int(2 * sf), 2)}px {int(10 * sf)}px;
            border-radius: {chip_radius}px;
            background-color: transparent;
            color: {t['muted_soft']};
            border: 1px solid {t['input_border']};
            font-weight: 700;
        }}
        QPushButton[kind="chip-quiet"]:hover:!disabled {{
            color: {t['text']};
            border: 1px solid {t['btn_primary']};
            background-color: {t['btn_secondary_hover']};
        }}
        QPushButton[kind="chip-quiet"]:checked {{
            color: {t['btn_primary']};
            border: 1px solid {t['btn_primary']};
            background-color: {t['btn_secondary_pressed']};
        }}

        QToolButton {{
            min-height: {max(int(26 * sf), 26)}px;
            padding: {max(int(2 * sf), 2)}px {int(10 * sf)}px;
            border-radius: {chip_radius}px;
            background-color: {t['btn_secondary_bg']};
            color: {t['text']};
            border: 1px solid {t['input_border']};
            font-weight: 700;
        }}
        QToolButton:hover:!disabled {{
            background-color: {t['btn_secondary_hover']};
            border: 1px solid {t['btn_primary']};
        }}
        QToolButton:pressed:!disabled {{
            background-color: {t['btn_secondary_pressed']};
            border: 1px solid {t['btn_primary']};
        }}
        QToolButton[kind="ghost"] {{
            background-color: transparent;
            color: {t['btn_primary']};
            border: 1px solid transparent;
        }}
        QToolButton[kind="ghost"]:hover:!disabled {{
            background-color: {t['btn_secondary_hover']};
            border: 1px solid {t['input_border']};
        }}
        QToolButton[kind="chip-quiet"] {{
            min-height: {max(int(24 * sf), 24)}px;
            padding: {max(int(2 * sf), 2)}px {int(10 * sf)}px;
            border-radius: {chip_radius}px;
            background-color: transparent;
            color: {t['muted_soft']};
            border: 1px solid {t['input_border']};
        }}
        QToolButton[kind="chip-quiet"]:hover:!disabled {{
            color: {t['text']};
            border: 1px solid {t['btn_primary']};
            background-color: {t['btn_secondary_hover']};
        }}
        QToolButton:disabled {{
            background-color: {t['btn_disabled_bg']};
            color: {t['placeholder']};
            border: 1px solid {t['input_border']};
        }}
        QToolButton:checked {{
            background-color: {t['btn_secondary_pressed']};
            border: 1px solid {t['btn_primary']};
            color: {t['btn_primary']};
        }}
        QToolButton::menu-indicator {{
            subcontrol-origin: padding;
            subcontrol-position: right center;
            width: {max(int(10 * sf), 10)}px;
        }}

        QPushButton:disabled {{
            background-color: {t['btn_disabled_bg']};
            color: {t['placeholder']};
            border: 1px solid {t['input_border']};
        }}

        QProgressBar {{
            border: 1px solid {t['input_border']};
            border-radius: {radius}px;
            background-color: {t['btn_disabled_bg']};
            color: {t['text']};
            text-align: center;
            min-height: {min_h_input}px;
        }}
        QProgressBar::chunk {{
            background-color: {t['btn_primary']};
            border-radius: {max(int(5 * sf), 5)}px;
        }}

        QScrollArea {{
            background-color: transparent;
            border: none;
        }}

        QTableView, QTableWidget {{
            background-color: {t['input_bg']};
            alternate-background-color: {t['table_alt']};
            gridline-color: {t['table_grid']};
            color: {t['text']};
            selection-background-color: {t['table_sel_bg']};
            selection-color: {t['table_sel_fg']};
            border-radius: {radius}px;
            border: 1px solid {t['input_border']};
            outline: 0;
        }}
        QTableView::item, QTableWidget::item {{
            padding: {max(int(3 * sf), 3)}px {max(int(6 * sf), 6)}px;
        }}
        QTableView::item:hover, QTableWidget::item:hover {{
            background-color: {t['table_hover']};
        }}
        QTableView::item:selected, QTableWidget::item:selected {{
            border: 0px;
        }}
        QHeaderView::section, QTableCornerButton::section {{
            background-color: {t['table_header']};
            color: {t['text']};
            padding: {int(7*sf)}px {int(8*sf)}px;
            border: 1px solid {t['table_grid']};
            font-weight: 800;
        }}

        QSplitter::handle {{ background: {t['splitter_handle']}; }}
        QSplitter::handle:hover {{ background: {t['border_strong']}; }}
        QMenu {{
            background-color: {t['bg_panel']};
            color: {t['text']};
            border: 1px solid {t['input_border']};
            padding: {max(int(6 * sf), 6)}px 0;
        }}
        QMenu::item {{
            padding: {max(int(6 * sf), 6)}px {max(int(14 * sf), 14)}px;
            margin: 0 {max(int(4 * sf), 4)}px;
            border-radius: {int(6 * sf)}px;
        }}
        QMenu::item:selected {{ background-color: {t['table_sel_bg']}; color: {t['table_sel_fg']}; }}
        QMenu::separator {{
            height: 1px;
            background: {t['input_border']};
            margin: {max(int(6 * sf), 6)}px {max(int(8 * sf), 8)}px;
        }}

        QDialogButtonBox QPushButton {{
            min-width: {max(int(110 * sf), 110)}px;
        }}

        QScrollBar:vertical {{
            background-color: transparent;
            width: {max(int(10 * sf), 10)}px;
            margin: 2px;
        }}
        QScrollBar::handle:vertical {{
            background-color: {t['input_border']};
            min-height: {max(int(28 * sf), 28)}px;
            border-radius: {max(int(5 * sf), 5)}px;
        }}
        QScrollBar::handle:vertical:hover {{
            background-color: {t['muted']};
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0px;
        }}
        QScrollBar:horizontal {{
            background-color: transparent;
            height: {max(int(10 * sf), 10)}px;
            margin: 2px;
        }}
        QScrollBar::handle:horizontal {{
            background-color: {t['input_border']};
            min-width: {max(int(28 * sf), 28)}px;
            border-radius: {max(int(5 * sf), 5)}px;
        }}
        QScrollBar::handle:horizontal:hover {{
            background-color: {t['muted']};
        }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
            width: 0px;
        }}

        /* ===== Status Bar Chips ===== */
        QLabel#StatusChip, QLabel#FormStateLabel {{
            background-color: {t['status_bg']};
            color: {t['text']};
            border: 1px solid {t['status_border']};
            border-radius: {int(8*sf)}px;
            padding: {max(int(3 * sf), 3)}px {int(10*sf)}px;
            font-weight: 700;
            font-size: {int(9*sf)}px;
            margin-left: {int(2*sf)}px;
        }}
        QLabel#FormStateLabel {{
            color: {t['btn_primary']};
            border-color: {t['btn_primary']};
            background-color: {t['status_accent_bg']};
        }}

        QLabel[role="page-meta"] {{
            color: {t['muted_soft']};
            font-size: {int(10 * sf)}px;
            font-weight: 700;
        }}

        QLabel[role="page-title"] {{
            font-size: {int(19 * sf)}px;
            font-weight: 800;
            color: {t['text']};
        }}

        QLabel[role="page-subtitle"] {{
            color: {t['muted']};
            font-size: {int(11 * sf)}px;
        }}

        QLabel[role="section-title"] {{
            font-size: {int(13 * sf)}px;
            font-weight: 800;
            color: {t['text']};
        }}

        QLabel[role="muted"] {{
            color: {t['muted']};
            font-size: {int(10 * sf)}px;
        }}

        QLabel[role="eyebrow"] {{
            color: {t['btn_primary']};
            font-size: {int(10 * sf)}px;
            font-weight: 800;
        }}

        QLabel[role="helper"] {{
            color: {t['muted']};
            font-size: {int(10 * sf)}px;
        }}

        QLabel[role="helper-strong"] {{
            color: {t['text']};
            font-size: {int(10 * sf)}px;
            font-weight: 700;
        }}

        QLabel[role="panel-caption"] {{
            color: {t['muted_soft']};
            font-size: {int(9 * sf)}px;
            font-weight: 700;
        }}

        QLabel[role="context-chip"] {{
            color: {t['btn_primary']};
            background-color: {t['status_accent_bg']};
            border: 1px solid {t['status_border']};
            border-radius: {int(10 * sf)}px;
            padding: {max(int(2 * sf), 2)}px {max(int(8 * sf), 8)}px;
            font-size: {int(9 * sf)}px;
            font-weight: 800;
        }}

        QLabel[role="account-meta"] {{
            color: {t['muted']};
            font-size: {int(9 * sf)}px;
            font-weight: 600;
        }}

        QLabel[role="account-name"] {{
            color: {t['text']};
            font-size: {int(10 * sf)}px;
            font-weight: 800;
        }}

        QLabel[role="sidebar-title"] {{
            color: {t['text']};
            font-size: {int(12 * sf)}px;
            font-weight: 800;
        }}

        QLabel[role="sidebar-helper"] {{
            color: {t['muted']};
            font-size: {int(9 * sf)}px;
            font-weight: 600;
        }}

        QLabel[role="table-caption"] {{
            color: {t['muted']};
            font-size: {int(10 * sf)}px;
            font-weight: 600;
        }}

        QLabel[role="status-note"] {{
            color: {t['muted']};
            font-size: {int(9 * sf)}px;
        }}

        QLabel[role="feedback-error"] {{
            color: {t['btn_danger']};
            background: rgba(196, 71, 71, 0.10);
            border: 1px solid rgba(196, 71, 71, 0.28);
            border-radius: {int(6 * sf)}px;
            padding: {int(3 * sf)}px {int(8 * sf)}px;
            font-size: {int(10 * sf)}px;
            font-weight: 700;
        }}

        QLabel[role="feedback-warning"] {{
            color: #d97706;
            background: rgba(217, 119, 6, 0.11);
            border: 1px solid rgba(217, 119, 6, 0.30);
            border-radius: {int(6 * sf)}px;
            padding: {int(3 * sf)}px {int(8 * sf)}px;
            font-size: {int(10 * sf)}px;
            font-weight: 700;
        }}

        QLabel[role="feedback-info"] {{
            color: {t['btn_primary']};
            background: rgba(45, 112, 201, 0.10);
            border: 1px solid rgba(45, 112, 201, 0.26);
            border-radius: {int(6 * sf)}px;
            padding: {int(3 * sf)}px {int(8 * sf)}px;
            font-size: {int(10 * sf)}px;
            font-weight: 700;
        }}

        QLabel[role="feedback-success"] {{
            color: {t['btn_success']};
            background: rgba(45, 138, 95, 0.10);
            border: 1px solid rgba(45, 138, 95, 0.26);
            border-radius: {int(6 * sf)}px;
            padding: {int(3 * sf)}px {int(8 * sf)}px;
            font-size: {int(10 * sf)}px;
            font-weight: 700;
        }}
    """

