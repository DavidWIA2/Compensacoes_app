import os
import sys
import json
import tempfile
import time
import gc
from dataclasses import replace
from pathlib import Path
from typing import List, Optional, Tuple, Dict

# --- ImportaÃ§Ãµes PySide6 ---
from PySide6.QtCore import (
    Qt, QSortFilterProxyModel, QSettings, QObject, Slot, QUrl, QThread, Signal, QTimer
)
from PySide6.QtGui import (
    QStandardItemModel, QStandardItem, QColor, QPainter, QAction, QKeySequence, QIcon
)
from PySide6.QtWidgets import (
    QApplication, QProgressDialog, QMainWindow, QWidget, QFileDialog, QMessageBox,
    QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit, QLabel,
    QTableView, QCheckBox, QSplitter, QComboBox, QButtonGroup, QTabWidget,
    QGroupBox, QDialog, QFrame, QHeaderView, QGridLayout, QRadioButton,
    QSizePolicy
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PySide6.QtCharts import (
    QChart, QChartView, QPieSeries, QBarSeries, QBarSet,
    QBarCategoryAxis, QValueAxis
)

# --- CORREÃ‡ÃƒO DE CAMINHOS (ANTES dos imports do projeto que usam GIS) ---
def _ajustar_ambiente_pyinstaller():
    """
    Garante que, no executÃ¡vel (onedir), DLLs e dados possam ser encontrados.
    """
    try:
        if getattr(sys, "frozen", False):
            exe_dir = os.path.dirname(sys.executable)
            internal_dir = os.path.join(exe_dir, "_internal")

            # adiciona caminhos no PATH (Ãºtil para libs que precisam de DLLs)
            os.environ["PATH"] = internal_dir + os.pathsep + exe_dir + os.pathsep + os.environ.get("PATH", "")

            # Alguns builds usam _MEIPASS (onefile). MantÃ©m compatibilidade:
            if hasattr(sys, "_MEIPASS"):
                os.environ["PATH"] = sys._MEIPASS + os.pathsep + os.environ.get("PATH", "")
    except Exception as exc:
        print(f"[BOOT] Falha ao ajustar ambiente do executavel: {exc}")


_ajustar_ambiente_pyinstaller()


if getattr(sys, 'frozen', False):
    # Caminho para a pasta _internal onde o PyInstaller coloca as DLLs
    internal_path = os.path.join(os.path.dirname(sys.executable), "_internal")
    os.environ["PATH"] = internal_path + os.pathsep + os.environ.get("PATH", "")

    # Tentativa especÃ­fica para o pyogrio/GDAL
    pyogrio_dlls = os.path.join(internal_path, "pyogrio", "shlib")
    if os.path.exists(pyogrio_dlls):
        os.add_dll_directory(pyogrio_dlls) if hasattr(os, "add_dll_directory") else None


def resource_path(*partes: str) -> str:
    """Resolve caminhos em desenvolvimento e no executavel PyInstaller."""
    rel = os.path.join(*partes)

    if getattr(sys, "frozen", False):
        # Pasta onde o .exe reside
        base_path = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))

        # Ordem de busca: 1. Raiz do pacote, 2. Dentro de _internal
        opcoes = [
            os.path.join(base_path, rel),
            os.path.join(base_path, "_internal", rel)
        ]

        for p in opcoes:
            if os.path.exists(p):
                return p
        return opcoes[0]  # Fallback

    # Desenvolvimento: sobe 2 nÃ­veis (de app/ui/ para a raiz)
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    return os.path.join(base_dir, rel)

    # ExecuÃ§Ã£o normal (projeto): sobe 3 nÃ­veis a partir de app/ui/main_window.py para a raiz


# --- ImportaÃ§Ãµes do Projeto ---
from app.models.compensacao import Compensacao
from app.services.excel_service import ExcelService
from app.services.geocode_service import geocode_address_arcgis
from app.services.geocode_update_service import (
    apply_geocode_to_record,
    build_cached_microbacia_finder,
)
from app.services.validation import validate_compensacao
from app.services.report_service import (
    export_csv, export_pdf, export_dashboard_pdf,
    export_excel_two_sheets, ALL_COLUMNS
)
from app.services.gis_service import GisService
from app.services.records_service import (
    compute_metrics,
    filter_records,
    row_is_compensado,
    safe_upper,
    to_float,
    unique_non_empty,
)

# --- CONSTANTES ---
COLS = [
    "Of\u00edcio/ Processo", "Eletr\u00f4nico", "Caixa", "Av. Tec.",
    "Compensa\u00e7\u00e3o", "Endere\u00e7o", "Microbacia", "Compensado"
]
MICROB_NAME_FIELD = "Nome_Do_Arquivo"
# No topo do arquivo main_window.py
MICROB_DIR = resource_path("data", "microbacias") # Use vÃ­rgulas em vez de os.path.join aqui




# --- TEMAS VISUAIS (Premium A) ---
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
    "btn_text": "#ffffff",

    "btn_danger": "#d32f2f",
    "btn_success": "#2e7d32",

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
    "btn_text": "#ffffff",

    "btn_danger": "#e04b4b",
    "btn_success": "#35a55a",

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


# --- WORKERS ---
class GeocodeWorker(QThread):
    progress_update = Signal(int, str)
    # Agora ele emite um "pacote" (dicionÃ¡rio) com todos os resultados no final
    finished_process = Signal(object)

    def __init__(self, records_to_process):
        super().__init__()
        self.records = records_to_process
        self.is_running = True
        self.resultados = {}  # A "caixa" onde ele vai guardar os acertos

    def run(self):
        total = len(self.records)
        for i, r in enumerate(self.records):
            if not self.is_running:
                break
            address = r.endereco
            self.progress_update.emit(i, f"Buscando ({i + 1}/{total}): {str(address)[:30]}...")

            coords = self._geocode_api(address)
            if coords:
                # Guarda as coordenadas no pacote usando o nÃºmero da linha do Excel
                self.resultados[r.excel_row] = (coords[0], coords[1])
            time.sleep(0.3)

        # Entrega o pacote completo de uma vez sÃ³!
        self.finished_process.emit(self.resultados)

    def stop(self):
        self.is_running = False

    def _geocode_api(self, address: str):
        return geocode_address_arcgis(address, timeout=8)

# --- UI COMPONENTS ---
class MapBridge(QObject):
    def __init__(self, on_clicked_callback, on_layer_changed_callback=None):
        super().__init__()
        self._on_clicked = on_clicked_callback
        self._on_layer_changed = on_layer_changed_callback

    @Slot(float, float)
    def onMapClicked(self, lat: float, lng: float):
        if self._on_clicked:
            self._on_clicked(lat, lng)

    @Slot(str)
    def onLayerChanged(self, layer_name: str):
        if self._on_layer_changed:
            self._on_layer_changed(layer_name)


class DebugPage(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        # Se quiser depurar, troque por: print(message, sourceID, lineNumber)
        pass


class CheckableComboBox(QComboBox):
    def __init__(self, all_label: str):
        super().__init__()
        self._all_label = all_label
        self.setEditable(True)
        self.lineEdit().setReadOnly(True)
        self.lineEdit().setPlaceholderText(all_label)
        self.setInsertPolicy(QComboBox.NoInsert)
        model = QStandardItemModel()
        self.setModel(model)
        self.view().pressed.connect(self._on_pressed)
        self.set_items([])

    def set_items(self, items: List[str]):
        m = self.model()
        m.clear()
        all_item = QStandardItem(self._all_label)
        all_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
        all_item.setData(Qt.Checked, Qt.CheckStateRole)
        m.appendRow(all_item)
        for it in items:
            if not it or not str(it).strip():
                continue
            row = QStandardItem(it)
            row.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            row.setData(Qt.Unchecked, Qt.CheckStateRole)
            m.appendRow(row)
        self._refresh_text()

    def checked_items(self) -> List[str]:
        m = self.model()
        out = []
        for i in range(1, m.rowCount()):
            item = m.item(i)
            if item.data(Qt.CheckStateRole) == Qt.Checked:
                out.append(item.text())
        return out

    def select_all(self):
        m = self.model()
        if m.rowCount() == 0:
            return
        m.item(0).setData(Qt.Checked, Qt.CheckStateRole)
        for i in range(1, m.rowCount()):
            m.item(i).setData(Qt.Unchecked, Qt.CheckStateRole)
        self._refresh_text()
        self.currentTextChanged.emit(self.currentText())

    def _on_pressed(self, index):
        m = self.model()
        item = m.itemFromIndex(index)
        if not item:
            return

        new_state = Qt.Unchecked if item.data(Qt.CheckStateRole) == Qt.Checked else Qt.Checked
        item.setData(new_state, Qt.CheckStateRole)

        if index.row() == 0:
            if new_state == Qt.Checked:
                for i in range(1, m.rowCount()):
                    m.item(i).setData(Qt.Unchecked, Qt.CheckStateRole)
        else:
            if new_state == Qt.Checked:
                m.item(0).setData(Qt.Unchecked, Qt.CheckStateRole)

            has_checked = False
            for i in range(1, m.rowCount()):
                if m.item(i).data(Qt.CheckStateRole) == Qt.Checked:
                    has_checked = True
                    break
            if not has_checked:
                m.item(0).setData(Qt.Checked, Qt.CheckStateRole)

        self._refresh_text()
        self.currentTextChanged.emit(self.currentText())

    def _refresh_text(self):
        checked = self.checked_items()
        self.lineEdit().setText(self._all_label if not checked else ", ".join(checked))

    # Em app/ui/main_window.py (Classe CheckableComboBox)
    def is_all_selected(self) -> bool:
        model = self.model()
        # Verifica se o model existe e se tem pelo menos uma linha (o "Todos")
        if not model or model.rowCount() == 0:
            return True  # Se nÃ£o hÃ¡ itens, assume que nÃ£o hÃ¡ restriÃ§Ã£o de filtro
        item = model.item(0)
        if not item:
            return True
        return item.data(Qt.CheckStateRole) == Qt.Checked


class NumericSortProxy(QSortFilterProxyModel):
    def lessThan(self, left, right):
        if left.column() == 4:
            l = self.sourceModel().data(left, Qt.UserRole)
            r = self.sourceModel().data(right, Qt.UserRole)
            try:
                return float(l) < float(r)
            except Exception:
                return str(l) < str(r)
        return super().lessThan(left, right)


class KPICard(QFrame):
    def __init__(self, title: str, value: str, color: str):
        super().__init__()
        self.color = color
        self.setFrameShape(QFrame.StyledPanel)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(4)

        self.lbl_title = QLabel(title.upper())
        self.lbl_title.setObjectName("Titulo")
        self.lbl_value = QLabel(value)
        self.lbl_value.setObjectName("Valor")

        layout.addWidget(self.lbl_title)
        layout.addWidget(self.lbl_value)
        layout.addStretch(1)

    def update_style(self, theme: dict):
        self.setStyleSheet(f"""
            KPICard {{
                background-color: {theme['kpi_bg']};
                border-radius: 10px;
                border-left: 6px solid {self.color};
                border: 1px solid {theme['kpi_border']};
            }}
            QLabel#Valor {{
                font-size: 20px;
                font-weight: 800;
                color: {theme['text']};
                border: none;
            }}
            QLabel#Titulo {{
                font-size: 11px;
                font-weight: 800;
                color: {theme['muted']};
                border: none;
            }}
        """)

    def update_value(self, new_value: str):
        self.lbl_value.setText(new_value)


class ColumnsDialog(QDialog):
    def __init__(self, parent, visible_map: Dict[int, bool]):
        super().__init__(parent)
        self.setWindowTitle("Selecionar Colunas")
        self.resize(380, 450)

        layout = QVBoxLayout(self)
        lbl = QLabel("Marque as colunas que deseja exibir:")
        layout.addWidget(lbl)

        self.in_busca = QLineEdit()
        self.in_busca.setPlaceholderText("Pesquisar coluna...")
        layout.addWidget(self.in_busca)

        self.checks: List[QCheckBox] = []
        for i, name in enumerate(COLS):
            cb = QCheckBox(name)
            cb.setChecked(visible_map.get(i, True))
            self.checks.append(cb)
            layout.addWidget(cb)

        def _filtrar_colunas():
            termo = self.in_busca.text().strip().lower()
            for cb2 in self.checks:
                cb2.setVisible((termo in cb2.text().lower()) if termo else True)

        self.in_busca.textChanged.connect(_filtrar_colunas)

        layout.addStretch(1)

        btn_batch_layout = QHBoxLayout()
        self.btn_all = QPushButton("Marcar Todos")
        self.btn_none = QPushButton("Desmarcar Todos")
        self.btn_reset = QPushButton("Padr\u00e3o")
        btn_batch_layout.addWidget(self.btn_all)
        btn_batch_layout.addWidget(self.btn_none)
        btn_batch_layout.addWidget(self.btn_reset)
        layout.addLayout(btn_batch_layout)

        btns = QHBoxLayout()
        self.btn_ok = QPushButton("Aplicar")
        self.btn_cancel = QPushButton("Cancelar")
        btns.addStretch()
        btns.addWidget(self.btn_ok)
        btns.addWidget(self.btn_cancel)
        layout.addLayout(btns)

        self.btn_all.clicked.connect(lambda: [c.setChecked(True) for c in self.checks])
        self.btn_none.clicked.connect(lambda: [c.setChecked(False) for c in self.checks])
        self.btn_reset.clicked.connect(lambda: [c.setChecked(True) for c in self.checks])
        self.btn_ok.clicked.connect(self.accept)
        self.btn_cancel.clicked.connect(self.reject)

    def result_map(self) -> Dict[int, bool]:
        return {i: cb.isChecked() for i, cb in enumerate(self.checks)}


class MapFullScreenDialog(QDialog):
    def __init__(self, parent, html_path, geojson_data, theme, marker_coords, gis_service, current_layer,
                 heatmap_points):
        super().__init__(parent)
        self.setWindowFlags(Qt.Window)
        self.setWindowTitle("Mapa - Tela Cheia")
        self.resize(1200, 800)

        self.geojson_data = geojson_data
        self.theme = theme
        self.marker_coords = marker_coords
        self.gis = gis_service
        self.current_layer = current_layer
        self.heatmap_points = heatmap_points
        self.parent_window = parent
        self._geocode_address = parent.geocode_address if parent and hasattr(parent, "geocode_address") else geocode_address_arcgis

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        top_bar = QFrame()
        top_bar.setObjectName("TopBar")
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(10, 8, 10, 8)
        top_layout.setSpacing(8)

        self.in_search = QLineEdit()
        self.in_search.setPlaceholderText("Pesquisar endere\u00e7o...")
        self.in_search.setMinimumWidth(340)

        self.btn_search = QPushButton("Buscar")
        btn_close = QPushButton("Sair")

        self.lbl_status = QLabel("")
        self.lbl_status.setObjectName("MapStatus")

        top_layout.addWidget(self.in_search)
        top_layout.addWidget(self.btn_search)
        top_layout.addWidget(self.lbl_status, 1)
        top_layout.addWidget(btn_close)

        layout.addWidget(top_bar)

        self.web = QWebEngineView()
        self.web.setPage(DebugPage(self.web))
        s = self.web.page().settings()
        s.setAttribute(QWebEngineSettings.PluginsEnabled, False)
        s.setAttribute(QWebEngineSettings.JavascriptCanOpenWindows, False)
        s.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
        s.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)

        self.channel = QWebChannel(self.web.page())
        self.bridge = MapBridge(lambda lat, lng: None, self._on_layer_changed_fullscreen)
        self.channel.registerObject("bridge", self.bridge)
        self.web.page().setWebChannel(self.channel)

        self.web.loadFinished.connect(self._on_loaded)
        self.web.setUrl(QUrl.fromLocalFile(str(html_path)))

        layout.addWidget(self.web, 1)

        btn_close.clicked.connect(self.close)
        self.btn_search.clicked.connect(self.perform_search)
        self.in_search.returnPressed.connect(self.perform_search)

        self.showMaximized()

    def _run_map_js(self, script: str, context: str) -> bool:
        try:
            self.web.page().runJavaScript(script)
            return True
        except Exception as exc:
            print(f"[FS MAP JS] Falha em {context}: {exc}")
            return False

    def _on_layer_changed_fullscreen(self, layer_name):
        if self.parent_window:
            self.parent_window.save_map_layer_preference(layer_name)

    def _on_loaded(self, ok):
        if not ok:
            return
        if self.geojson_data:
            self._run_map_js(
                f"if(window.setMicrobacias) window.setMicrobacias({json.dumps(self.geojson_data)});",
                "microbacias",
            )
        if self.theme:
            self._run_map_js(f"if(window.setTheme) window.setTheme('{self.theme}');", "theme")
        if self.current_layer:
            self._run_map_js(
                f"if(window.setBaseLayer) window.setBaseLayer('{self.current_layer}');",
                "base-layer",
            )
        if self.marker_coords:
            self._run_map_js(
                f"if(window.setMarker) window.setMarker({self.marker_coords[0]}, {self.marker_coords[1]});",
                "marker",
            )
        if self.heatmap_points:
            self._run_map_js(
                f"if(window.setHeatmap) window.setHeatmap({json.dumps(self.heatmap_points)});",
                "heatmap",
            )

    def perform_search(self):
        address = self.in_search.text().strip()
        if not address:
            return
        self.lbl_status.setText("Buscando...")
        QApplication.processEvents()

        try:
            coords = self._geocode_address(address)
            if coords:
                lat, lng = coords
                self._run_map_js(f"if(window.setMarker) window.setMarker({lat}, {lng});", "search-marker")
                self.marker_coords = (lat, lng)
                if self.parent_window:
                    self.parent_window.last_marker_coords = (lat, lng)
                self.lbl_status.setText("Localizado")
            else:
                self.lbl_status.setText("Não encontrado")
        except Exception as exc:
            print(f"[FS MAP] Falha na busca por endereço: {exc}")
            self.lbl_status.setText("Erro")


