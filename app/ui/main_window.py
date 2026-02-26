import os
import sys
import json
import tempfile
import time
import requests
import gc
from pathlib import Path
from typing import List, Optional, Tuple, Dict
from threading import Lock
from PySide6.QtCore import QTimer

# --- Importações PySide6 ---
from PySide6.QtCore import (
    Qt, QSortFilterProxyModel, QSettings, QObject, Slot, QUrl, QThread, Signal
)
from PySide6.QtGui import (
    QStandardItemModel, QStandardItem, QColor, QPainter, QAction, QKeySequence, QIcon
)
from PySide6.QtWidgets import (
    QApplication, QProgressDialog, QMainWindow, QWidget, QFileDialog, QMessageBox,
    QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit, QLabel,
    QTableView, QCheckBox, QSplitter, QComboBox, QButtonGroup, QTabWidget,
    QGroupBox, QDialog, QFrame, QHeaderView, QGridLayout, QRadioButton,
    QSizePolicy, QStyle
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PySide6.QtCharts import (
    QChart, QChartView, QPieSeries, QBarSeries, QBarSet,
    QBarCategoryAxis, QValueAxis
)
from PySide6.QtCore import Qt

# --- CORREÇÃO DE CAMINHOS (ANTES dos imports do projeto que usam GIS) ---
def _ajustar_ambiente_pyinstaller():
    """
    Garante que, no executável (onedir), DLLs e dados possam ser encontrados.
    """
    try:
        if getattr(sys, "frozen", False):
            exe_dir = os.path.dirname(sys.executable)
            internal_dir = os.path.join(exe_dir, "_internal")

            # adiciona caminhos no PATH (útil para libs que precisam de DLLs)
            os.environ["PATH"] = internal_dir + os.pathsep + exe_dir + os.pathsep + os.environ.get("PATH", "")

            # Alguns builds usam _MEIPASS (onefile). Mantém compatibilidade:
            if hasattr(sys, "_MEIPASS"):
                os.environ["PATH"] = sys._MEIPASS + os.pathsep + os.environ.get("PATH", "")
    except Exception:
        pass


_ajustar_ambiente_pyinstaller()


import os
import sys

def resource_path(*partes: str) -> str:
    """
    Resolve caminhos tanto no modo desenvolvimento quanto no executável (PyInstaller).
    - ONEDIR: sys._MEIPASS costuma ser ...\\dist\\Compensacoes\\_internal
    - Fallback: ...\\dist\\Compensacoes\\_internal (a partir do sys.executable)
    """
    rel = os.path.join(*partes)

    # Executável (PyInstaller)
    if getattr(sys, "frozen", False):
        candidatos = []

        # 1) Base do PyInstaller (mais confiável)
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidatos.append(os.path.join(meipass, rel))
            # alguns casos antigos colocam coisas em _internal dentro do meipass
            candidatos.append(os.path.join(meipass, "_internal", rel))

        # 2) Fallback: pasta do .exe
        exe_dir = os.path.dirname(sys.executable)
        candidatos.append(os.path.join(exe_dir, rel))
        candidatos.append(os.path.join(exe_dir, "_internal", rel))

        for p in candidatos:
            if os.path.exists(p):
                return p

        # Retorna o mais provável (para mostrar em mensagens de erro)
        return candidatos[0] if candidatos else os.path.join(exe_dir, rel)

    # Desenvolvimento: raiz do projeto (assumindo main_window.py em app/ui/)
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    return os.path.join(base_dir, rel)

    # Execução normal (projeto): sobe 3 níveis a partir de app/ui/main_window.py para a raiz
    base_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base_path, relative_path)


# --- Importações do Projeto ---
from app.models.compensacao import Compensacao
from app.services.excel_service import ExcelService
from app.services.validation import validate_compensacao
from app.services.report_service import (
    export_csv, export_pdf, export_dashboard_pdf,
    export_excel_two_sheets, ALL_COLUMNS
)
from app.services.gis_service import GisService

# --- CONSTANTES ---
COLS = [
    "Ofício/ Processo", "Eletrônico", "Caixa", "Av. Tec.",
    "Compensação", "Endereço", "Microbacia", "Compensado"
]
MICROB_NAME_FIELD = "Nome_Do_Arquivo"
MICROB_DIR = resource_path(os.path.join("data", "microbacias"))




def _safe_upper(s: str) -> str:
    return str(s).strip().upper() if s is not None else ""


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
    # Agora ele emite um "pacote" (dicionário) com todos os resultados no final
    finished_process = Signal(object)

    def __init__(self, records_to_process):
        super().__init__()
        self.records = records_to_process
        self.is_running = True
        self.resultados = {}  # A "caixa" onde ele vai guardar os acertos

    def run(self):
        import time
        import requests
        total = len(self.records)
        for i, r in enumerate(self.records):
            if not self.is_running:
                break
            address = r.endereco
            self.progress_update.emit(i, f"Buscando ({i + 1}/{total}): {str(address)[:30]}...")

            coords = self._geocode_api(address)
            if coords:
                # Guarda as coordenadas no pacote usando o número da linha do Excel
                self.resultados[r.excel_row] = (coords[0], coords[1])
            time.sleep(0.3)

        # Entrega o pacote completo de uma vez só!
        self.finished_process.emit(self.resultados)

    def stop(self):
        self.is_running = False

    def _geocode_api(self, address: str):
        import requests
        if not address or not str(address).strip():
            return None
        clean_addr = str(address).strip()
        if "são carlos" not in clean_addr.lower() and "sao carlos" not in clean_addr.lower():
            clean_addr += ", São Carlos, SP"

        url = "https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates"
        params = {
            "SingleLine": clean_addr, "f": "json", "maxLocations": 1,
            "outFields": "Match_addr,Addr_type", "countryCode": "BRA"
        }
        headers = {"User-Agent": "CompensacoesApp/1.0"}

        try:
            r = requests.get(url, params=params, headers=headers, timeout=8)
            if r.status_code == 200:
                data = r.json()
                if data.get("candidates"):
                    loc = data["candidates"][0]["location"]
                    return float(loc["y"]), float(loc["x"])
        except Exception:
            pass
        return None

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
            return True  # Se não há itens, assume que não há restrição de filtro
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
        self.btn_reset = QPushButton("Padrão")
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

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        top_bar = QFrame()
        top_bar.setObjectName("TopBar")
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(10, 8, 10, 8)
        top_layout.setSpacing(8)

        self.in_search = QLineEdit()
        self.in_search.setPlaceholderText("Pesquisar endereço...")
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
        s = self.web.settings()
        s.setAttribute(QWebEngineSettings.PluginsEnabled, False)
        s.setAttribute(QWebEngineSettings.JavascriptCanOpenWindows, False)
        s.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
        s.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)

        self.web.setPage(DebugPage(self.web))
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

    def _on_layer_changed_fullscreen(self, layer_name):
        if self.parent_window:
            self.parent_window.save_map_layer_preference(layer_name)

    def _on_loaded(self, ok):
        if not ok:
            return
        if self.geojson_data:
            self.web.page().runJavaScript(
                f"if(window.setMicrobacias) window.setMicrobacias({json.dumps(self.geojson_data)});")
        if self.theme:
            self.web.page().runJavaScript(f"if(window.setTheme) window.setTheme('{self.theme}');")
        if self.current_layer:
            self.web.page().runJavaScript(f"if(window.setBaseLayer) window.setBaseLayer('{self.current_layer}');")
        if self.marker_coords:
            self.web.page().runJavaScript(
                f"if(window.setMarker) window.setMarker({self.marker_coords[0]}, {self.marker_coords[1]});")
        if self.heatmap_points:
            self.web.page().runJavaScript(
                f"if(window.setHeatmap) window.setHeatmap({json.dumps(self.heatmap_points)});")

    def perform_search(self):
        address = self.in_search.text().strip()
        if not address:
            return
        self.lbl_status.setText("Buscando...")
        QApplication.processEvents()

        clean = address.strip()
        if "são carlos" not in clean.lower():
            clean += ", São Carlos, SP"

        url = "https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates"
        try:
            r = requests.get(url, params={"SingleLine": clean, "f": "json", "maxLocations": 1}, timeout=7).json()
            if r.get("candidates"):
                loc = r["candidates"][0]["location"]
                self.web.page().runJavaScript(f"window.setMarker({loc['y']}, {loc['x']});")
                self.lbl_status.setText("Localizado")
            else:
                self.lbl_status.setText("Não encontrado")
        except Exception:
            self.lbl_status.setText("Erro")


