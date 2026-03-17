import os
import json
import tempfile
import uuid
from typing import Dict, List, Optional, Tuple
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QPushButton, QSizePolicy
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from app.ui.components.widgets import KPICard
from app.ui.components.ui_utils import resource_path

class DashboardTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = parent
        self.sf = getattr(parent, "scale_factor", 1.0)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(int(10*self.sf), int(10*self.sf), int(10*self.sf), int(10*self.sf))
        layout.setSpacing(int(10*self.sf))

        # Cards
        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(int(10*self.sf))
        self.card_total = KPICard("Total Mudas", "0", "#2176ff")
        self.card_pend = KPICard("Pendentes", "0", "#d32f2f")
        self.card_comp = KPICard("Compensadas", "0", "#2e7d32")
        self.card_records = KPICard("Total Processos", "0", "#ff9800")
        for c in [self.card_total, self.card_pend, self.card_comp, self.card_records]:
            cards_layout.addWidget(c)
        layout.addLayout(cards_layout)

        # Export Actions
        actions_layout = QHBoxLayout()
        self.btn_export_pdf = QPushButton("Exportar Painel (PDF)")
        self.btn_export_pdf.setMinimumHeight(int(30*self.sf))
        actions_layout.addStretch(1)
        actions_layout.addWidget(self.btn_export_pdf)
        layout.addLayout(actions_layout)

        # QWebEngineView for ECharts
        self.web = QWebEngineView()
        self.web.setStyleSheet("background: transparent;")
        self.web.page().setBackgroundColor(Qt.transparent)
        
        self._page_loaded = False
        self.web.loadFinished.connect(self._on_load_finished)
        
        html_path = resource_path("app", "ui", "dashboard_echarts.html")
        if os.path.exists(html_path):
            self.web.setUrl(QUrl.fromLocalFile(html_path))
        layout.addWidget(self.web, 1)
        
        self.last_data = None

    def _on_load_finished(self, ok):
        if ok:
            self._page_loaded = True
            if self.last_data:
                self._send_to_js(self.last_data)

    def _send_to_js(self, data: Dict):
        script = f"if(window.updateDashboard) window.updateDashboard({json.dumps(json.dumps(data))});"
        self.web.page().runJavaScript(script)

    def update_dashboard(self, m: Dict, is_dark: bool, records_micros: List[str]):
        # Cards
        self.card_total.update_value(f"{m['total_geral']:,.0f}".replace(",", "."))
        self.card_pend.update_value(f"{m['total_pendente']:,.0f}".replace(",", "."))
        self.card_comp.update_value(f"{m['total_compensado']:,.0f}".replace(",", "."))
        self.card_records.update_value(f"{m['count_total']}")

        payload = {
            "m": m,
            "is_dark": is_dark,
            "records_micros": records_micros
        }
        self.last_data = payload
        
        if self._page_loaded:
            self._send_to_js(payload)

    def apply_theme(self, theme):
        for c in [self.card_total, self.card_pend, self.card_comp, self.card_records]:
            c.update_style(theme)
        if self.last_data:
            # Garantir que a WebView acompanhe o tema
            is_dark = getattr(self.main_window, "is_dark_mode", False)
            self.last_data["is_dark"] = is_dark
            if self._page_loaded:
                self._send_to_js(self.last_data)

    def export_images(self) -> Tuple[str, str]:
        pixmap = self.web.grab()
        if pixmap.isNull():
            return "", ""

        width = pixmap.width()
        height = pixmap.height()
        if width <= 1 or height <= 1:
            return "", ""

        pie_width = max(1, int(width * 0.45))
        bar_width = max(1, width - pie_width)

        pie_pixmap = pixmap.copy(0, 0, pie_width, height)
        bar_pixmap = pixmap.copy(pie_width, 0, bar_width, height)

        token = uuid.uuid4().hex
        pie_path = os.path.join(tempfile.gettempdir(), f"dash_pie_{token}.png")
        bar_path = os.path.join(tempfile.gettempdir(), f"dash_bar_{token}.png")

        pie_pixmap.save(pie_path)
        bar_pixmap.save(bar_path)
        return pie_path, bar_path