# --- MAIN WINDOW ---

class TableFullScreenDialog(QDialog):
    """
    Tela cheia da planilha.

    Requisitos:
    - Manter filtros, barra de busca e botÃµes de exportaÃ§Ã£o tambÃ©m em tela cheia.
    - NÃ£o duplicar a tabela (reusa o painel esquerdo com tabela + totais + exportaÃ§Ã£o).
    - Controles no topo sÃ£o "espelhos" sincronizados com os controles da janela principal,
      para nÃ£o mexer no layout original e evitar bugs de reparent.
    """

    def __init__(self, parent: "MainWindow", content_widget: QWidget, on_close_callback):
        super().__init__(parent)
        self.setWindowFlags(Qt.Window)
        self.setWindowTitle("Planilha - Tela Cheia")

        self._mw = parent
        self._content = content_widget
        self._on_close_callback = on_close_callback
        self._syncing = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ---------- Barra superior ----------
        top = QFrame()
        top.setObjectName("TopBar")
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(10, 10, 10, 10)
        top_layout.setSpacing(8)

        lbl = QLabel("Planilha - Tela Cheia")
        lbl.setObjectName("FsTitle")

        self.btn_exit = QPushButton("Sair da Tela Cheia")
        self.btn_exit.setProperty("kind", "secondary")
        self.btn_exit.clicked.connect(self.close)

        top_layout.addWidget(lbl)
        top_layout.addStretch(1)
        top_layout.addWidget(self.btn_exit)
        layout.addWidget(top)

        # ---------- Barra de busca (espelho) ----------
        search_bar = QFrame()
        search_bar.setObjectName("SearchBarFs")
        sb = QHBoxLayout(search_bar)
        sb.setContentsMargins(10, 0, 10, 10)
        sb.setSpacing(8)

        self.in_search = QLineEdit()
        self.in_search.setPlaceholderText("Buscar (of\u00edcio, av. tec., endere\u00e7o, microbacia...)")
        self.in_search.setClearButtonEnabled(True)
        self.in_search.setText(self._mw.search.text())

        # mantÃ©m sincronizado nos dois sentidos
        self.in_search.textChanged.connect(self._on_fs_search_changed)
        self._mw.search.textChanged.connect(self._on_main_search_changed)

        sb.addWidget(QLabel("Busca:"))
        sb.addWidget(self.in_search, 1)

        # (opcional) botÃ£o limpar rÃ¡pido
        self.btn_clear_search = QPushButton("Limpar Busca")
        self.btn_clear_search.setProperty("kind", "secondary")
        self.btn_clear_search.clicked.connect(lambda: self.in_search.setText(""))
        sb.addWidget(self.btn_clear_search)

        layout.addWidget(search_bar)

        # ---------- Barra de filtros (espelho) ----------
        filt_bar = QFrame()
        filt_bar.setObjectName("FilterBarFs")
        fb = QHBoxLayout(filt_bar)
        fb.setContentsMargins(10, 0, 10, 10)
        fb.setSpacing(8)

        fb.addWidget(QLabel("Filtros:"))

        self.fs_filter_micro = self._clone_checkable_combo(self._mw.filter_micro, "Todas as Microbacias")
        self.fs_filter_eletronico = self._clone_checkable_combo(self._mw.filter_eletronico, "Eletr\u00f4nico")

        self.fs_filter_status = QComboBox()
        self._copy_combo_items(self._mw.filter_status, self.fs_filter_status)
        self.fs_filter_status.setCurrentIndex(self._mw.filter_status.currentIndex())

        # botÃµes (chamam as mesmas aÃ§Ãµes do MainWindow)
        self.btn_clear_filters = QPushButton("Limpar")
        self.btn_clear_filters.setProperty("kind", "secondary")
        self.btn_clear_filters.clicked.connect(self._mw.clear_filters)

        self.btn_reset_sort = QPushButton("Redefinir Ordem")
        self.btn_reset_sort.setProperty("kind", "secondary")
        self.btn_reset_sort.clicked.connect(self._mw.clear_sorting)

        self.btn_columns = QPushButton("Colunas")
        self.btn_columns.setProperty("kind", "secondary")
        self.btn_columns.clicked.connect(self._mw.open_columns_dialog)

        fb.addWidget(self.fs_filter_micro)
        fb.addWidget(self.fs_filter_eletronico)
        fb.addWidget(self.fs_filter_status)
        fb.addWidget(self.btn_clear_filters)
        fb.addWidget(self.btn_reset_sort)
        fb.addWidget(self.btn_columns)
        fb.addStretch(1)

        # contador (espelho do label principal, se existir)
        self.lbl_results = QLabel(
            getattr(self._mw, "lbl_results", QLabel("")).text() if hasattr(self._mw, "lbl_results") else "")
        self.lbl_results.setObjectName("ResultsLabelFs")
        self.lbl_results.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.lbl_results.setMinimumWidth(170)
        fb.addWidget(self.lbl_results)

        layout.addWidget(filt_bar)

        self._fs_micro_to_main_slot = lambda: self._sync_checkable_to_main(self.fs_filter_micro, self._mw.filter_micro)
        self._fs_ele_to_main_slot = lambda: self._sync_checkable_to_main(
            self.fs_filter_eletronico, self._mw.filter_eletronico
        )
        self._main_micro_to_fs_slot = lambda: self._sync_checkable_to_fs(self._mw.filter_micro, self.fs_filter_micro)
        self._main_ele_to_fs_slot = lambda: self._sync_checkable_to_fs(
            self._mw.filter_eletronico, self.fs_filter_eletronico
        )

        # sincronizaÃ§Ã£o filtros (fs -> main)
        self.fs_filter_micro.currentTextChanged.connect(
            self._fs_micro_to_main_slot)
        self.fs_filter_eletronico.currentTextChanged.connect(
            self._fs_ele_to_main_slot)
        self.fs_filter_status.currentTextChanged.connect(self._on_fs_status_changed)

        # sincronizaÃ§Ã£o filtros (main -> fs)
        self._mw.filter_micro.currentTextChanged.connect(
            self._main_micro_to_fs_slot)
        self._mw.filter_eletronico.currentTextChanged.connect(
            self._main_ele_to_fs_slot)
        self._mw.filter_status.currentTextChanged.connect(self._on_main_status_changed)

        # manter contador em sync quando filtro roda
        # sempre que statusbar mudar (apÃ³s apply_filter), atualiza contador
        self._mw.search.textChanged.connect(self._refresh_results_label)
        self._mw.filter_status.currentTextChanged.connect(self._refresh_results_label)
        self._mw.filter_micro.currentTextChanged.connect(self._refresh_results_label)
        self._mw.filter_eletronico.currentTextChanged.connect(self._refresh_results_label)

        # ---------- ConteÃºdo (painel esquerdo com tabela + totais + exportaÃ§Ã£o) ----------
        self._content.setParent(self)
        layout.addWidget(self._content, 1)

        # aplica foco na busca
        self.in_search.setFocus()

    # ----- helpers clone/sync -----
    @staticmethod
    def _copy_combo_items(src: QComboBox, dst: QComboBox):
        dst.clear()
        for i in range(src.count()):
            dst.addItem(src.itemText(i))

    @staticmethod
    def _clone_checkable_combo(src: "CheckableComboBox", all_label: str) -> "CheckableComboBox":
        # Clona itens + estado de check
        items = []
        m = src.model()
        for i in range(1, m.rowCount()):
            items.append(m.item(i).text())
        clone = CheckableComboBox(all_label)
        clone.set_items(items)

        # copia checkstate
        cm = clone.model()
        src_all = m.item(0)
        dst_all = cm.item(0)
        if src_all is not None and dst_all is not None:
            dst_all.setData(src_all.data(Qt.CheckStateRole), Qt.CheckStateRole)
        for i in range(1, min(m.rowCount(), cm.rowCount())):
            cm.item(i).setData(m.item(i).data(Qt.CheckStateRole), Qt.CheckStateRole)

        clone._refresh_text()
        return clone

    def _sync_checkable_to_main(self, fs: "CheckableComboBox", main: "CheckableComboBox"):
        if self._syncing:
            return
        self._syncing = True
        try:
            fm = fs.model()
            mm = main.model()

            # garante mesma contagem (caso main tenha sido atualizado)
            if mm.rowCount() != fm.rowCount():
                # reconstrÃ³i o FS a partir do main
                rebuilt = self._clone_checkable_combo(main, main._all_label if hasattr(main, "_all_label") else "Todos")
                fs.blockSignals(True)
                fs.setModel(rebuilt.model())
                fs.blockSignals(False)
                fm = fs.model()
                mm = main.model()

            # copia estados do FS -> main
            for i in range(min(fm.rowCount(), mm.rowCount())):
                mm.item(i).setData(fm.item(i).data(Qt.CheckStateRole), Qt.CheckStateRole)

            main._refresh_text()
            main.currentTextChanged.emit(main.currentText())
        finally:
            self._syncing = False

    def _sync_checkable_to_fs(self, main: "CheckableComboBox", fs: "CheckableComboBox"):
        if self._syncing:
            return
        self._syncing = True
        try:
            mm = main.model()
            fm = fs.model()

            # se mudou a lista no main, recria o FS
            if mm.rowCount() != fm.rowCount():
                new_fs = self._clone_checkable_combo(main, main._all_label if hasattr(main, "_all_label") else "Todos")
                fs.blockSignals(True)
                fs.setModel(new_fs.model())
                fs.blockSignals(False)
                fs._refresh_text()
                return

            for i in range(min(mm.rowCount(), fm.rowCount())):
                fm.item(i).setData(mm.item(i).data(Qt.CheckStateRole), Qt.CheckStateRole)

            fs._refresh_text()
        finally:
            self._syncing = False

    def _on_fs_status_changed(self):
        if self._syncing:
            return
        self._syncing = True
        try:
            self._mw.filter_status.setCurrentIndex(self.fs_filter_status.currentIndex())
        finally:
            self._syncing = False

    def _on_main_status_changed(self):
        if self._syncing:
            return
        self._syncing = True
        try:
            self.fs_filter_status.setCurrentIndex(self._mw.filter_status.currentIndex())
        finally:
            self._syncing = False

    def _on_fs_search_changed(self, txt: str):
        if self._syncing:
            return
        self._syncing = True
        try:
            # atualiza o campo principal (mantÃ©m toda a lÃ³gica existente de filtro)
            self._mw.search.setText(txt)
        finally:
            self._syncing = False

    def _on_main_search_changed(self, txt: str):
        if self._syncing:
            return
        self._syncing = True
        try:
            if self.in_search.text() != txt:
                self.in_search.setText(txt)
        finally:
            self._syncing = False

    def _refresh_results_label(self):
        if hasattr(self._mw, "lbl_results") and hasattr(self, "lbl_results"):
            self.lbl_results.setText(self._mw.lbl_results.text())

    @staticmethod
    def _safe_disconnect(signal, slot):
        try:
            signal.disconnect(slot)
        except (TypeError, RuntimeError):
            pass

    def closeEvent(self, event):
        try:
            # desconecta sinais (evita referÃªncias penduradas)
            self._safe_disconnect(self._mw.search.textChanged, self._on_main_search_changed)
            self._safe_disconnect(self._mw.filter_status.currentTextChanged, self._on_main_status_changed)
            self._safe_disconnect(self._mw.filter_micro.currentTextChanged, self._main_micro_to_fs_slot)
            self._safe_disconnect(self._mw.filter_eletronico.currentTextChanged, self._main_ele_to_fs_slot)
            self._safe_disconnect(self.fs_filter_micro.currentTextChanged, self._fs_micro_to_main_slot)
            self._safe_disconnect(self.fs_filter_eletronico.currentTextChanged, self._fs_ele_to_main_slot)
            self._safe_disconnect(self._mw.search.textChanged, self._refresh_results_label)
            self._safe_disconnect(self._mw.filter_status.currentTextChanged, self._refresh_results_label)
            self._safe_disconnect(self._mw.filter_micro.currentTextChanged, self._refresh_results_label)
            self._safe_disconnect(self._mw.filter_eletronico.currentTextChanged, self._refresh_results_label)

            if callable(self._on_close_callback):
                self._on_close_callback(self._content)
        finally:
            super().closeEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Escape, Qt.Key_F11):
            self.close()
            return
        super().keyPressEvent(event)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Compensa\u00e7\u00f5es - Cadastro e Consulta")

        icon_path = resource_path("assets", "app.ico")  # Ajuste o nome conforme seu arquivo em /assets
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        else:
            print(f"Aviso: \u00cdcone n\u00e3o encontrado em {icon_path}")

        self.excel = ExcelService()
        self.records: List[Compensacao] = []
        self.filtered_records: List[Compensacao] = []
        self.selected: Optional[Compensacao] = None
        self.records_by_excel_row: Dict[int, Compensacao] = {}
        self._all_metrics_cache: Optional[Dict[str, object]] = None
        self._filtered_metrics_cache: Optional[Dict[str, object]] = None
        self._heatmap_revision = 0
        self._heatmap_cache_signature = None
        self._heatmap_points_cache: Optional[List[List[float]]] = None
        self.gis: Optional[GisService] = None
        self.last_marker_coords: Optional[Tuple[float, float]] = None

        self.settings = QSettings("CompensacoesApp", "CompensacoesDesktop")
        self.columns_visible: Dict[int, bool] = {i: True for i in range(len(COLS))}
        self.is_dark_mode = str(self.settings.value("dark_mode", "false")).lower() == "true"
        self.geo_worker = None
        self._is_reset_state = False
        self._did_initial_resize = False  # evita â€œtremorâ€ ao filtrar
        self._table_fs_dialog = None
        self._table_fs_placeholder = None
        self._table_fs_split_state = None
        self._table_fs_split_sizes = None

        # Timer para "debounce" do filtro (evita recalcular a cada tecla)
        self._timer_filtro = QTimer(self)
        self._timer_filtro.setSingleShot(True)
        self._timer_filtro.setInterval(180)
        self._timer_filtro.timeout.connect(self.apply_filter)

        self._load_column_settings()

        root = QWidget()
        self.setCentralWidget(root)

        main_layout = QVBoxLayout(root)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(8)

        # ===== Top Bar (compact + premium) =====
        top = QHBoxLayout()
        top.setSpacing(8)

        self.btn_open = QPushButton("Abrir Excel")
        self.btn_reload = QPushButton("Recarregar")

        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar (of\u00edcio, av. tec., endere\u00e7o, microbacia...)")
        self.search.setClearButtonEnabled(True)

        self.btn_theme = QPushButton("Tema")
        self.btn_theme.setToolTip("Alternar Modo Claro/Escuro")
        self.btn_theme.setFixedWidth(70)

        # impedir â€œafinamentoâ€ ao maximizar
        self.btn_open.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.btn_reload.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.search.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.btn_theme.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        top.addWidget(self.btn_open)
        top.addWidget(self.btn_reload)
        top.addWidget(self.search, 1)
        top.addWidget(self.btn_theme)

        main_layout.addLayout(top)

        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs, 1)

        # ===== TAB: Dados & Cadastro =====
        tab_data = QWidget()
        tab_data_layout = QVBoxLayout(tab_data)
        tab_data_layout.setContentsMargins(0, 0, 0, 0)
        tab_data_layout.setSpacing(8)

        # Filters row (compact)
        filters = QHBoxLayout()
        filters.setSpacing(8)

        self.filter_micro = CheckableComboBox("Todas as Microbacias")
        self.filter_micro.setMinimumWidth(240)

        self.filter_eletronico = CheckableComboBox("Eletr\u00f4nico")
        self.filter_eletronico.setMinimumWidth(180)

        self.filter_status = QComboBox()
        self.filter_status.addItems(["Todos", "Compensados", "Pendentes"])
        self.filter_status.setMinimumWidth(150)

        self.btn_clear_filters = QPushButton("Limpar")
        self.btn_reset_sort = QPushButton("Redefinir Ordem")
        self.btn_columns = QPushButton("Colunas")
        self.btn_table_full = QPushButton("Tela Cheia")
        self.btn_table_full.setToolTip("Abrir a planilha em tela cheia")
        self.btn_table_full.setProperty("kind", "secondary")

        filters.addWidget(QLabel("Filtros:"))
        filters.addWidget(self.filter_micro)
        filters.addWidget(self.filter_eletronico)
        filters.addWidget(self.filter_status)
        filters.addWidget(self.btn_clear_filters)
        filters.addWidget(self.btn_reset_sort)
        filters.addWidget(self.btn_columns)
        filters.addWidget(self.btn_table_full)
        filters.addStretch(1)

        self.lbl_results = QLabel("0 registros")
        self.lbl_results.setObjectName("ResultsLabel")
        self.lbl_results.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.lbl_results.setMinimumWidth(170)
        filters.addWidget(self.lbl_results)

        tab_data_layout.addLayout(filters)

        # Main Splitter
        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.setHandleWidth(8)
        tab_data_layout.addWidget(self.main_splitter, 1)

        # ---------- LEFT ----------
        left = QWidget()
        self._left_panel = left  # usado para tela cheia da planilha
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        self.model = QStandardItemModel(0, len(COLS))
        self.model.setHorizontalHeaderLabels(COLS)

        # Alinhamento do cabeÃ§alho por tipo (melhor leitura)
        self.model.setHeaderData(4, Qt.Horizontal, Qt.AlignRight | Qt.AlignVCenter,
                                 Qt.TextAlignmentRole)  # CompensaÃ§Ã£o
        self.model.setHeaderData(7, Qt.Horizontal, Qt.AlignCenter | Qt.AlignVCenter,
                                 Qt.TextAlignmentRole)  # Compensado

        self.proxy = NumericSortProxy()
        self.proxy.setSourceModel(self.model)

        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setSelectionMode(QTableView.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.selectionModel().currentRowChanged.connect(self._on_current_row_changed)

        # Row numbers (visÃ­veis)
        self.table.verticalHeader().setVisible(True)
        self.table.verticalHeader().setDefaultSectionSize(24)
        self.table.verticalHeader().setMinimumWidth(38)

        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table.horizontalHeader().sectionClicked.connect(self._on_header_clicked)

        # pequena melhoria de legibilidade
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.ElideRight)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)

        left_layout.addWidget(self.table, 1)

        left_layout.addWidget(self._build_totals_group())
        left_layout.addWidget(self._build_export_bar())

        self.main_splitter.addWidget(left)

        # ---------- RIGHT ----------
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        right_layout.addWidget(self._build_form_group())

        right_layout.addLayout(self._build_crud_buttons_layout())
        right_layout.addWidget(self._build_map_group())

        # Map view
        self.web = QWebEngineView()
        self.web.setMinimumHeight(380)
        right_layout.addWidget(self.web, 1)

        self.main_splitter.addWidget(right)
        self.main_splitter.setSizes([910, 520])

        self.tabs.addTab(tab_data, "Dados & Cadastro")

        # ===== TAB: Dashboard =====
        tab_dash = QWidget()
        dash_layout = QVBoxLayout(tab_dash)
        dash_layout.setContentsMargins(0, 0, 0, 0)
        dash_layout.setSpacing(8)

        dash_layout.addLayout(self._build_dashboard_cards_layout())
        dash_layout.addLayout(self._build_dashboard_actions_layout())

        dash_layout.addWidget(self._build_dashboard_splitter(), 1)
        self.dash_splitter.addWidget(self._build_dashboard_pie_panel())
        self.dash_splitter.addWidget(self._build_dashboard_micro_chart_panel())

        self.tabs.addTab(tab_dash, "Painel")

        # ===== Wiring =====
        self._setup_leaflet_map()
        self._load_last_excel()
        self._load_sort_settings()
        self._restore_splitter_preferences()
        self._restore_window_preferences()

        self._apply_button_kind_properties()
        self._connect_main_signals()

        # Shortcuts (premium)
        self._setup_shortcuts()
        self._finalize_initial_ui_state()


    # ===== Shortcuts =====
    def _restore_splitter_preferences(self):
        try:
            state = self.settings.value("split_main")
            if state is not None:
                self.main_splitter.restoreState(state)
        except Exception as exc:
            print(f"[SETTINGS] Falha ao restaurar split_main: {exc}")

        try:
            state = self.settings.value("split_dash")
            if state is not None:
                self.dash_splitter.restoreState(state)
        except Exception as exc:
            print(f"[SETTINGS] Falha ao restaurar split_dash: {exc}")

    def _finalize_initial_ui_state(self):
        self._set_enabled_all(False)
        self.clear_filters()
        self._apply_columns_visibility(resize=True)  # 1x so
        self._apply_theme()
        self._update_address_search_enabled()
        self._update_form_action_buttons()
        if self.excel.path and self.records:
            self._set_enabled_all(True)

        self.statusBar().showMessage("Pronto")

        # Mantem a janela utilizavel em telas menores sem esmagar os botoes.
        self.setMinimumSize(1024, 600)
        self.table.setMinimumHeight(50)

    def _build_form_group(self):
        form_group = QGroupBox("Cadastro / Edição")
        form_layout = QGridLayout(form_group)
        form_layout.setContentsMargins(10, 10, 10, 10)
        form_layout.setHorizontalSpacing(10)
        form_layout.setVerticalSpacing(6)

        def make_label(text: str) -> QLabel:
            label = QLabel(text)
            label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            label.setMinimumWidth(110)
            return label

        def make_line_edit() -> QLineEdit:
            line_edit = QLineEdit()
            line_edit.setMinimumHeight(26)
            line_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            return line_edit

        self.in_oficio = make_line_edit()
        self.in_caixa = make_line_edit()
        self.in_avtec = make_line_edit()
        self.in_comp = make_line_edit()
        self.in_end = make_line_edit()

        self.in_micro = QComboBox()
        self.in_micro.setEditable(True)
        self.in_micro.setMinimumHeight(26)
        self.in_micro.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.eletronico_container = QWidget()
        self.eletronico_layout = QHBoxLayout(self.eletronico_container)
        self.eletronico_layout.setContentsMargins(0, 0, 0, 0)
        self.eletronico_layout.setSpacing(10)
        self.eletronico_group = QButtonGroup(self)
        self.eletronico_group.setExclusive(True)

        self.chk_compensado = QCheckBox("Compensado (SIM)")
        self.chk_compensado.setMinimumHeight(24)

        form_layout.addWidget(make_label("Ofício/Processo:"), 0, 0)
        form_layout.addWidget(self.in_oficio, 0, 1)
        form_layout.addWidget(make_label("Compensação:"), 0, 2)
        form_layout.addWidget(self.in_comp, 0, 3)

        form_layout.addWidget(make_label("Eletrônico:"), 1, 0)
        form_layout.addWidget(self.eletronico_container, 1, 1)
        form_layout.addWidget(make_label("Microbacia:"), 1, 2)
        form_layout.addWidget(self.in_micro, 1, 3)

        form_layout.addWidget(make_label("Caixa:"), 2, 0)
        form_layout.addWidget(self.in_caixa, 2, 1)
        form_layout.addWidget(make_label("Endereço:"), 2, 2)
        form_layout.addWidget(self.in_end, 2, 3)

        form_layout.addWidget(make_label("Av. Tec.:"), 3, 0)
        form_layout.addWidget(self.in_avtec, 3, 1)
        form_layout.addWidget(QLabel(""), 3, 2)
        form_layout.addWidget(self.chk_compensado, 3, 3)

        form_layout.setColumnStretch(1, 1)
        form_layout.setColumnStretch(3, 1)
        return form_group

    def _build_dashboard_cards_layout(self):
        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(8)

        self.card_total = KPICard("Total Mudas", "0", "#2176ff")
        self.card_pend = KPICard("Pendentes", "0", "#d32f2f")
        self.card_comp = KPICard("Compensadas", "0", "#2e7d32")
        self.card_records = KPICard("Total Processos", "0", "#ff9800")

        cards_layout.addWidget(self.card_total)
        cards_layout.addWidget(self.card_pend)
        cards_layout.addWidget(self.card_comp)
        cards_layout.addWidget(self.card_records)
        return cards_layout

    def _build_dashboard_actions_layout(self):
        actions_layout = QHBoxLayout()
        self.btn_export_dashboard_pdf = QPushButton("Exportar Painel (PDF)")
        actions_layout.addStretch(1)
        actions_layout.addWidget(self.btn_export_dashboard_pdf)
        return actions_layout

    def _build_dashboard_splitter(self):
        self.dash_splitter = QSplitter(Qt.Horizontal)
        self.dash_splitter.setChildrenCollapsible(False)
        self.dash_splitter.setHandleWidth(8)
        return self.dash_splitter

    def _build_dashboard_pie_panel(self):
        self.pie_chart = QChart()
        self.pie_series = QPieSeries()
        self.pie_series.setHoleSize(0.40)
        self.pie_chart.addSeries(self.pie_series)
        self.pie_chart.setTitle("Status de Compensa\u00e7\u00e3o")
        self.pie_chart.legend().setAlignment(Qt.AlignBottom)

        self.pie_container = QFrame()
        pie_layout = QVBoxLayout(self.pie_container)
        pie_layout.setContentsMargins(8, 8, 8, 8)
        self.pie_view = QChartView(self.pie_chart)
        self.pie_view.setRenderHint(QPainter.Antialiasing)
        pie_layout.addWidget(self.pie_view)
        return self.pie_container

    def _build_dashboard_micro_chart_panel(self):
        self.bar_chart_micro = QChart()
        self.bar_series_micro = QBarSeries()
        self.bar_chart_micro.addSeries(self.bar_series_micro)
        self.bar_chart_micro.setTitle("Top 10 - Pend\u00eancias por Microbacia")
        self.bar_chart_micro.legend().setVisible(False)

        self.bar_axis_x_micro = QBarCategoryAxis()
        self.bar_axis_y_micro = QValueAxis()
        self.bar_chart_micro.addAxis(self.bar_axis_x_micro, Qt.AlignBottom)
        self.bar_chart_micro.addAxis(self.bar_axis_y_micro, Qt.AlignLeft)
        self.bar_series_micro.attachAxis(self.bar_axis_x_micro)
        self.bar_series_micro.attachAxis(self.bar_axis_y_micro)

        self.bar_container = QFrame()
        bar_layout = QVBoxLayout(self.bar_container)
        bar_layout.setContentsMargins(8, 8, 8, 8)
        self.bar_view_micro = QChartView(self.bar_chart_micro)
        self.bar_view_micro.setRenderHint(QPainter.Antialiasing)
        bar_layout.addWidget(self.bar_view_micro)
        return self.bar_container

    def _build_totals_group(self):
        totals_group = QGroupBox("Totais (Filtro Atual)")
        totals_layout = QHBoxLayout(totals_group)
        totals_layout.setContentsMargins(8, 10, 8, 8)
        totals_layout.setSpacing(8)

        self.kpi_table = QTableView()
        self.kpi_model = QStandardItemModel(0, 2)
        self.kpi_model.setHorizontalHeaderLabels(["M\u00e9trica", "Valor"])
        self.kpi_table.setModel(self.kpi_model)
        self.kpi_table.horizontalHeader().setStretchLastSection(True)
        self.kpi_table.setMinimumHeight(120)

        self.micro_table = QTableView()
        self.micro_model = QStandardItemModel(0, 2)
        self.micro_model.setHorizontalHeaderLabels(["Microbacia", "Pendente"])
        self.micro_table.setModel(self.micro_model)
        self.micro_table.horizontalHeader().setStretchLastSection(True)
        self.micro_table.setMinimumHeight(120)

        totals_layout.addWidget(self.kpi_table, 1)
        totals_layout.addWidget(self.micro_table, 1)

        # Mantem a area de Totais/Exportacao estavel apos sair da tela cheia.
        totals_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        totals_group.setMinimumHeight(180)
        totals_group.setMaximumHeight(260)
        return totals_group

    def _build_export_bar(self):
        export_widget = QWidget()
        export_widget.setObjectName("BarraExportacao")
        export_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        export_widget.setFixedHeight(46)

        export_bar = QHBoxLayout(export_widget)
        export_bar.setContentsMargins(0, 0, 0, 0)
        export_bar.setSpacing(8)

        self.btn_export_csv = QPushButton("Exportar CSV")
        self.btn_export_excel = QPushButton("Exportar Excel (2 abas)")
        self.btn_export_pdf = QPushButton("Exportar PDF")

        export_bar.addWidget(self.btn_export_csv)
        export_bar.addWidget(self.btn_export_excel)
        export_bar.addWidget(self.btn_export_pdf)
        export_bar.addStretch(1)
        return export_widget

    def _build_crud_buttons_layout(self):
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(8)

        self.btn_clear = QPushButton("Novo")
        self.btn_add = QPushButton("Adicionar")
        self.btn_save_edit = QPushButton("Salvar")
        self.btn_delete = QPushButton("Excluir")

        for button in [self.btn_clear, self.btn_add, self.btn_save_edit, self.btn_delete]:
            button.setMinimumHeight(30)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        buttons_layout.addWidget(self.btn_clear)
        buttons_layout.addWidget(self.btn_add)
        buttons_layout.addWidget(self.btn_save_edit)
        buttons_layout.addWidget(self.btn_delete)
        return buttons_layout

    def _build_map_group(self):
        map_group = QGroupBox("Mapa")
        map_layout = QGridLayout(map_group)
        map_layout.setContentsMargins(10, 10, 10, 10)
        map_layout.setHorizontalSpacing(8)
        map_layout.setVerticalSpacing(6)

        self.btn_maps = QPushButton("Pesquisar Endereço")
        self.btn_batch_geo = QPushButton("GPS em Lote")
        self.btn_map_full = QPushButton("Tela Cheia")

        self.chk_heatmap = QCheckBox("Mapa de Calor")
        self.combo_heatmap_type = QComboBox()
        self.combo_heatmap_type.addItems(["Pendentes", "Realizadas", "Tudo"])
        self.combo_heatmap_type.setMinimumWidth(150)

        for button in [self.btn_maps, self.btn_batch_geo, self.btn_map_full]:
            button.setMinimumHeight(30)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.chk_heatmap.setMinimumHeight(24)
        self.combo_heatmap_type.setMinimumHeight(28)

        map_layout.addWidget(self.btn_maps, 0, 0)
        map_layout.addWidget(self.btn_batch_geo, 0, 1)
        map_layout.addWidget(self.btn_map_full, 0, 2)
        map_layout.addWidget(self.chk_heatmap, 1, 0)
        map_layout.addWidget(self.combo_heatmap_type, 1, 1)
        map_layout.setColumnStretch(0, 1)
        map_layout.setColumnStretch(1, 1)
        map_layout.setColumnStretch(2, 1)
        return map_group

    def _apply_button_kind_properties(self):
        # Somente visual: organiza a hierarquia de acoes sem alterar comportamento.
        self.btn_open.setProperty("kind", "primary")
        self.btn_save_edit.setProperty("kind", "primary")
        self.btn_export_dashboard_pdf.setProperty("kind", "primary")

        self.btn_add.setProperty("kind", "success")
        self.btn_delete.setProperty("kind", "danger")

        for button in [
            self.btn_reload, self.btn_theme, self.btn_columns, self.btn_clear_filters,
            self.btn_reset_sort, self.btn_export_csv, self.btn_export_pdf, self.btn_export_excel,
            self.btn_maps, self.btn_batch_geo, self.btn_map_full, self.btn_table_full
        ]:
            button.setProperty("kind", "secondary")

    def _connect_main_signals(self):
        self.btn_open.clicked.connect(self.open_excel)
        self.btn_reload.clicked.connect(self.reload)

        self.search.textChanged.connect(self._agendar_filtro)
        self.filter_micro.currentTextChanged.connect(self.apply_filter)
        self.filter_eletronico.currentTextChanged.connect(self.apply_filter)
        self.filter_status.currentTextChanged.connect(self.apply_filter)

        self.btn_clear_filters.clicked.connect(self.clear_filters)
        self.btn_reset_sort.clicked.connect(self.reset_sorting)
        self.btn_columns.clicked.connect(self.open_columns_dialog)
        self.btn_table_full.clicked.connect(self.open_fullscreen_table)

        self.table.clicked.connect(self.on_table_click)

        self.btn_clear.clicked.connect(self.clear_form)
        self.btn_add.clicked.connect(self.add_new)
        self.btn_save_edit.clicked.connect(self.save_edit)
        self.btn_delete.clicked.connect(self.delete_selected)

        self.btn_maps.clicked.connect(self.search_on_map_by_address)
        self.in_end.returnPressed.connect(self.search_on_map_by_address)
        self.in_end.textChanged.connect(self._update_address_search_enabled)
        self.btn_map_full.clicked.connect(self.open_map_fullscreen)
        self.btn_batch_geo.clicked.connect(self.run_batch_geocode)

        self.chk_heatmap.stateChanged.connect(self.toggle_heatmap)
        self.combo_heatmap_type.currentTextChanged.connect(self.on_heatmap_type_changed)

        self.btn_export_csv.clicked.connect(self.export_csv_clicked)
        self.btn_export_excel.clicked.connect(self.export_excel_clicked)
        self.btn_export_pdf.clicked.connect(self.export_pdf_clicked)
        self.btn_export_dashboard_pdf.clicked.connect(self.export_dashboard_pdf_clicked)

        self.btn_theme.clicked.connect(self.toggle_theme)

    def _setup_shortcuts(self):
        act_open = QAction(self)
        act_open.setShortcut(QKeySequence("Ctrl+O"))
        act_open.triggered.connect(self.open_excel)
        self.addAction(act_open)

        act_reload = QAction(self)
        act_reload.setShortcut(QKeySequence("Ctrl+R"))
        act_reload.triggered.connect(self.reload)
        self.addAction(act_reload)

        act_focus = QAction(self)
        act_focus.setShortcut(QKeySequence("Ctrl+F"))
        act_focus.triggered.connect(lambda: self.search.setFocus())
        self.addAction(act_focus)

        act_new = QAction(self)
        act_new.setShortcut(QKeySequence("Ctrl+N"))
        act_new.triggered.connect(self.clear_form)
        self.addAction(act_new)

        act_save = QAction(self)
        act_save.setShortcut(QKeySequence("Ctrl+S"))
        act_save.triggered.connect(self.save_edit)
        self.addAction(act_save)

        act_del = QAction(self)
        act_del.setShortcut(QKeySequence(Qt.Key_Delete))
        act_del.triggered.connect(self.delete_selected)
        self.addAction(act_del)

    # ===== Helpers UI =====
    def _update_address_search_enabled(self):
        # Habilita o botÃ£o somente se:
        # 1) o campo de endereÃ§o estiver habilitado (app jÃ¡ carregou / nÃ£o estÃ¡ bloqueado)
        # 2) houver algum texto no endereÃ§o
        self.btn_maps.setEnabled(self.in_end.isEnabled() and bool(self.in_end.text().strip()))

    def _update_form_action_buttons(self):
        can_use_form = bool(self.excel.path) and self.in_oficio.isEnabled()
        has_selected = self.selected is not None
        self.btn_add.setEnabled(can_use_form)
        self.btn_save_edit.setEnabled(can_use_form and has_selected)
        self.btn_delete.setEnabled(can_use_form and has_selected)

    # ===== THEME =====
    def toggle_theme(self):
        self.is_dark_mode = not self.is_dark_mode
        self.settings.setValue("dark_mode", str(self.is_dark_mode).lower())
        self._apply_theme()
        self.populate_table(self.filtered_records)

    def _apply_theme(self):
        t = THEME_DARK if self.is_dark_mode else THEME_LIGHT

        qss = f"""
            /* ===== Base (vale para TODAS as janelas, inclusive QDialog) ===== */
            QWidget {{
                color: {t['text']};
            }}

            QMainWindow, QDialog {{
                background-color: {t['bg_main']};
                color: {t['text']};
                font-family: 'Segoe UI', Arial;
                font-size: 12px;
            }}

            QLabel {{ color: {t['text']}; }}
            QCheckBox, QRadioButton {{ color: {t['text']}; }}

            QGroupBox {{
                font-weight: 800;
                border: 1px solid {t['input_border']};
                border-radius: 10px;
                margin-top: 8px;
                padding-top: 10px;
                background: {t['bg_panel']};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 6px;
                color: {t['text']};
            }}

            QTabWidget::pane {{
                border: 1px solid {t['input_border']};
                background: {t['bg_panel']};
                border-radius: 10px;
            }}
            QTabBar::tab {{
                background: {t['tab_unsel']};
                color: {t['text']};
                padding: 7px 16px;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                margin-right: 4px;
            }}
            QTabBar::tab:selected {{
                background: {t['tab_sel']};
                font-weight: 800;
                border-bottom: 3px solid {t['btn_primary']};
            }}

            QLineEdit, QComboBox {{
                background-color: {t['input_bg']};
                border: 1px solid {t['input_border']};
                border-radius: 8px;
                padding: 5px 8px;
                color: {t['input_text']};
                min-height: 26px;
            }}
            QLineEdit::placeholder {{
                color: {t['placeholder']};
            }}
            QComboBox QAbstractItemView {{
                background-color: {t['input_bg']};
                color: {t['input_text']};
                selection-background-color: {t['btn_primary']};
                border: 1px solid {t['input_border']};
            }}

            QPushButton {{
                background-color: {t['bg_panel']};
                border: 1px solid {t['input_border']};
                border-radius: 8px;
                padding: 6px 10px;
                color: {t['text']};
                font-weight: 700;
                min-height: 30px;
            }}
            QPushButton:hover {{
                border: 1px solid {t['btn_primary']};
            }}
            QPushButton:pressed {{
                padding-top: 7px;
                padding-bottom: 5px;
            }}
            QPushButton:disabled {{
                color: {t['placeholder']};
                border-color: {t['input_border']};
            }}

            /* Hierarquia visual dos botÃµes */
            QPushButton[kind="primary"] {{
                background-color: {t['btn_primary']};
                color: {t['btn_text']};
                border: 1px solid {t['btn_primary']};
                font-weight: 900;
            }}
            QPushButton[kind="primary"]:hover {{
                background-color: {t['btn_primary_hover']};
                border: 1px solid {t['btn_primary_hover']};
            }}

            QPushButton[kind="success"] {{
                background-color: {t['btn_success']};
                color: #ffffff;
                border: 1px solid {t['btn_success']};
                font-weight: 900;
            }}
            QPushButton[kind="success"]:hover {{
                border: 1px solid {t['btn_primary']};
            }}

            QPushButton[kind="danger"] {{
                background-color: {t['btn_danger']};
                color: #ffffff;
                border: 1px solid {t['btn_danger']};
                font-weight: 900;
            }}
            QPushButton[kind="danger"]:hover {{
                border: 1px solid {t['btn_primary']};
            }}


            QPushButton[kind="secondary"] {{
                background-color: transparent;
                color: {t['text']};
                border: 1px solid {t['input_border']};
                font-weight: 700;
            }}
            QPushButton[kind="secondary"]:hover {{
                background-color: {t['table_alt']};
                border: 1px solid {t['btn_primary']};
            }}
            QPushButton[kind="secondary"]:pressed {{
                background-color: {t['table_header']};
            }}
            QTableView {{
                background-color: {t['input_bg']};
                alternate-background-color: {t['table_alt']};
                gridline-color: {t['input_border']};
                color: {t['text']};
                selection-background-color: {t['table_sel_bg']};
                selection-color: {t['table_sel_fg']};
                border-radius: 8px;
                border: 1px solid {t['input_border']};
            }}
            QTableView::item:selected {{
                background-color: {t['table_sel_bg']};
                color: {t['table_sel_fg']};
            }}
            QTableView::item:selected:active {{
                background-color: {t['table_sel_bg']};
            }}
            QTableView::item:selected {{
                background-color: {t['table_sel_bg']};
                color: {t['table_sel_fg']};
            }}
            QTableView::item:selected:active {{
                background-color: {t['table_sel_bg']};
            }}

            QHeaderView::section {{
                background-color: {t['table_header']};
                color: {t['text']};
                padding: 5px;
                border: 1px solid {t['input_border']};
                font-weight: 800;
            }}

            QSplitter::handle {{
                background: {t['splitter_handle']};
            }}

            /* ===== Menus/Popups (evita texto invisÃ­vel) ===== */
            QMenu {{
                background-color: {t['bg_panel']};
                color: {t['text']};
                border: 1px solid {t['input_border']};
            }}
            QMenu::item:selected {{
                background-color: {t['table_sel_bg']};
                color: {t['table_sel_fg']};
            }}
        """

        app = QApplication.instance()
        if app:
            app.setStyleSheet(qss)
        else:
            self.setStyleSheet(qss)

        for card in [self.card_total, self.card_pend, self.card_comp, self.card_records]:
            card.update_style(t)

        self._run_map_js(
            f"if(window.setTheme) window.setTheme('{'dark' if self.is_dark_mode else 'light'}');",
            "theme",
        )

    # ===== Settings (columns / sort / splitters) =====
    def _load_column_settings(self):
        raw = self.settings.value("columns_visible_json", "")
        if raw:
            try:
                data = json.loads(raw)
                self.columns_visible = {int(k): bool(v) for k, v in data.items()}
            except Exception as exc:
                print(f"[SETTINGS] Falha ao ler visibilidade de colunas: {exc}")

    def _save_column_settings(self):
        try:
            self.settings.setValue("columns_visible_json", json.dumps(self.columns_visible))
        except Exception as exc:
            print(f"[SETTINGS] Falha ao salvar visibilidade de colunas: {exc}")

    def _save_sort_settings(self):
        if self._is_reset_state:
            self.settings.setValue("sort_column", -1)
            self.settings.setValue("sort_order", int(Qt.AscendingOrder.value))
        else:
            sort_order = self.proxy.sortOrder()
            sort_order_value = getattr(sort_order, "value", sort_order)
            self.settings.setValue("sort_column", self.proxy.sortColumn())
            self.settings.setValue("sort_order", int(sort_order_value))

    def _load_sort_settings(self):
        col = int(self.settings.value("sort_column", -1))
        if col >= 0:
            self.proxy.sort(col, Qt.SortOrder(int(self.settings.value("sort_order", 0))))
            self.table.horizontalHeader().setSortIndicator(col, Qt.SortOrder(int(self.settings.value("sort_order", 0))))
        else:
            self.proxy.sort(-1)

    def _restore_window_preferences(self):
        try:
            geometry = self.settings.value("window_geometry")
            if geometry:
                self.restoreGeometry(geometry)
        except Exception as exc:
            print(f"[SETTINGS] Falha ao restaurar geometria da janela: {exc}")

        try:
            tab_index = int(self.settings.value("active_tab_index", 0))
            if 0 <= tab_index < self.tabs.count():
                self.tabs.setCurrentIndex(tab_index)
        except Exception as exc:
            print(f"[SETTINGS] Falha ao restaurar aba ativa: {exc}")

    def closeEvent(self, event):
        self._save_column_settings()
        self._save_sort_settings()
        try:
            self.settings.setValue("split_main", self.main_splitter.saveState())
        except Exception as exc:
            print(f"[SETTINGS] Falha ao salvar split_main: {exc}")
        try:
            self.settings.setValue("split_dash", self.dash_splitter.saveState())
        except Exception as exc:
            print(f"[SETTINGS] Falha ao salvar split_dash: {exc}")
        try:
            self.settings.setValue("window_geometry", self.saveGeometry())
        except Exception as exc:
            print(f"[SETTINGS] Falha ao salvar geometria da janela: {exc}")
        try:
            self.settings.setValue("active_tab_index", self.tabs.currentIndex())
        except Exception as exc:
            print(f"[SETTINGS] Falha ao salvar aba ativa: {exc}")
        super().closeEvent(event)

    def reset_sorting(self):
        self._is_reset_state = True
        self.proxy.sort(-1)
        self.table.clearSelection()
        self.settings.setValue("sort_column", -1)

    def _on_header_clicked(self, index):
        self._is_reset_state = False

    # ===== Map setup =====
    def save_map_layer_preference(self, layer_name):
        self.settings.setValue("map_layer", layer_name)

    def _setup_leaflet_map(self):
        path = resource_path(os.path.join("app", "ui", "map_leaflet.html"))
        if not os.path.exists(path):
            path = str(Path(__file__).resolve().parent / "map_leaflet.html")

        self.web.setPage(DebugPage(self.web))
        s = self.web.page().settings()
        s.setAttribute(QWebEngineSettings.PluginsEnabled, False)
        s.setAttribute(QWebEngineSettings.JavascriptCanOpenWindows, False)
        s.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
        s.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)

        self.web.setUrl(QUrl.fromLocalFile(str(path)))

        self.channel = QWebChannel(self.web.page())
        self.bridge = MapBridge(self._handle_map_click, self.save_map_layer_preference)
        self.channel.registerObject("bridge", self.bridge)
        self.web.page().setWebChannel(self.channel)

        def on_loaded(ok):
            if ok:
                self._apply_theme()
                if self.gis:
                    self._load_microbacias_layer()
                saved_layer = self.settings.value("map_layer", "Mapa Claro")
                self._run_map_js(f"if(window.setBaseLayer) window.setBaseLayer('{saved_layer}');", "base-layer")
            else:
                self._set_map_status("Falha ao carregar o HTML do mapa.")

        self.web.loadFinished.connect(on_loaded)

    def _run_map_js(self, script: str, context: str) -> bool:
        try:
            self.web.page().runJavaScript(script)
            return True
        except Exception as exc:
            print(f"[MAP JS] Falha em {context}: {exc}")
            return False

    def _set_map_status(self, msg: str):
        self._run_map_js(f"window.setStatus({json.dumps(msg)});", "status")

    def _set_map_marker(self, lat: float, lng: float):
        self._run_map_js(f"window.setMarker({lat}, {lng});", "marker")

    def _highlight_microbacia(self, micro_name: str):
        self._run_map_js(
            f"window.highlightGeoJsonByName({json.dumps(MICROB_NAME_FIELD)}, {json.dumps(micro_name)});",
            "highlight-microbacia",
        )

    def _handle_map_click(self, lat: float, lng: float):
        self.last_marker_coords = (lat, lng)

        if not self.gis:
            self._load_microbacias_layer()
            if not self.gis:
                self._set_map_status(f"Erro: Pasta {MICROB_DIR} n\u00e3o encontrada.")
                return

        micro = self.gis.find_microbacia(lat, lng)
        if micro:
            self.in_micro.setCurrentText(micro)
            self._highlight_microbacia(micro)
            self._set_map_status(f"Ponto dentro de: {micro}")
        else:
            self._set_map_status("Fora de microbacia conhecida.")

    def _get_planilha_panel(self) -> Tuple[Optional[QWidget], int]:
        """Retorna o widget do splitter principal que contÃ©m a â€œplanilhaâ€ e seu Ã­ndice.

        Isso evita inversÃ£o esquerda/direita caso o layout mude.
        """
        if hasattr(self, "table") and self.table is not None:
            for i in range(self.main_splitter.count()):
                w = self.main_splitter.widget(i)
                if w is not None and w.isAncestorOf(self.table):
                    return w, i

        # Fallback para versÃµes antigas que guardavam _left_panel
        w = getattr(self, "_left_panel", None)
        try:
            idx = self.main_splitter.indexOf(w) if w is not None else 0
        except Exception:
            idx = 0
        return w, idx

    def open_fullscreen_table(self):
        """Abre a Ã¡rea da planilha em tela cheia (mantÃ©m filtros/busca/exportaÃ§Ã£o via painel reutilizado)."""
        panel = None
        try:
            if self._table_fs_dialog is not None:
                try:
                    if self._table_fs_dialog.isVisible():
                        self._table_fs_dialog.activateWindow()
                        self._table_fs_dialog.raise_()
                        return
                except Exception as exc:
                    print(f"[FS TABLE] Falha ao reativar dialogo existente: {exc}")
                self._table_fs_dialog = None

            panel, idx = self._get_planilha_panel()
            if panel is None:
                return

            self._table_fs_index = idx

            try:
                self._table_fs_split_state = self.main_splitter.saveState()
            except Exception:
                self._table_fs_split_state = None

            try:
                self._table_fs_split_sizes = self.main_splitter.sizes()
            except Exception:
                self._table_fs_split_sizes = None

            if self._table_fs_placeholder is None:
                self._table_fs_placeholder = QWidget()
                self._table_fs_placeholder.setObjectName("PlaceholderPlanilha")
                self._table_fs_placeholder.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

            try:
                self.main_splitter.replaceWidget(idx, self._table_fs_placeholder)
            except Exception:
                try:
                    panel.setParent(None)
                except Exception as exc:
                    print(f"[FS TABLE] Falha ao soltar painel do splitter: {exc}")
                try:
                    self.main_splitter.insertWidget(idx, self._table_fs_placeholder)
                except Exception as exc:
                    print(f"[FS TABLE] Falha ao inserir placeholder no splitter: {exc}")

            dlg = TableFullScreenDialog(self, panel, self._restore_table_panel)
            self._table_fs_dialog = dlg
            dlg.showMaximized()
            try:
                dlg.activateWindow()
                dlg.raise_()
            except Exception as exc:
                print(f"[FS TABLE] Falha ao trazer dialogo para frente: {exc}")

        except Exception as e:
            try:
                if panel is not None:
                    self._restore_table_panel(panel)
            except Exception as restore_exc:
                print(f"[FS TABLE] Falha ao restaurar painel apos erro: {restore_exc}")
            QMessageBox.critical(self, "Erro", f"Falha ao abrir tela cheia da planilha:\n{e}")

    def _restore_table_panel(self, panel_widget: QWidget):
        """Restaura o painel da planilha no mesmo Ã­ndice do splitter, sem inverter lados."""
        if panel_widget is None:
            return

        # Ãndice original antes de abrir a tela cheia
        try:
            idx = int(getattr(self, "_table_fs_index", 0))
        except Exception:
            idx = 0

        # Garante Ã­ndice vÃ¡lido
        try:
            count = self.main_splitter.count()
            if idx < 0:
                idx = 0
            if idx >= count:
                idx = max(0, count - 1)
        except Exception as exc:
            print(f"[FS TABLE] Falha ao normalizar indice do splitter: {exc}")

        # IMPORTANTE: nÃ£o remover o placeholder antes de substituir
        try:
            try:
                self.main_splitter.replaceWidget(idx, panel_widget)
            except Exception:
                # Fallback: tenta inserir no Ã­ndice (mantendo a ordem)
                panel_widget.setParent(self.main_splitter)
                self.main_splitter.insertWidget(idx, panel_widget)
        except Exception as exc:
            print(f"[FS TABLE] Falha ao recolocar painel no splitter: {exc}")

        # Agora sim, remove o placeholder (se existir)
        try:
            if self._table_fs_placeholder is not None:
                self._table_fs_placeholder.setParent(None)
        except Exception as exc:
            print(f"[FS TABLE] Falha ao remover placeholder temporario: {exc}")

        # Restaura tamanhos/estado do splitter
        try:
            if self._table_fs_split_state is not None:
                self.main_splitter.restoreState(self._table_fs_split_state)
        except Exception as exc:
            print(f"[FS TABLE] Falha ao restaurar estado do splitter: {exc}")

        # ==========================================================
        # CORREÃ‡ÃƒO: Zerar a PolÃ­tica de Tamanho da Tabela
        # ==========================================================
        try:
            # 1. Guardamos a polÃ­tica original de redimensionamento da tabela
            politica_antiga = self.table.sizePolicy()

            # 2. ForÃ§amos a tabela a ignorar qualquer tamanho em cache (fazendo-a encolher)
            from PySide6.QtWidgets import QSizePolicy
            self.table.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)

            def _restaurar_tamanho_tabela():
                # 3. Devolvemos a capacidade da tabela de se expandir normalmente
                self.table.setSizePolicy(politica_antiga)

                # 4. Reaplicamos as larguras exatas do painel esquerdo/direito
                if getattr(self, '_table_fs_split_sizes', None):
                    self.main_splitter.setSizes(self._table_fs_split_sizes)

            # Damos 50 milissegundos para o layout "puxar" os botÃµes para cima
            QTimer.singleShot(50, _restaurar_tamanho_tabela)
        except Exception as exc:
            print(f"[FS TABLE] Falha ao restaurar layout da tabela: {exc}")

        self._table_fs_dialog = None

    def open_map_fullscreen(self):
        path = resource_path(os.path.join("app", "ui", "map_leaflet.html"))
        if not os.path.exists(path):
            path = str(Path(__file__).resolve().parent / "map_leaflet.html")

        geojson = self.gis.to_geojson_obj() if self.gis else None
        theme = "dark" if self.is_dark_mode else "light"
        layer = self.settings.value("map_layer", "Mapa Claro")
        pts = self._get_current_heatmap_points()

        dlg = MapFullScreenDialog(self, path, geojson, theme, self.last_marker_coords, self.gis, layer, pts)
        dlg.exec()

    # ===== Geocode =====
    def geocode_address(self, address: str) -> Optional[Tuple[float, float]]:
        return geocode_address_arcgis(address)

    def _show_geocode_not_found(self):
        self._set_map_status("Endereço não encontrado.")
        self.statusBar().showMessage("Endereço não encontrado")
        QMessageBox.warning(self, "Não encontrado", "Não consegui localizar esse endereço.")

    def _apply_geocode_result(self, lat: float, lng: float) -> str:
        self.last_marker_coords = (lat, lng)
        self._set_map_marker(lat, lng)

        micro = ""
        if self.gis:
            micro = self.gis.find_microbacia(lat, lng)

        if self.selected:
            updated_record = replace(
                self.selected,
                latitude=str(lat),
                longitude=str(lng),
                microbacia=micro or self.selected.microbacia,
            )
            try:
                self.excel.save_edit(updated_record)
            except Exception as exc:
                self._set_map_status("Endereço localizado, mas não foi possível salvar no Excel.")
                self.statusBar().showMessage("Endereço localizado, mas houve falha ao salvar.")
                QMessageBox.critical(
                    self,
                    "Erro de salvamento",
                    f"Não foi possível salvar a localização encontrada:\n{exc}",
                )
                return micro
            self.selected.latitude = updated_record.latitude
            self.selected.longitude = updated_record.longitude
            self.selected.microbacia = updated_record.microbacia
            self._mark_metrics_dirty()
            self._mark_heatmap_dirty()

        if micro:
            self.in_micro.setCurrentText(micro)
            self._highlight_microbacia(micro)
            self._set_map_status(f"Endereço localizado. Microbacia: {micro}")
            self.statusBar().showMessage(f"Endereço localizado. Microbacia: {micro}")
        else:
            self._set_map_status("Endereço localizado, mas microbacia não detectada.")
            self.statusBar().showMessage("Endereço localizado (microbacia não detectada)")

        return micro

    def search_on_map_by_address(self):
        addr = self.in_end.text().strip()
        if not addr:
            QMessageBox.warning(self, "Atenção", "Digite um endereço para pesquisar.")
            return

        self._set_map_status("Pesquisando endere\u00e7o...")
        self.statusBar().showMessage("Pesquisando endere\u00e7o...")
        result = self.geocode_address(addr)
        if not result:
            self._show_geocode_not_found()
            return

        lat, lng = result
        self._apply_geocode_result(lat, lng)

    # ===== Enable/Disable =====
    def _set_enabled_all(self, enabled: bool):
        widgets = [
            self.btn_reload, self.search, self.filter_micro, self.filter_eletronico,
            self.filter_status, self.btn_clear_filters,
            self.btn_reset_sort, self.btn_columns, self.table, self.in_oficio,
            self.eletronico_container, self.in_caixa, self.in_avtec, self.in_comp,
            self.in_end, self.in_micro, self.chk_compensado, self.btn_clear,
            self.btn_add, self.btn_save_edit, self.btn_delete, self.btn_maps,
            self.btn_map_full, self.btn_batch_geo, self.chk_heatmap, self.btn_export_csv,
            self.btn_export_excel, self.btn_export_pdf, self.btn_export_dashboard_pdf,
            self.btn_theme, self.combo_heatmap_type
        ]
        for w in widgets:
            w.setEnabled(enabled)
        for btn in self.eletronico_group.buttons():
            btn.setEnabled(enabled)
        self._update_address_search_enabled()
        self._update_form_action_buttons()

    # ===== Filters =====
    def clear_filters(self):
        """Limpa apenas os filtros aplicados, sem apagar a lista de itens."""
        self.search.setText("")
        self.filter_status.setCurrentText("Todos")
        self.filter_micro.select_all()
        self.filter_eletronico.select_all()
        self.apply_filter()
        self.statusBar().showMessage("Filtros limpos")

    def clear_sorting(self):
        """Remove ordenaÃ§Ã£o da tabela (volta ao estado 'sem ordenaÃ§Ã£o')."""
        self._is_reset_state = True
        try:
            # -1 remove ordenaÃ§Ã£o no proxy
            self.proxy.sort(-1)
            self.table.horizontalHeader().setSortIndicatorShown(False)
        finally:
            self._save_sort_settings()
            self._is_reset_state = False

    def _unique_non_empty(self, values: List[str]) -> List[str]:
        return unique_non_empty(values)

    def _row_is_compensado(self, c: Compensacao) -> bool:
        return row_is_compensado(c)

    def _to_float(self, v) -> float:
        return to_float(v)

    def _compute_metrics(self, records: List[Compensacao]) -> Dict[str, object]:
        return compute_metrics(records)

    def _mark_metrics_dirty(self):
        self._all_metrics_cache = None
        self._filtered_metrics_cache = None

    def _mark_heatmap_dirty(self):
        self._heatmap_revision += 1
        self._heatmap_cache_signature = None
        self._heatmap_points_cache = None

    def _get_all_metrics(self) -> Dict[str, object]:
        if self._all_metrics_cache is None:
            self._all_metrics_cache = self._compute_metrics(self.records)
        return self._all_metrics_cache

    def _get_filtered_metrics(self) -> Dict[str, object]:
        if self._filtered_metrics_cache is None:
            self._filtered_metrics_cache = self._compute_metrics(self.filtered_records)
        return self._filtered_metrics_cache

    def _update_filters_from_records(self):
        micros = self._unique_non_empty([r.microbacia for r in self.records])
        eles = self._unique_non_empty([r.eletronico for r in self.records])
        self.filter_micro.set_items(micros)
        self.filter_eletronico.set_items(eles)

    def _setup_dynamic_form_options_from_records(self):
        micros = self._unique_non_empty([r.microbacia for r in self.records])
        cur_micro = self.in_micro.currentText().strip()
        self.in_micro.clear()
        self.in_micro.addItem("")
        for m in micros:
            self.in_micro.addItem(m)
        if cur_micro:
            self.in_micro.setCurrentText(cur_micro)

        opcoes = self._unique_non_empty([r.eletronico for r in self.records])

        for btn in self.eletronico_group.buttons():
            self.eletronico_group.removeButton(btn)
            btn.deleteLater()

        while self.eletronico_layout.count():
            item = self.eletronico_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        if not opcoes:
            opcoes = ["SIM", "N\u00c3O"]

        for opt in opcoes:
            rb = QRadioButton(opt)
            rb.setMinimumHeight(24)
            rb.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            self.eletronico_group.addButton(rb)
            self.eletronico_layout.addWidget(rb)

        self.eletronico_layout.addStretch(1)

    # ===== Columns =====
    def _apply_columns_visibility(self, resize: bool = False):
        self.table.setUpdatesEnabled(False)
        for i in range(len(COLS)):
            visible = self.columns_visible.get(i, True)
            self.table.setColumnHidden(i, not visible)
        if resize:
            self._auto_resize_columns()
            self._did_initial_resize = True
        self.table.setUpdatesEnabled(True)

    def _auto_resize_columns(self):
        # Auto ajuste inicial (evita â€œtremorâ€ durante filtros)
        self.table.resizeColumnsToContents()

        # EndereÃ§o costuma precisar de mais espaÃ§o
        if not self.table.isColumnHidden(5):
            self.table.setColumnWidth(5, max(self.table.columnWidth(5), 320))

        # Microbacia tambÃ©m costuma cortar
        if not self.table.isColumnHidden(6):
            self.table.setColumnWidth(6, max(self.table.columnWidth(6), 200))

    def _auto_resize_totals_tables(self):
        self.kpi_table.resizeColumnsToContents()
        self.micro_table.resizeColumnsToContents()
        # NÃ£o deixar encolher demais apÃ³s atualizar/limpar filtros
        self.kpi_table.setColumnWidth(0, max(self.kpi_table.columnWidth(0), 160))
        self.kpi_table.setColumnWidth(1, max(self.kpi_table.columnWidth(1), 140))

        self.micro_table.setColumnWidth(0, max(self.micro_table.columnWidth(0), 200))
        self.micro_table.setColumnWidth(1, max(self.micro_table.columnWidth(1), 140))

    def open_columns_dialog(self):
        dlg = ColumnsDialog(self, self.columns_visible)
        if dlg.exec():
            self.columns_visible = dlg.result_map()
            self._apply_columns_visibility(resize=True)
            self._save_column_settings()

    def _selected_export_attrs(self) -> List[str]:
        selected_attrs = []
        for idx, (_, attr) in enumerate(ALL_COLUMNS):
            if self.columns_visible.get(idx, True):
                selected_attrs.append(attr)
        if not selected_attrs:
            selected_attrs = ["av_tec", "compensacao"]
        return selected_attrs

    def _compensado_badge_palette(self) -> Tuple[QColor, QColor, QColor, QColor]:
        if self.is_dark_mode:
            return (
                QColor("#1f6f3a"),
                QColor("#eafff1"),
                QColor("#3a3f4c"),
                QColor("#e9e9ea"),
            )
        return (
            QColor("#c6efce"),
            QColor("#1d4b2a"),
            QColor("#e9edf3"),
            QColor("#1f2328"),
        )

    def _build_table_row_items(
        self,
        record: Compensacao,
        badge_palette: Tuple[QColor, QColor, QColor, QColor],
    ) -> List[QStandardItem]:
        badge_bg_ok, badge_fg_ok, badge_bg_no, badge_fg_no = badge_palette

        it_comp = QStandardItem("" if record.compensacao is None else str(record.compensacao))
        it_comp.setData(self._to_float(record.compensacao), Qt.UserRole)

        it_compensado = QStandardItem(record.compensado)
        if self._row_is_compensado(record):
            it_compensado.setText("SIM")
            it_compensado.setBackground(badge_bg_ok)
            it_compensado.setForeground(badge_fg_ok)
        else:
            it_compensado.setText("" if not str(record.compensado or "").strip() else str(record.compensado))
            it_compensado.setBackground(badge_bg_no)
            it_compensado.setForeground(badge_fg_no)

        items = [
            QStandardItem(record.oficio_processo),
            QStandardItem(record.eletronico),
            QStandardItem(record.caixa),
            QStandardItem(record.av_tec),
            it_comp,
            QStandardItem(record.endereco),
            QStandardItem(record.microbacia),
            it_compensado,
        ]
        items[0].setData(record.excel_row, Qt.UserRole)

        lat = getattr(record, "latitude", "")
        lon = getattr(record, "longitude", "")
        if str(lat).strip() and str(lon).strip():
            tip = f"Lat/Lon: {lat}, {lon}"
            for item in items:
                item.setToolTip(tip)

        return items

    # ===== Table + Totals =====
    def populate_table(self, records: List[Compensacao]):
        self.table.setUpdatesEnabled(False)
        self.model.setRowCount(0)

        badge_palette = self._compensado_badge_palette()
        for row in [self._build_table_row_items(record, badge_palette) for record in records]:
            self.model.appendRow(row)

        # NÃƒO chamar resizeColumnsToContents a cada filtro (evita tremor)
        self._apply_columns_visibility(resize=not self._did_initial_resize)
        self.table.setUpdatesEnabled(True)

    def _update_totals_tables(self):
        m = self._get_filtered_metrics()

        self.kpi_model.setRowCount(0)
        rows = [
            ("Total geral", m["total_geral"]),
            ("Pendente", m["total_pendente"]),
            ("Compensado", m["total_compensado"])
        ]
        for k, v in rows:
            self.kpi_model.appendRow([QStandardItem(k), QStandardItem(f"{v:g}")])

        self.micro_model.setRowCount(0)
        for micro, tot in m["pend_micro_sorted"]:
            self.micro_model.appendRow([QStandardItem(micro), QStandardItem(f"{tot:g}")])

        self._auto_resize_totals_tables()

    # ===== Dashboard =====
    def _fill_bar(self, series, axis_x, axis_y, data):
        series.clear()
        axis_x.clear()

        cats = [k for k, _ in data]
        vals = [v for _, v in data]

        barset = QBarSet("Pendente")
        barset.setColor(QColor("#F44336"))

        for v in vals:
            barset.append(v)

        series.append(barset)
        axis_x.append(cats)

        maxv = max(vals) if vals else 0
        axis_y.setRange(0, max(1, maxv * 1.1))
        series.attachAxis(axis_x)
        series.attachAxis(axis_y)

    def _update_dashboard(self):
        m = self._get_all_metrics()

        self.card_total.update_value(f"{m['total_geral']:,.0f}".replace(",", "."))
        self.card_pend.update_value(f"{m['total_pendente']:,.0f}".replace(",", "."))
        self.card_comp.update_value(f"{m['total_compensado']:,.0f}".replace(",", "."))
        self.card_records.update_value(f"{m['count_total']}")

        self.pie_series.clear()
        if m["total_pendente"] == 0 and m["total_compensado"] == 0:
            self.pie_series.append("Sem dados", 1).setColor(QColor("#ddd"))
        else:
            s_pend = self.pie_series.append("Pendente", m["total_pendente"])
            s_pend.setColor(QColor("#F44336"))
            s_pend.setLabelVisible(True)
            s_comp = self.pie_series.append("Compensado", m["total_compensado"])
            s_comp.setColor(QColor("#4CAF50"))
            s_comp.setLabelVisible(True)

        self._fill_bar(self.bar_series_micro, self.bar_axis_x_micro, self.bar_axis_y_micro, m["pend_micro_sorted"][:10])

    # ===== Export =====
    def _show_export_success(self):
        QMessageBox.information(self, "Sucesso", "Exportado com sucesso.")

    def _get_save_path(self, title: str, file_filter: str) -> str:
        path, _ = QFileDialog.getSaveFileName(self, title, "", file_filter)
        return path

    def _run_export(self, action):
        try:
            action()
        except Exception as exc:
            QMessageBox.critical(self, "Erro de exportação", f"Falha ao exportar:\n{exc}")
            return False
        self._show_export_success()
        return True

    def _export_dashboard_images(self, temp_dir: str) -> tuple[str, str]:
        pie = os.path.join(temp_dir, "p.png")
        bar = os.path.join(temp_dir, "b.png")
        self.pie_view.grab().save(pie)
        self.bar_view_micro.grab().save(bar)
        return pie, bar

    def _current_filters_summary(self) -> str:
        parts = []

        search_text = self.search.text().strip()
        if search_text:
            parts.append(f"Busca: {search_text}")

        status = self.filter_status.currentText().strip()
        if status and status != "Todos":
            parts.append(f"Status: {status}")

        selected_micros = self.filter_micro.checked_items()
        if selected_micros and not self.filter_micro.is_all_selected():
            parts.append(f"Microbacias: {', '.join(selected_micros)}")

        selected_eletronicos = self.filter_eletronico.checked_items()
        if selected_eletronicos and not self.filter_eletronico.is_all_selected():
            parts.append(f"Eletrônico: {', '.join(selected_eletronicos)}")

        return " | ".join(parts) if parts else "Sem filtros"

    def export_csv_clicked(self):
        if not self.records:
            return
        path = self._get_save_path("Salvar CSV", "CSV (*.csv)")
        if path:
            self._run_export(
                lambda: export_csv(path, self.filtered_records, self._selected_export_attrs())
            )

    def export_excel_clicked(self):
        if not self.records:
            return
        path = self._get_save_path("Salvar Excel", "Excel (*.xlsx)")
        if path:
            m = self._get_filtered_metrics()
            filtros_txt = self._current_filters_summary()
            kpis = [
                ("Total", m["total_geral"]),
                ("Pendente", m["total_pendente"]),
                ("Compensado", m["total_compensado"]),
            ]
            self._run_export(
                lambda: export_excel_two_sheets(
                    path,
                    self.filtered_records,
                    filtros_txt,
                    self._selected_export_attrs(),
                    kpis,
                    m["pend_micro_sorted"],
                    m["pend_ele_sorted"],
                )
            )

    def export_pdf_clicked(self):
        if not self.records:
            return
        path = self._get_save_path("Salvar PDF", "PDF (*.pdf)")
        if path:
            m = self._get_filtered_metrics()
            filtros_txt = self._current_filters_summary()
            kpis = [("Total", m["total_geral"]), ("Pendente", m["total_pendente"])]
            self._run_export(
                lambda: export_pdf(
                    path,
                    self.filtered_records,
                    filtros_txt,
                    self._selected_export_attrs(),
                    kpis,
                    m["pend_micro_sorted"],
                )
            )

    def export_dashboard_pdf_clicked(self):
        if not self.records:
            return
        path = self._get_save_path("Salvar PDF", "PDF (*.pdf)")
        if path:
            m = self._get_all_metrics()
            filtros_txt = self._current_filters_summary()
            def action():
                with tempfile.TemporaryDirectory() as temp_dir:
                    pie, bar = self._export_dashboard_images(temp_dir)
                    export_dashboard_pdf(
                        path,
                        "Painel",
                        [
                            f"Total: {m['total_geral']}",
                            f"Pendente: {m['total_pendente']}",
                            f"Compensado: {m['total_compensado']}",
                        ],
                        filtros_txt,
                        [pie, bar],
                    )

            self._run_export(action)

    # ===== Form CRUD =====
    def clear_form(self):
        self.selected = None
        for w in [self.in_oficio, self.in_caixa, self.in_avtec, self.in_comp, self.in_end]:
            w.clear()
        self.in_micro.setCurrentText("")
        self.chk_compensado.setChecked(False)
        for b in self.eletronico_group.buttons():
            b.setChecked(False)
        self.table.clearSelection()
        self._update_form_action_buttons()
        self.in_oficio.setFocus()
        self.statusBar().showMessage("Novo registro")

    def fill_form(self, c: Compensacao):
        self.in_oficio.setText(c.oficio_processo)
        self.in_caixa.setText(c.caixa)
        self.in_avtec.setText(c.av_tec)
        self.in_comp.setText("" if c.compensacao is None else str(c.compensacao))
        self.in_end.setText(c.endereco)
        self.in_micro.setCurrentText(c.microbacia)
        self.chk_compensado.setChecked(safe_upper(c.compensado) == "SIM")

        target = safe_upper(c.eletronico)
        found = False
        for btn in self.eletronico_group.buttons():
            if safe_upper(btn.text()) == target and target:
                btn.setChecked(True)
                found = True
                break
        if not found:
            for btn in self.eletronico_group.buttons():
                btn.setChecked(False)

        self._update_address_search_enabled()
        self._update_form_action_buttons()

    def _read_form(self) -> Compensacao:
        ele = ""
        btn = self.eletronico_group.checkedButton()
        if btn:
            ele = btn.text().strip()

        return Compensacao(
            excel_row=self.selected.excel_row if self.selected else -1,
            oficio_processo=self.in_oficio.text().strip(),
            eletronico=ele,
            caixa=self.in_caixa.text().strip(),
            av_tec=self.in_avtec.text().strip(),
            compensacao=self.in_comp.text().strip(),
            endereco=self.in_end.text().strip(),
            microbacia=self.in_micro.currentText().strip(),
            compensado="SIM" if self.chk_compensado.isChecked() else "",
            latitude=self.selected.latitude if self.selected else "",
            longitude=self.selected.longitude if self.selected else ""
        )

    def add_new(self):
        if not self.excel.path:
            return
        c = self._read_form()
        err = validate_compensacao(c)
        if err:
            QMessageBox.warning(self, "Erro", err)
            return
        self.excel.add_new(c)
        self.reload()
        self.clear_form()
        QMessageBox.information(self, "Sucesso", "Adicionado com sucesso.")

    def save_edit(self):
        if not self.excel.path or not self.selected:
            return
        c = self._read_form()
        err = validate_compensacao(c)
        if err:
            QMessageBox.warning(self, "Erro", err)
            return
        self.excel.save_edit(c)
        self.reload()
        QMessageBox.information(self, "Sucesso", "Salvo com sucesso.")

    def delete_selected(self):
        if not self.excel.path or not self.selected:
            return
        if QMessageBox.question(self, "Excluir", "Confirma a exclus\u00e3o?") == QMessageBox.Yes:
            self.excel.delete_record_shift_up(self.selected.excel_row)
            self.reload()
            self.clear_form()

    def _load_excel_records(self, path: str, *, persist_last_path: bool, status_prefix: str):
        self.records = self.excel.load(path)
        self._reindex_records()
        self._mark_metrics_dirty()
        self._mark_heatmap_dirty()
        if persist_last_path:
            self.settings.setValue("last_excel_path", path)

        gc.collect()

        self._setup_dynamic_form_options_from_records()
        self._update_filters_from_records()
        self._load_microbacias_layer()

        self.apply_filter()
        self._update_dashboard()
        self._set_enabled_all(True)
        self._apply_columns_visibility(resize=True)
        self.statusBar().showMessage(f"{status_prefix}: {len(self.records)} registros.")

    def open_excel(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Abrir Excel",
            "",
            "Excel (*.xlsx)"
        )

        if not path:
            return

        try:
            self._load_excel_records(path, persist_last_path=True, status_prefix="Carregado")
            QMessageBox.information(self, "Sucesso", f"Carregado: {len(self.records)} registros.")
        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Falha ao abrir a planilha:\n{str(e)}")

    def _load_last_excel(self):
        path = self.settings.value("last_excel_path", "")
        if path and os.path.exists(path):
            try:
                self._load_excel_records(path, persist_last_path=False, status_prefix="Carregado")
            except Exception as exc:
                self.settings.remove("last_excel_path")
                self.statusBar().showMessage(f"Falha ao carregar a última planilha: {exc}")
                QTimer.singleShot(
                    0,
                    lambda exc=exc: QMessageBox.warning(
                        self,
                        "Falha ao carregar última planilha",
                        f"Não foi possível reabrir a última planilha usada:\n{exc}",
                    ),
                )

    def reload(self):
        if not self.excel.path:
            return
        try:
            self._load_excel_records(self.excel.path, persist_last_path=False, status_prefix="Recarregado")
        except Exception as e:
            QMessageBox.critical(self, "Erro", str(e))

    # ===== GIS layer =====
    def _load_microbacias_layer(self):
        if not os.path.isdir(MICROB_DIR):
            self.gis = None
            print(f"[GIS] Pasta de microbacias n\u00e3o encontrada: {MICROB_DIR}")
            # opcional (bem Ãºtil no exe):
            # QMessageBox.warning(self, "GIS", f"Pasta de microbacias nÃ£o encontrada:\n{MICROB_DIR}")
            return
        try:
            if not self.gis:
                self.gis = GisService(MICROB_DIR, MICROB_NAME_FIELD)
            geojson_obj = self.gis.to_geojson_obj()
            self._run_map_js(
                f"if(window.setMicrobacias) window.setMicrobacias({json.dumps(geojson_obj)});",
                "microbacias-layer",
            )
        except Exception as e:
            self.gis = None
            print(f"Erro GIS: {e}")

    # ===== Filtering =====
    def _agendar_filtro(self):
        # Reinicia o timer a cada digitaÃ§Ã£o; o filtro roda sÃ³ quando o usuÃ¡rio parar
        self._timer_filtro.start()

    def _filter_records(self) -> List[Compensacao]:
        return filter_records(
            self.records,
            text=self.search.text(),
            status=self.filter_status.currentText().strip(),
            selected_micros=self.filter_micro.checked_items(),
            selected_eletronicos=self.filter_eletronico.checked_items(),
            micro_all_selected=self.filter_micro.is_all_selected(),
            eletronico_all_selected=self.filter_eletronico.is_all_selected(),
        )

    def _apply_filtered_records(self, filtered: List[Compensacao]):
        self.filtered_records = filtered
        self._filtered_metrics_cache = self._compute_metrics(filtered)
        self._mark_heatmap_dirty()
        self.populate_table(filtered)
        self._update_totals_tables()
        self.toggle_heatmap()
        self.lbl_results.setText("Nenhum registro" if not filtered else f"{len(filtered)} registros")
        self.statusBar().showMessage(f"Filtro aplicado: {len(filtered)} registros")

    def apply_filter(self):
        filtered = self._filter_records()
        self._apply_filtered_records(filtered)

    def _reindex_records(self):
        self.records_by_excel_row = {r.excel_row: r for r in self.records}

    def _get_record_by_excel_row(self, excel_row: int) -> Optional[Compensacao]:
        record = self.records_by_excel_row.get(excel_row)
        if record is not None:
            return record

        if self.records:
            self._reindex_records()
            return self.records_by_excel_row.get(excel_row)
        return None

    def _select_record_from_proxy_index(self, proxy_index):
        if not proxy_index or not proxy_index.isValid():
            return
        src_index = self.proxy.mapToSource(proxy_index)
        if not src_index.isValid():
            return
        item = self.model.item(src_index.row(), 0)
        if item is None:
            return
        excel_row = item.data(Qt.UserRole)
        self.selected = self._get_record_by_excel_row(excel_row)
        if self.selected:
            self.fill_form(self.selected)

    def _on_current_row_changed(self, current, previous):
        self._select_record_from_proxy_index(current)

    def on_table_click(self, proxy_index):
        self._select_record_from_proxy_index(proxy_index)

    # ===== Heatmap =====
    def on_heatmap_type_changed(self, text):
        self.toggle_heatmap()

    def _get_current_heatmap_points(self):
        signature = (
            self._heatmap_revision,
            self.chk_heatmap.isChecked(),
            self.combo_heatmap_type.currentText(),
        )
        if signature == self._heatmap_cache_signature and self._heatmap_points_cache is not None:
            return [point[:] for point in self._heatmap_points_cache]

        if not self.chk_heatmap.isChecked():
            self._heatmap_cache_signature = signature
            self._heatmap_points_cache = []
            return []
        mode = self.combo_heatmap_type.currentText()

        points = []
        pend_micro_fallback = {}

        for r in self.filtered_records:
            is_comp = str(r.compensado).strip().upper() == "SIM"
            if mode == "Pendentes" and is_comp:
                continue
            if mode == "Realizadas" and not is_comp:
                continue

            val = self._to_float(r.compensacao)

            if getattr(r, "latitude", "") and getattr(r, "longitude", ""):
                try:
                    points.append([float(r.latitude), float(r.longitude), 1.0])
                except (TypeError, ValueError):
                    continue
            else:
                m = (r.microbacia or "").strip()
                if m:
                    pend_micro_fallback[m] = pend_micro_fallback.get(m, 0.0) + val

        if self.gis and pend_micro_fallback:
            max_val = max(pend_micro_fallback.values()) if pend_micro_fallback else 1
            for m, val in pend_micro_fallback.items():
                c = self.gis.get_microbacia_centroid(m)
                if c:
                    points.append([c[0], c[1], val / max_val])

        self._heatmap_cache_signature = signature
        self._heatmap_points_cache = [point[:] for point in points]
        return [point[:] for point in points]

    def toggle_heatmap(self):
        if not self.gis:
            return
        pts = self._get_current_heatmap_points()
        self._run_map_js(f"if(window.setHeatmap) window.setHeatmap({json.dumps(pts)});", "heatmap")

    # ===== Batch geocode =====
    def _pending_geocode_records(self) -> List[Compensacao]:
        return [
            r for r in self.records
            if (r.endereco or "").strip() and (
                not getattr(r, "latitude", "") or
                not getattr(r, "longitude", "") or
                not str(getattr(r, "microbacia", "") or "").strip()
            )
        ]

    def _start_batch_geocode(self, records_to_process: List[Compensacao]):
        self.progress = QProgressDialog("Processando...", "Cancelar", 0, len(records_to_process), self)
        self.progress.setWindowTitle("Georreferenciamento")
        self.progress.setMinimumDuration(0)

        self.geo_worker = GeocodeWorker(records_to_process)
        self.progress.canceled.connect(self._cancel_batch_geocode)
        self.geo_worker.progress_update.connect(
            lambda i, t: (self.progress.setValue(i), self.progress.setLabelText(t))
        )
        self.geo_worker.finished_process.connect(self.on_geocode_finished)
        self.geo_worker.start()

    def run_batch_geocode(self):
        if not self.excel.path:
            return

        to_process = self._pending_geocode_records()
        if not to_process:
            QMessageBox.information(self, "Sucesso", "Tudo georreferenciado e com microbacias preenchidas!")
            return

        if QMessageBox.question(self, "Lote",
                                f"Georreferenciar {len(to_process)} endereços pendentes?") == QMessageBox.Yes:
            self._start_batch_geocode(to_process)

    def _cancel_batch_geocode(self):
        if self.geo_worker:
            self.geo_worker.stop()
        if hasattr(self, "progress") and self.progress:
            self.progress.setLabelText("Cancelando...")

    def on_geocode_result(self, excel_row: int, lat: float, lon: float):
        # 1. Pega o registro original usando o nÃºmero da linha que veio do trabalhador
        orig = self._get_record_by_excel_row(excel_row)
        if not orig:
            return

        micro_finder = self.gis.find_microbacia if self.gis else None
        apply_geocode_to_record(orig, lat, lon, micro_finder)

        # 4. Salva imediatamente a linha no Excel (MÃ©todo blindado)
        try:
            self.excel.save_edit(orig)
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Erro de salvamento", f"Falha ao salvar linha {excel_row}: {e}")

    def _apply_batch_geocode_to_record(self, excel_row: int, lat: float, lon: float, micro_finder=None) -> bool:
        orig = self._get_record_by_excel_row(excel_row)
        if not orig:
            return False

        apply_geocode_to_record(orig, lat, lon, micro_finder)
        self.excel._write_row(orig.excel_row, orig)
        return True

    def _save_batch_geocode_results(self, sucessos: int, erros_escrita: int):
        if sucessos <= 0:
            QMessageBox.warning(self, "Aviso", "Nenhum dado pode ser gravado no arquivo.")
            return

        self.excel._create_rotating_backup()
        self.excel.wb.save(self.excel.path)
        self._mark_metrics_dirty()
        self._mark_heatmap_dirty()
        self.apply_filter()
        self._update_dashboard()

        msg = f"{sucessos} endereços foram georreferenciados e salvos com sucesso!"
        if erros_escrita > 0:
            msg += f"\n(Houve erro em {erros_escrita} registros)"
        QMessageBox.information(self, "Concluído", msg)

    def on_geocode_finished(self, resultados: dict):
        if hasattr(self, "progress") and self.progress:
            self.progress.close()

        if not resultados:
            QMessageBox.information(self, "Aviso", "Nenhum endereço novo foi localizado.")
            return

        erros_escrita = 0
        sucessos = 0
        micro_finder = build_cached_microbacia_finder(self.gis.find_microbacia if self.gis else None)
        for excel_row, coords in resultados.items():
            lat, lon = coords
            try:
                if self._apply_batch_geocode_to_record(excel_row, lat, lon, micro_finder):
                    sucessos += 1
            except Exception as e:
                erros_escrita += 1
                print(f"Erro ao escrever linha {excel_row}: {e}")

        try:
            self._save_batch_geocode_results(sucessos, erros_escrita)
        except PermissionError:
            QMessageBox.critical(self, "Erro de Permissão",
                                 "Não foi possível salvar. O arquivo Excel está aberto em outro programa.")
        except Exception as e:
            QMessageBox.critical(self, "Erro Inesperado", f"Falha ao salvar o Excel:\n{e}")