# --- MAIN WINDOW ---

class TableFullScreenDialog(QDialog):
    """
    Tela cheia da planilha.

    Requisitos:
    - Manter filtros, barra de busca e botões de exportação também em tela cheia.
    - Não duplicar a tabela (reusa o painel esquerdo com tabela + totais + exportação).
    - Controles no topo são "espelhos" sincronizados com os controles da janela principal,
      para não mexer no layout original e evitar bugs de reparent.
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
        self.in_search.setPlaceholderText("Buscar (ofício, av. tec, endereço, microbacia...)")
        self.in_search.setClearButtonEnabled(True)
        self.in_search.setText(self._mw.search.text())

        # mantém sincronizado nos dois sentidos
        self.in_search.textChanged.connect(self._on_fs_search_changed)
        self._mw.search.textChanged.connect(self._on_main_search_changed)

        sb.addWidget(QLabel("Busca:"))
        sb.addWidget(self.in_search, 1)

        # (opcional) botão limpar rápido
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
        self.fs_filter_eletronico = self._clone_checkable_combo(self._mw.filter_eletronico, "Eletrônico")

        self.fs_filter_status = QComboBox()
        self._copy_combo_items(self._mw.filter_status, self.fs_filter_status)
        self.fs_filter_status.setCurrentIndex(self._mw.filter_status.currentIndex())

        # botões (chamam as mesmas ações do MainWindow)
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

        # sincronização filtros (fs -> main)
        self.fs_filter_micro.currentTextChanged.connect(
            lambda: self._sync_checkable_to_main(self.fs_filter_micro, self._mw.filter_micro))
        self.fs_filter_eletronico.currentTextChanged.connect(
            lambda: self._sync_checkable_to_main(self.fs_filter_eletronico, self._mw.filter_eletronico))
        self.fs_filter_status.currentTextChanged.connect(self._on_fs_status_changed)

        # sincronização filtros (main -> fs)
        self._mw.filter_micro.currentTextChanged.connect(
            lambda: self._sync_checkable_to_fs(self._mw.filter_micro, self.fs_filter_micro))
        self._mw.filter_eletronico.currentTextChanged.connect(
            lambda: self._sync_checkable_to_fs(self._mw.filter_eletronico, self.fs_filter_eletronico))
        self._mw.filter_status.currentTextChanged.connect(self._on_main_status_changed)

        # manter contador em sync quando filtro roda
        try:
            # sempre que statusbar mudar (após apply_filter), atualiza contador
            self._mw.search.textChanged.connect(self._refresh_results_label)
            self._mw.filter_status.currentTextChanged.connect(self._refresh_results_label)
            self._mw.filter_micro.currentTextChanged.connect(self._refresh_results_label)
            self._mw.filter_eletronico.currentTextChanged.connect(self._refresh_results_label)
        except Exception:
            pass

        # ---------- Conteúdo (painel esquerdo com tabela + totais + exportação) ----------
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
        try:
            cm.item(0).setData(m.item(0).data(Qt.CheckStateRole), Qt.CheckStateRole)
        except Exception:
            pass
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
                # reconstrói o FS a partir do main
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
            # atualiza o campo principal (mantém toda a lógica existente de filtro)
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
        try:
            if hasattr(self._mw, "lbl_results"):
                self.lbl_results.setText(self._mw.lbl_results.text())
        except Exception:
            pass

    def closeEvent(self, event):
        try:
            # desconecta sinais (evita referências penduradas)
            try:
                self._mw.search.textChanged.disconnect(self._on_main_search_changed)
            except Exception:
                pass
            try:
                self._mw.filter_status.currentTextChanged.disconnect(self._on_main_status_changed)
            except Exception:
                pass
            try:
                self._mw.filter_micro.currentTextChanged.disconnect(
                    lambda: self._sync_checkable_to_fs(self._mw.filter_micro, self.fs_filter_micro))
            except Exception:
                pass
            try:
                self._mw.filter_eletronico.currentTextChanged.disconnect(
                    lambda: self._sync_checkable_to_fs(self._mw.filter_eletronico, self.fs_filter_eletronico))
            except Exception:
                pass

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
        self.setWindowTitle("Compensações - Cadastro e Consulta")

        icon_path = resource_path("assets", "app.ico")  # Ajuste o nome conforme seu arquivo em /assets
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        else:
            print(f"Aviso: Ícone não encontrado em {icon_path}")

        self.excel = ExcelService()
        self.records: List[Compensacao] = []
        self.filtered_records: List[Compensacao] = []
        self.selected: Optional[Compensacao] = None
        self.gis: Optional[GisService] = None
        self.last_marker_coords: Optional[Tuple[float, float]] = None

        self.settings = QSettings("CompensacoesApp", "CompensacoesDesktop")
        self.columns_visible: Dict[int, bool] = {i: True for i in range(len(COLS))}
        self.is_dark_mode = str(self.settings.value("dark_mode", "false")).lower() == "true"
        self.geo_worker = None
        self._is_reset_state = False
        self._did_initial_resize = False  # evita “tremor” ao filtrar
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
        self.search.setPlaceholderText("Buscar (ofício, av. tec, endereço, microbacia...)")
        self.search.setClearButtonEnabled(True)

        self.btn_theme = QPushButton("Tema")
        self.btn_theme.setToolTip("Alternar Modo Claro/Escuro")
        self.btn_theme.setFixedWidth(70)

        # impedir “afinamento” ao maximizar
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

        self.filter_eletronico = CheckableComboBox("Eletrônico")
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

        # Alinhamento do cabeçalho por tipo (melhor leitura)
        try:
            self.model.setHeaderData(4, Qt.Horizontal, Qt.AlignRight | Qt.AlignVCenter,
                                     Qt.TextAlignmentRole)  # Compensação
            self.model.setHeaderData(7, Qt.Horizontal, Qt.AlignCenter | Qt.AlignVCenter,
                                     Qt.TextAlignmentRole)  # Compensado
        except Exception:
            pass

        self.proxy = NumericSortProxy()
        self.proxy.setSourceModel(self.model)

        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setSelectionMode(QTableView.SingleSelection)
        self.table.setAlternatingRowColors(True)

        # Row numbers (visíveis)
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

        totals_group = QGroupBox("Totais (Filtro Atual)")
        totals_layout = QHBoxLayout(totals_group)
        totals_layout.setContentsMargins(8, 10, 8, 8)
        totals_layout.setSpacing(8)

        self.kpi_table = QTableView()
        self.kpi_model = QStandardItemModel(0, 2)
        self.kpi_model.setHorizontalHeaderLabels(["Métrica", "Valor"])
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
        left_layout.addWidget(totals_group)

        # Mantém a área de Totais/Exportação estável (não “some” após sair da tela cheia)
        totals_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        totals_group.setMinimumHeight(180)
        totals_group.setMaximumHeight(260)

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
        left_layout.addWidget(export_widget)

        self.main_splitter.addWidget(left)

        # ---------- RIGHT ----------
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        # Cadastro em 2 colunas
        form_group = QGroupBox("Cadastro / Edição")
        fg = QGridLayout(form_group)
        fg.setContentsMargins(10, 10, 10, 10)
        fg.setHorizontalSpacing(10)
        fg.setVerticalSpacing(6)

        def mk_label(txt: str) -> QLabel:
            lb = QLabel(txt)
            lb.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            lb.setMinimumWidth(110)
            return lb

        def mk_line() -> QLineEdit:
            le = QLineEdit()
            le.setMinimumHeight(26)
            le.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            return le

        self.in_oficio = mk_line()
        self.in_caixa = mk_line()
        self.in_avtec = mk_line()
        self.in_comp = mk_line()
        self.in_end = mk_line()

        self.in_micro = QComboBox()
        self.in_micro.setEditable(True)
        self.in_micro.setMinimumHeight(26)
        self.in_micro.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        # Eletrônico (radio buttons)
        self.eletronico_container = QWidget()
        self.eletronico_layout = QHBoxLayout(self.eletronico_container)
        self.eletronico_layout.setContentsMargins(0, 0, 0, 0)
        self.eletronico_layout.setSpacing(10)
        self.eletronico_group = QButtonGroup(self)
        self.eletronico_group.setExclusive(True)

        self.chk_compensado = QCheckBox("Compensado (SIM)")
        self.chk_compensado.setMinimumHeight(24)

        fg.addWidget(mk_label("Ofício/Processo:"), 0, 0)
        fg.addWidget(self.in_oficio, 0, 1)
        fg.addWidget(mk_label("Compensação:"), 0, 2)
        fg.addWidget(self.in_comp, 0, 3)

        fg.addWidget(mk_label("Eletrônico:"), 1, 0)
        fg.addWidget(self.eletronico_container, 1, 1)
        fg.addWidget(mk_label("Microbacia:"), 1, 2)
        fg.addWidget(self.in_micro, 1, 3)

        fg.addWidget(mk_label("Caixa:"), 2, 0)
        fg.addWidget(self.in_caixa, 2, 1)
        fg.addWidget(mk_label("Endereço:"), 2, 2)
        fg.addWidget(self.in_end, 2, 3)

        fg.addWidget(mk_label("Av. Tec.:"), 3, 0)
        fg.addWidget(self.in_avtec, 3, 1)
        fg.addWidget(QLabel(""), 3, 2)
        fg.addWidget(self.chk_compensado, 3, 3)

        fg.setColumnStretch(1, 1)
        fg.setColumnStretch(3, 1)

        right_layout.addWidget(form_group)

        # CRUD buttons
        btns = QHBoxLayout()
        btns.setSpacing(8)

        self.btn_clear = QPushButton("Novo")
        self.btn_add = QPushButton("Adicionar")
        self.btn_save_edit = QPushButton("Salvar")
        self.btn_delete = QPushButton("Excluir")

        for b in [self.btn_clear, self.btn_add, self.btn_save_edit, self.btn_delete]:
            b.setMinimumHeight(30)
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        btns.addWidget(self.btn_clear)
        btns.addWidget(self.btn_add)
        btns.addWidget(self.btn_save_edit)
        btns.addWidget(self.btn_delete)

        right_layout.addLayout(btns)

        # Map controls
        map_group = QGroupBox("Mapa")
        mg = QGridLayout(map_group)
        mg.setContentsMargins(10, 10, 10, 10)
        mg.setHorizontalSpacing(8)
        mg.setVerticalSpacing(6)

        self.btn_maps = QPushButton("Pesquisar Endereço")
        self.btn_batch_geo = QPushButton("GPS em Lote")
        self.btn_map_full = QPushButton("Tela Cheia")

        self.chk_heatmap = QCheckBox("Mapa de Calor")
        self.combo_heatmap_type = QComboBox()
        self.combo_heatmap_type.addItems(["Pendentes", "Realizadas", "Tudo"])
        self.combo_heatmap_type.setMinimumWidth(150)

        for b in [self.btn_maps, self.btn_batch_geo, self.btn_map_full]:
            b.setMinimumHeight(30)
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.chk_heatmap.setMinimumHeight(24)
        self.combo_heatmap_type.setMinimumHeight(28)

        mg.addWidget(self.btn_maps, 0, 0)
        mg.addWidget(self.btn_batch_geo, 0, 1)
        mg.addWidget(self.btn_map_full, 0, 2)

        mg.addWidget(self.chk_heatmap, 1, 0)
        mg.addWidget(self.combo_heatmap_type, 1, 1)
        mg.setColumnStretch(0, 1)
        mg.setColumnStretch(1, 1)
        mg.setColumnStretch(2, 1)

        right_layout.addWidget(map_group)

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
        dash_layout.addLayout(cards_layout)

        dash_btns = QHBoxLayout()
        self.btn_export_dashboard_pdf = QPushButton("Exportar Painel (PDF)")
        dash_btns.addStretch(1)
        dash_btns.addWidget(self.btn_export_dashboard_pdf)
        dash_layout.addLayout(dash_btns)

        self.dash_splitter = QSplitter(Qt.Horizontal)
        self.dash_splitter.setChildrenCollapsible(False)
        self.dash_splitter.setHandleWidth(8)
        dash_layout.addWidget(self.dash_splitter, 1)

        self.pie_chart = QChart()
        self.pie_series = QPieSeries()
        self.pie_series.setHoleSize(0.40)
        self.pie_chart.addSeries(self.pie_series)
        self.pie_chart.setTitle("Status de Compensação")
        self.pie_chart.legend().setAlignment(Qt.AlignBottom)

        self.pie_container = QFrame()
        pie_layout = QVBoxLayout(self.pie_container)
        pie_layout.setContentsMargins(8, 8, 8, 8)
        self.pie_view = QChartView(self.pie_chart)
        self.pie_view.setRenderHint(QPainter.Antialiasing)
        pie_layout.addWidget(self.pie_view)
        self.dash_splitter.addWidget(self.pie_container)

        self.bar_chart_micro = QChart()
        self.bar_series_micro = QBarSeries()
        self.bar_chart_micro.addSeries(self.bar_series_micro)
        self.bar_chart_micro.setTitle("Top 10 - Pendências por Microbacia")
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
        self.dash_splitter.addWidget(self.bar_container)

        self.tabs.addTab(tab_dash, "Painel")

        # ===== Wiring =====
        self._setup_leaflet_map()
        self._load_sort_settings()

        # Restore splitters
        try:
            st = self.settings.value("split_main")
            if st is not None:
                self.main_splitter.restoreState(st)
        except Exception:
            pass
        try:
            st2 = self.settings.value("split_dash")
            if st2 is not None:
                self.dash_splitter.restoreState(st2)
        except Exception:
            pass

        # ===== Aparência: hierarquia de botões (primário / secundário / perigo) =====
        # (Somente visual: não altera funções)
        try:
            self.btn_open.setProperty("kind", "primary")
            self.btn_save_edit.setProperty("kind", "primary")
            self.btn_export_dashboard_pdf.setProperty("kind", "primary")

            self.btn_add.setProperty("kind", "success")
            self.btn_delete.setProperty("kind", "danger")

            for b in [
                self.btn_reload, self.btn_theme, self.btn_columns, self.btn_clear_filters, self.btn_clear_sort,
                self.btn_export_csv, self.btn_export_pdf, self.btn_export_excel, self.btn_export_pend_pdf,
                self.btn_maps, self.btn_batch_geo, self.btn_full
            ]:
                b.setProperty("kind", "secondary")
        except Exception:
            pass

        # Connections
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

        # Shortcuts (premium)
        self._setup_shortcuts()

        self._set_enabled_all(False)
        self.clear_filters()
        self._apply_columns_visibility(resize=True)  # 1x só
        self._apply_theme()
        self._update_address_search_enabled()

        self.statusBar().showMessage("Pronto")
        # ==========================================================
        # CORREÇÃO PARA TELAS 1440x900 (Evitar botões cortados)
        # ==========================================================
        # 1. Libera a janela principal para encolher até 600px de altura se o monitor exigir
        self.setMinimumSize(1024, 600)

        # 2. Força a tabela principal a aceitar ser "esmagada", liberando espaço pros botões
        try:
            self.table.setMinimumHeight(50)
        except Exception:
            pass


    # ===== Shortcuts =====
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
        # Habilita o botão somente se:
        # 1) o campo de endereço estiver habilitado (app já carregou / não está bloqueado)
        # 2) houver algum texto no endereço
        self.btn_maps.setEnabled(self.in_end.isEnabled() and bool(self.in_end.text().strip()))

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

            /* Hierarquia visual dos botões */
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

            /* ===== Menus/Popups (evita texto invisível) ===== */
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

        try:
            self.web.page().runJavaScript(
                f"if(window.setTheme) window.setTheme('{'dark' if self.is_dark_mode else 'light'}');")
        except Exception:
            pass

    # ===== Settings (columns / sort / splitters) =====
    def _load_column_settings(self):
        raw = self.settings.value("columns_visible_json", "")
        if raw:
            try:
                data = json.loads(raw)
                self.columns_visible = {int(k): bool(v) for k, v in data.items()}
            except Exception:
                pass

    def _save_column_settings(self):
        try:
            self.settings.setValue("columns_visible_json", json.dumps(self.columns_visible))
        except Exception:
            pass

    def _save_sort_settings(self):
        if self._is_reset_state:
            self.settings.setValue("sort_column", -1)
        else:
            self.settings.setValue("sort_column", self.proxy.sortColumn())
            self.settings.setValue("sort_order", int(self.proxy.sortOrder()))

    def _load_sort_settings(self):
        col = int(self.settings.value("sort_column", -1))
        if col >= 0:
            self.proxy.sort(col, Qt.SortOrder(int(self.settings.value("sort_order", 0))))
            self.table.horizontalHeader().setSortIndicator(col, Qt.SortOrder(int(self.settings.value("sort_order", 0))))
        else:
            self.proxy.sort(-1)

    def closeEvent(self, event):
        self._save_column_settings()
        self._save_sort_settings()
        try:
            self.settings.setValue("split_main", self.main_splitter.saveState())
        except Exception:
            pass
        try:
            self.settings.setValue("split_dash", self.dash_splitter.saveState())
        except Exception:
            pass
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

        s = self.web.settings()
        s.setAttribute(QWebEngineSettings.PluginsEnabled, False)
        s.setAttribute(QWebEngineSettings.JavascriptCanOpenWindows, False)
        s.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
        s.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)

        self.web.setPage(DebugPage(self.web))
        self.web.setUrl(QUrl.fromLocalFile(str(path)))

        self.channel = QWebChannel(self.web.page())
        self.bridge = MapBridge(self._handle_map_click, self.save_map_layer_preference)
        self.channel.registerObject("bridge", self.bridge)
        self.web.page().setWebChannel(self.channel)

        def on_loaded(ok):
            if ok:
                self._load_last_excel()
                self._apply_theme()
                saved_layer = self.settings.value("map_layer", "Mapa Claro")
                try:
                    self.web.page().runJavaScript(f"if(window.setBaseLayer) window.setBaseLayer('{saved_layer}');")
                except Exception:
                    pass
            else:
                self._set_map_status("Falha ao carregar o HTML do mapa.")

        self.web.loadFinished.connect(on_loaded)

    def _set_map_status(self, msg: str):
        try:
            self.web.page().runJavaScript(f"window.setStatus({json.dumps(msg)});")
        except Exception:
            pass

    def _set_map_marker(self, lat: float, lng: float):
        try:
            self.web.page().runJavaScript(f"window.setMarker({lat}, {lng});")
        except Exception:
            pass

    def _highlight_microbacia(self, micro_name: str):
        try:
            self.web.page().runJavaScript(
                f"window.highlightGeoJsonByName({json.dumps(MICROB_NAME_FIELD)}, {json.dumps(micro_name)});"
            )
        except Exception:
            pass

    def _handle_map_click(self, lat: float, lng: float):
        self.last_marker_coords = (lat, lng)

        if not self.gis:
            self._load_microbacias_layer()
            if not self.gis:
                self._set_map_status(f"Erro: Pasta {MICROB_DIR} não encontrada.")
                return

        micro = self.gis.find_microbacia(lat, lng)
        if micro:
            self.in_micro.setCurrentText(micro)
            self._highlight_microbacia(micro)
            self._set_map_status(f"Ponto dentro de: {micro}")
        else:
            self._set_map_status("Fora de microbacia conhecida.")

    def _get_planilha_panel(self) -> Tuple[Optional[QWidget], int]:
        """Retorna o widget do splitter principal que contém a “planilha” e seu índice.

        Isso evita inversão esquerda/direita caso o layout mude.
        """
        try:
            if hasattr(self, "table") and self.table is not None:
                for i in range(self.main_splitter.count()):
                    w = self.main_splitter.widget(i)
                    if w is not None and w.isAncestorOf(self.table):
                        return w, i
        except Exception:
            pass

        # Fallback para versões antigas que guardavam _left_panel
        w = getattr(self, "_left_panel", None)
        try:
            idx = self.main_splitter.indexOf(w) if w is not None else 0
        except Exception:
            idx = 0
        return w, idx

    def open_fullscreen_table(self):
        """Abre a área da planilha em tela cheia (mantém filtros/busca/exportação via painel reutilizado)."""
        panel = None
        try:
            if self._table_fs_dialog is not None:
                try:
                    if self._table_fs_dialog.isVisible():
                        self._table_fs_dialog.activateWindow()
                        self._table_fs_dialog.raise_()
                        return
                except Exception:
                    pass
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
                except Exception:
                    pass
                try:
                    self.main_splitter.insertWidget(idx, self._table_fs_placeholder)
                except Exception:
                    pass

            dlg = TableFullScreenDialog(self, panel, self._restore_table_panel)
            self._table_fs_dialog = dlg
            dlg.showMaximized()
            try:
                dlg.activateWindow()
                dlg.raise_()
            except Exception:
                pass

        except Exception as e:
            try:
                if panel is not None:
                    self._restore_table_panel(panel)
            except Exception:
                pass
            QMessageBox.critical(self, "Erro", f"Falha ao abrir tela cheia da planilha:\n{e}")

    def _restore_table_panel(self, panel_widget: QWidget):
        """Restaura o painel da planilha no mesmo índice do splitter, sem inverter lados."""
        if panel_widget is None:
            return

        # Índice original antes de abrir a tela cheia
        try:
            idx = int(getattr(self, "_table_fs_index", 0))
        except Exception:
            idx = 0

        # Garante índice válido
        try:
            count = self.main_splitter.count()
            if idx < 0:
                idx = 0
            if idx >= count:
                idx = max(0, count - 1)
        except Exception:
            pass

        # IMPORTANTE: não remover o placeholder antes de substituir
        try:
            try:
                self.main_splitter.replaceWidget(idx, panel_widget)
            except Exception:
                # Fallback: tenta inserir no índice (mantendo a ordem)
                panel_widget.setParent(self.main_splitter)
                self.main_splitter.insertWidget(idx, panel_widget)
        except Exception:
            pass

        # Agora sim, remove o placeholder (se existir)
        try:
            if self._table_fs_placeholder is not None:
                self._table_fs_placeholder.setParent(None)
        except Exception:
            pass

        # Restaura tamanhos/estado do splitter
        try:
            if self._table_fs_split_state is not None:
                self.main_splitter.restoreState(self._table_fs_split_state)
        except Exception:
            pass

        # ==========================================================
        # CORREÇÃO: Zerar a Política de Tamanho da Tabela
        # ==========================================================
        try:
            # 1. Guardamos a política original de redimensionamento da tabela
            politica_antiga = self.table.sizePolicy()

            # 2. Forçamos a tabela a ignorar qualquer tamanho em cache (fazendo-a encolher)
            from PySide6.QtWidgets import QSizePolicy
            self.table.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)

            def _restaurar_tamanho_tabela():
                # 3. Devolvemos a capacidade da tabela de se expandir normalmente
                self.table.setSizePolicy(politica_antiga)

                # 4. Reaplicamos as larguras exatas do painel esquerdo/direito
                if getattr(self, '_table_fs_split_sizes', None):
                    self.main_splitter.setSizes(self._table_fs_split_sizes)

            # Damos 50 milissegundos para o layout "puxar" os botões para cima
            QTimer.singleShot(50, _restaurar_tamanho_tabela)
        except Exception:
            pass

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
        if not address.strip():
            return None
        clean_addr = address.strip()
        if "são carlos" not in clean_addr.lower() and "sao carlos" not in clean_addr.lower():
            clean_addr += ", São Carlos, SP"
        url = "https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates"
        params = {
            "SingleLine": clean_addr, "f": "json", "maxLocations": 1,
            "outFields": "Match_addr,Addr_type", "countryCode": "BRA"
        }
        try:
            r = requests.get(url, params=params, timeout=10)
            data = r.json()
            if data and "candidates" in data and len(data["candidates"]) > 0:
                cand = data["candidates"][0]
                return float(cand["location"]["y"]), float(cand["location"]["x"])
        except Exception:
            pass
        return None

    def search_on_map_by_address(self):
        addr = self.in_end.text().strip()
        if not addr:
            QMessageBox.warning(self, "Atenção", "Digite um endereço para pesquisar.")
            return

        self._set_map_status("Pesquisando endereço...")
        self.statusBar().showMessage("Pesquisando endereço...")
        result = self.geocode_address(addr)
        if not result:
            self._set_map_status("Endereço não encontrado.")
            self.statusBar().showMessage("Endereço não encontrado")
            QMessageBox.warning(self, "Não encontrado", "Não consegui localizar esse endereço.")
            return

        lat, lng = result
        self.last_marker_coords = (lat, lng)
        self._set_map_marker(lat, lng)

        if self.selected:
            self.selected.latitude = str(lat)
            self.selected.longitude = str(lng)
            try:
                self.excel.save_edit(self.selected)
            except Exception:
                pass

        if self.gis:
            micro = self.gis.find_microbacia(lat, lng)
            if micro:
                self.in_micro.setCurrentText(micro)
                self._highlight_microbacia(micro)
                self._set_map_status(f"Endereço localizado. Microbacia: {micro}")
                self.statusBar().showMessage(f"Endereço localizado. Microbacia: {micro}")
            else:
                self._set_map_status("Endereço localizado, mas microbacia não detectada.")
                self.statusBar().showMessage("Endereço localizado (microbacia não detectada)")

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

    # ===== Filters =====
    def clear_filters(self):
        """Limpa apenas os filtros aplicados, sem apagar a lista de itens."""
        self.search.setText("")
        self.filter_status.setCurrentText("Todos")
        try:
            self.filter_micro.select_all()
            self.filter_eletronico.select_all()
        except Exception:
            pass
        self.apply_filter()
        self.statusBar().showMessage("Filtros limpos")

    def clear_sorting(self):
        """Remove ordenação da tabela (volta ao estado 'sem ordenação')."""
        self._is_reset_state = True
        try:
            try:
                # -1 remove ordenação no proxy
                self.proxy.sort(-1)
            except Exception:
                pass
            try:
                self.table.horizontalHeader().setSortIndicatorShown(False)
            except Exception:
                pass
        finally:
            try:
                self._save_sort_settings()
            except Exception:
                pass
            self._is_reset_state = False

    def _unique_non_empty(self, values: List[str]) -> List[str]:
        seen = set()
        out = []
        for v in values:
            v = str(v).strip() if v is not None else ""
            if not v:
                continue
            key = v.upper()
            if key not in seen:
                seen.add(key)
                out.append(v)
        return sorted(out)

    def _row_is_compensado(self, c: Compensacao) -> bool:
        return _safe_upper(c.compensado) == "SIM"

    def _to_float(self, v) -> float:
        if v is None:
            return 0.0
        if isinstance(v, (int, float)):
            return float(v)
        s = str(v).strip().replace(",", ".")
        if not s:
            return 0.0
        try:
            return float(s)
        except Exception:
            return 0.0

    def _compute_metrics(self, records: List[Compensacao]) -> Dict[str, object]:
        total_geral = 0.0
        total_pendente = 0.0
        total_compensado = 0.0
        count_total = 0
        count_comp = 0
        count_pend = 0
        pend_micro: Dict[str, float] = {}
        pend_ele: Dict[str, float] = {}

        for r in records:
            val = self._to_float(r.compensacao)
            total_geral += val
            count_total += 1
            if self._row_is_compensado(r):
                total_compensado += val
                count_comp += 1
            else:
                total_pendente += val
                count_pend += 1
                micro = (r.microbacia or "").strip() or "(Sem microbacia)"
                pend_micro[micro] = pend_micro.get(micro, 0.0) + val
                ele = (r.eletronico or "").strip() or "(Sem eletrônico)"
                pend_ele[ele] = pend_ele.get(ele, 0.0) + val

        micro_sorted = sorted(pend_micro.items(), key=lambda x: x[1], reverse=True)
        ele_sorted = sorted(pend_ele.items(), key=lambda x: x[1], reverse=True)
        return {
            "total_geral": total_geral, "total_pendente": total_pendente,
            "total_compensado": total_compensado, "count_total": count_total,
            "count_comp": count_comp, "count_pend": count_pend,
            "pend_micro_sorted": micro_sorted, "pend_ele_sorted": ele_sorted,
        }

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
            opcoes = ["SIM", "NÃO"]

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
        # Auto ajuste inicial (evita “tremor” durante filtros)
        self.table.resizeColumnsToContents()

        # Endereço costuma precisar de mais espaço
        if not self.table.isColumnHidden(5):
            self.table.setColumnWidth(5, max(self.table.columnWidth(5), 320))

        # Microbacia também costuma cortar
        if not self.table.isColumnHidden(6):
            self.table.setColumnWidth(6, max(self.table.columnWidth(6), 200))

    def _auto_resize_totals_tables(self):
        self.kpi_table.resizeColumnsToContents()
        self.micro_table.resizeColumnsToContents()
        # Não deixar encolher demais após atualizar/limpar filtros
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

    # ===== Table + Totals =====
    def populate_table(self, records: List[Compensacao]):
        self.table.setUpdatesEnabled(False)
        self.model.setRowCount(0)

        # Badge colors for "Compensado"
        if self.is_dark_mode:
            badge_bg_ok = QColor("#1f6f3a")
            badge_fg_ok = QColor("#eafff1")
            badge_bg_no = QColor("#3a3f4c")
            badge_fg_no = QColor("#e9e9ea")
        else:
            badge_bg_ok = QColor("#c6efce")
            badge_fg_ok = QColor("#1d4b2a")
            badge_bg_no = QColor("#e9edf3")
            badge_fg_no = QColor("#1f2328")

        rows_to_add = []
        for c in records:
            it_comp = QStandardItem("" if c.compensacao is None else str(c.compensacao))
            it_comp.setData(self._to_float(c.compensacao), Qt.UserRole)

            it_compensado = QStandardItem(c.compensado)
            is_ok = self._row_is_compensado(c)

            # “badge” só na coluna Compensado (sem pintar a linha inteira)
            if is_ok:
                it_compensado.setText("SIM")
                it_compensado.setBackground(badge_bg_ok)
                it_compensado.setForeground(badge_fg_ok)
            else:
                it_compensado.setText("" if not str(c.compensado or "").strip() else str(c.compensado))
                it_compensado.setBackground(badge_bg_no)
                it_compensado.setForeground(badge_fg_no)

            items = [
                QStandardItem(c.oficio_processo), QStandardItem(c.eletronico),
                QStandardItem(c.caixa), QStandardItem(c.av_tec), it_comp,
                QStandardItem(c.endereco), QStandardItem(c.microbacia),
                it_compensado
            ]

            # Excel row
            items[0].setData(c.excel_row, Qt.UserRole)

            # Tooltip coords (se existirem)
            lat = getattr(c, "latitude", "")
            lon = getattr(c, "longitude", "")
            if str(lat).strip() and str(lon).strip():
                tip = f"Lat/Lon: {lat}, {lon}"
                for it in items:
                    it.setToolTip(tip)

            rows_to_add.append(items)

        for row in rows_to_add:
            self.model.appendRow(row)

        # NÃO chamar resizeColumnsToContents a cada filtro (evita tremor)
        self._apply_columns_visibility(resize=not self._did_initial_resize)
        self.table.setUpdatesEnabled(True)

    def _update_totals_tables(self):
        m = self._compute_metrics(self.filtered_records)

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
        m = self._compute_metrics(self.records)

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
    def export_csv_clicked(self):
        if not self.records:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Salvar CSV", "", "CSV (*.csv)")
        if path:
            export_csv(path, self.filtered_records, self._selected_export_attrs())
            QMessageBox.information(self, "Sucesso", "Exportado com sucesso.")

    def export_excel_clicked(self):
        if not self.records:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Salvar Excel", "", "Excel (*.xlsx)")
        if path:
            m = self._compute_metrics(self.filtered_records)
            kpis = [("Total", m["total_geral"]), ("Pendente", m["total_pendente"]),
                    ("Compensado", m["total_compensado"])]
            export_excel_two_sheets(path, self.filtered_records, "Filtro", self._selected_export_attrs(), kpis,
                                    m["pend_micro_sorted"], m["pend_ele_sorted"])
            QMessageBox.information(self, "Sucesso", "Exportado com sucesso.")

    def export_pdf_clicked(self):
        if not self.records:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Salvar PDF", "", "PDF (*.pdf)")
        if path:
            m = self._compute_metrics(self.filtered_records)
            kpis = [("Total", m["total_geral"]), ("Pendente", m["total_pendente"])]
            export_pdf(path, self.filtered_records, "Filtro", self._selected_export_attrs(), kpis,
                       m["pend_micro_sorted"])
            QMessageBox.information(self, "Sucesso", "Exportado com sucesso.")

    def export_dashboard_pdf_clicked(self):
        if not self.records:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Salvar PDF", "", "PDF (*.pdf)")
        if path:
            d = tempfile.mkdtemp()
            pie, bar = os.path.join(d, "p.png"), os.path.join(d, "b.png")
            self.pie_view.grab().save(pie)
            self.bar_view_micro.grab().save(bar)
            m = self._compute_metrics(self.records)
            export_dashboard_pdf(path, "Painel", [f"Total: {m['total_geral']}"], "Geral", [pie, bar])
            QMessageBox.information(self, "Sucesso", "Exportado com sucesso.")

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
        self.statusBar().showMessage("Novo registro")

    def fill_form(self, c: Compensacao):
        self.in_oficio.setText(c.oficio_processo)
        self.in_caixa.setText(c.caixa)
        self.in_avtec.setText(c.av_tec)
        self.in_comp.setText("" if c.compensacao is None else str(c.compensacao))
        self.in_end.setText(c.endereco)
        self.in_micro.setCurrentText(c.microbacia)
        self.chk_compensado.setChecked(_safe_upper(c.compensado) == "SIM")

        target = _safe_upper(c.eletronico)
        found = False
        for btn in self.eletronico_group.buttons():
            if _safe_upper(btn.text()) == target and target:
                btn.setChecked(True)
                found = True
                break
        if not found:
            for btn in self.eletronico_group.buttons():
                btn.setChecked(False)

        self._update_address_search_enabled()

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
        self.excel.save_edit(c)
        self.reload()
        QMessageBox.information(self, "Sucesso", "Salvo com sucesso.")

    def delete_selected(self):
        if not self.excel.path or not self.selected:
            return
        if QMessageBox.question(self, "Excluir", "Confirma a exclusão?") == QMessageBox.Yes:
            self.excel.delete_record_shift_up(self.selected.excel_row)
            self.reload()
            self.clear_form()

    def open_excel(self):
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        import gc
        import os

        # Abre o navegador NATIVO do Windows (Permite acessar a Rede/Servidores perfeitamente)
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Abrir Excel",
            "",
            "Excel (*.xlsx)"
        )

        if not path:
            return

        try:
            self.records = self.excel.load(path)
            self.settings.setValue("last_excel_path", path)

            gc.collect()

            self._setup_dynamic_form_options_from_records()
            self._update_filters_from_records()
            self._load_microbacias_layer()

            self.apply_filter()
            self._update_dashboard()
            self._set_enabled_all(True)

            self._apply_columns_visibility(resize=True)
            QMessageBox.information(self, "Sucesso", f"Carregado: {len(self.records)} registros.")
            self.statusBar().showMessage(f"Carregado: {len(self.records)} registros.")
        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Falha ao abrir a planilha na rede:\n{str(e)}")

    def _load_last_excel(self):
        path = self.settings.value("last_excel_path", "")
        if path and os.path.exists(path):
            try:
                self.records = self.excel.load(path)
                self.excel.path = path

                self._setup_dynamic_form_options_from_records()
                self._update_filters_from_records()
                self._load_microbacias_layer()

                self.apply_filter()
                self._update_dashboard()
                self._set_enabled_all(True)

                self._apply_columns_visibility(resize=True)
                self.statusBar().showMessage(f"Carregado: {len(self.records)} registros.")
            except Exception:
                pass

    def reload(self):
        if not self.excel.path:
            return
        try:
            self.records = self.excel.load(self.excel.path)
            gc.collect()

            self._setup_dynamic_form_options_from_records()
            self._update_filters_from_records()
            self._load_microbacias_layer()

            self.apply_filter()
            self._update_dashboard()
            self.statusBar().showMessage(f"Recarregado: {len(self.records)} registros.")
        except Exception as e:
            QMessageBox.critical(self, "Erro", str(e))

    # ===== GIS layer =====
    def _load_microbacias_layer(self):
        if not os.path.isdir(MICROB_DIR):
            self.gis = None
            print(f"[GIS] Pasta de microbacias NÃO encontrada: {MICROB_DIR}")
            # opcional (bem útil no exe):
            # QMessageBox.warning(self, "GIS", f"Pasta de microbacias não encontrada:\n{MICROB_DIR}")
            return
        try:
            if not self.gis:
                self.gis = GisService(MICROB_DIR, MICROB_NAME_FIELD)
            geojson_obj = self.gis.to_geojson_obj()
            self.web.page().runJavaScript(f"window.setMicrobacias({json.dumps(geojson_obj)});")
        except Exception as e:
            self.gis = None
            print(f"Erro GIS: {e}")

    # ===== Filtering =====
    def _agendar_filtro(self):
        # Reinicia o timer a cada digitação; o filtro roda só quando o usuário parar
        self._timer_filtro.start()

    def apply_filter(self):
        text = self.search.text().strip().lower()
        status = self.filter_status.currentText().strip()

        filtered = []
        sel_micros = self.filter_micro.checked_items()
        sel_eles = self.filter_eletronico.checked_items()

        for r in self.records:
            blob = f"{r.oficio_processo} {r.endereco} {r.microbacia} {r.av_tec} {r.caixa} {r.eletronico}".lower()
            if text and text not in blob:
                continue

            is_comp = str(r.compensado).strip().upper() == "SIM"
            if status == "Compensados" and not is_comp:
                continue
            if status == "Pendentes" and is_comp:
                continue

            if not self.filter_micro.is_all_selected() and r.microbacia not in sel_micros:
                continue

            if not self.filter_eletronico.is_all_selected() and r.eletronico not in sel_eles:
                continue

            filtered.append(r)

        self.filtered_records = filtered
        self.populate_table(filtered)
        self._update_totals_tables()
        self.toggle_heatmap()
        self.statusBar().showMessage(f"Filtro aplicado: {len(filtered)} registros")

    def on_table_click(self, proxy_index):
        src_index = self.proxy.mapToSource(proxy_index)
        excel_row = self.model.item(src_index.row(), 0).data(Qt.UserRole)
        self.selected = next((r for r in self.records if r.excel_row == excel_row), None)
        if self.selected:
            self.fill_form(self.selected)

    # ===== Heatmap =====
    def on_heatmap_type_changed(self, text):
        self.toggle_heatmap()

    def _get_current_heatmap_points(self):
        if not self.chk_heatmap.isChecked():
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
                except Exception:
                    pass
            else:
                m = (r.microbacia or "").strip()
                if m:
                    pend_micro_fallback[m] = pend_micro_fallback.get(m, 0.0) + val

        if self.gis and not points:
            max_val = max(pend_micro_fallback.values()) if pend_micro_fallback else 1
            for m, val in pend_micro_fallback.items():
                c = self.gis.get_microbacia_centroid(m)
                if c:
                    points.append([c[0], c[1], val / max_val])

        return points

    def toggle_heatmap(self):
        if not self.gis:
            return
        pts = self._get_current_heatmap_points()
        try:
            self.web.page().runJavaScript(f"window.setHeatmap({json.dumps(pts)});")
        except Exception:
            pass

    # ===== Batch geocode =====
    def run_batch_geocode(self):
        if not self.excel.path:
            return

        to_process = [
            r for r in self.records
            if (r.endereco or "").strip() and (not getattr(r, "latitude", "") or not getattr(r, "longitude", ""))
        ]

        if not to_process:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self, "Sucesso", "Tudo georeferenciado!")
            return

        from PySide6.QtWidgets import QMessageBox, QProgressDialog
        if QMessageBox.question(self, "Lote",
                                f"Georeferenciar {len(to_process)} endereços pendentes?") == QMessageBox.Yes:
            self.progress = QProgressDialog("Processando...", "Cancelar", 0, len(to_process), self)
            self.progress.setWindowTitle("Georreferenciamento")
            self.progress.setMinimumDuration(0)

            self.geo_worker = GeocodeWorker(to_process)
            self.geo_worker.progress_update.connect(
                lambda i, t: (self.progress.setValue(i), self.progress.setLabelText(t)))

            # Agora ele conecta apenas o envio do pacote final!
            self.geo_worker.finished_process.connect(self.on_geocode_finished)
            self.geo_worker.start()

    def on_geocode_result(self, excel_row: int, lat: float, lon: float):
        # 1. Pega o registro original usando o número da linha que veio do trabalhador
        orig = next((r for r in self.records if r.excel_row == excel_row), None)
        if not orig:
            return

        # 2. Atualiza coordenadas
        orig.latitude = str(lat)
        orig.longitude = str(lon)

        # 3. Tenta identificar a microbacia cruzando com o GIS
        if self.gis:
            try:
                m = self.gis.find_microbacia(lat, lon)
                if m and str(m).strip():
                    orig.microbacia = str(m)
            except Exception as e:
                print(f"Erro ao buscar microbacia: {e}")

        # 4. Salva imediatamente a linha no Excel (Método blindado)
        try:
            self.excel.save_edit(orig)
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Erro de Salvamento", f"Falha ao salvar linha {excel_row}: {e}")

    def on_geocode_finished(self, resultados: dict):
        try:
            if hasattr(self, "progress") and self.progress:
                self.progress.close()
        except Exception:
            pass

        if not resultados:
            QMessageBox.information(self, "Aviso", "Nenhum endereço novo foi localizado.")
            return

        erros_escrita = 0
        sucessos = 0

        # 1. Itera sobre os resultados do worker
        for excel_row, coords in resultados.items():
            lat, lon = coords

            # Localiza o registro na lista da memória
            orig = next((r for r in self.records if r.excel_row == excel_row), None)
            if not orig:
                continue

            # Atualiza Latitude e Longitude (essencial para o Mapa de Calor)
            orig.latitude = str(lat)
            orig.longitude = str(lon)

            # 2. Busca automática da Microbacia via GIS
            if self.gis:
                try:
                    micro_nome = self.gis.find_microbacia(lat, lon)
                    if micro_nome:
                        orig.microbacia = micro_nome
                except Exception as e:
                    print(f"Erro GIS na linha {excel_row}: {e}")

            # 3. Escreve os dados na memória do Workbook (openpyxl)
            try:
                # O método _write_row já contempla colunas 9 e 10 (lat/lon)
                self.excel._write_row(orig.excel_row, orig)
                sucessos += 1
            except Exception as e:
                erros_escrita += 1
                print(f"Erro ao escrever linha {excel_row}: {e}")

        # 4. Salva o arquivo Excel físico
        try:
            if sucessos > 0:
                self.excel._create_rotating_backup()
                self.excel.wb.save(self.excel.path)

                # Atualiza a interface (tabela, dashboard e mapa de calor)
                self.apply_filter()
                self._update_dashboard()
                self.toggle_heatmap()

                msg = f"{sucessos} endereços foram georreferenciados e salvos com sucesso!"
                if erros_escrita > 0:
                    msg += f"\n(Houve erro em {erros_escrita} registros)"

                QMessageBox.information(self, "Concluído", msg)
            else:
                QMessageBox.warning(self, "Aviso", "Nenhum dado pôde ser gravado no arquivo.")

        except PermissionError:
            QMessageBox.critical(self, "Erro de Permissão",
                                 "Não foi possível salvar. O arquivo Excel está aberto em outro programa.")
        except Exception as e:
            QMessageBox.critical(self, "Erro Inesperado", f"Falha ao salvar o Excel:\n{e}")