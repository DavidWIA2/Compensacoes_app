import json
from typing import Dict, List, Optional, Tuple
from PySide6.QtCore import Qt, QUrl, QTimer
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton, 
    QLineEdit, QComboBox, QWidget, QSizePolicy, QMessageBox, QApplication, QCheckBox,
    QTableView, QHeaderView, QDialogButtonBox, QTableWidget, QTableWidgetItem,
    QFormLayout,
    QAbstractItemView
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEngineSettings
from app.models.display_columns import display_column_index
from app.services.coordinates import build_heatmap_points
from app.ui.components.widgets import CheckableComboBox, MapBridge, DebugPage
from app.services.geocode_service import geocode_address_arcgis
from app.services.plantio_service import build_plantios_from_rows, clone_plantios, parse_numeric_value


class PlantioRowEditorDialog(QDialog):
    def __init__(self, parent, endereco="", qtd_mudas=""):
        super().__init__(parent)
        self.setWindowTitle("Editar Plantio")
        self.resize(520, 170)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)

        self.in_endereco = QLineEdit(str(endereco or ""))
        self.in_qtd_mudas = QLineEdit(str(qtd_mudas or ""))

        form.addRow("Endereco de Plantio:", self.in_endereco)
        form.addRow("Qtd. mudas:", self.in_qtd_mudas)
        layout.addLayout(form)

        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def values(self):
        return self.in_endereco.text().strip(), self.in_qtd_mudas.text().strip()


class PlantiosDialog(QDialog):
    def __init__(self, parent, plantios, compensacao_total=""):
        super().__init__(parent)
        self.setWindowTitle("Plantios da Compensação")
        self.resize(760, 420)
        self._previous_plantios = clone_plantios(plantios)
        self._result_plantios = clone_plantios(plantios)
        self._compensacao_total = str(compensacao_total or "").strip()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self.lbl_hint = QLabel(
            "Cadastre cada endereço de plantio com a quantidade de mudas usada naquela área."
        )
        self.lbl_total = QLabel("")
        self.lbl_total.setObjectName("FormStateLabel")

        layout.addWidget(self.lbl_hint)
        layout.addWidget(self.lbl_total)

        self.table = QTableWidget(0, 2, self)
        self.table.setHorizontalHeaderLabels(["Endereço de Plantio", "Qtd. mudas"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table, 1)

        buttons_row = QHBoxLayout()
        buttons_row.setSpacing(8)
        self.btn_add_row = QPushButton("Adicionar Linha")
        self.btn_edit_row = QPushButton("Editar Linha")
        self.btn_remove_row = QPushButton("Remover Linha")
        self.btn_add_row.setProperty("kind", "secondary")
        self.btn_edit_row.setProperty("kind", "secondary")
        self.btn_remove_row.setProperty("kind", "secondary")
        buttons_row.addWidget(self.btn_add_row)
        buttons_row.addWidget(self.btn_edit_row)
        buttons_row.addWidget(self.btn_remove_row)
        buttons_row.addStretch(1)
        layout.addLayout(buttons_row)

        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        layout.addWidget(self.button_box)

        self.btn_add_row.clicked.connect(self.add_empty_row)
        self.btn_edit_row.clicked.connect(self.edit_selected_row)
        self.btn_remove_row.clicked.connect(self.remove_selected_row)
        self.button_box.accepted.connect(self._accept_with_validation)
        self.button_box.rejected.connect(self.reject)
        self.table.itemChanged.connect(self._refresh_totals)
        self.table.itemSelectionChanged.connect(self._refresh_row_actions)

        for plantio in self._previous_plantios:
            self._append_row(plantio.endereco, plantio.qtd_mudas)
        if self.table.rowCount() == 0:
            self.add_empty_row(start_edit=False)
        else:
            self.table.setCurrentCell(0, 0)
        self._refresh_totals()
        self._refresh_row_actions()

    @property
    def plantios(self):
        return clone_plantios(self._result_plantios)

    def _append_row(self, endereco="", qtd_mudas=""):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(str(endereco or "")))
        self.table.setItem(row, 1, QTableWidgetItem(str(qtd_mudas or "")))

    def add_empty_row(self, start_edit: bool = True):
        self._append_row("", "")
        self.table.setCurrentCell(self.table.rowCount() - 1, 0)
        self._refresh_totals()
        self._refresh_row_actions()
        if start_edit:
            self.edit_selected_row()

    def edit_selected_row(self):
        if self.table.rowCount() == 0:
            self.add_empty_row(start_edit=False)

        row = self.table.currentRow()
        if row < 0:
            row = self.table.rowCount() - 1

        column = self.table.currentColumn()
        if column < 0:
            column = 0

        self.table.setCurrentCell(row, column)
        self._edit_row_at(row)

    def _edit_row_at(self, row: int):
        endereco_item = self.table.item(row, 0)
        qtd_item = self.table.item(row, 1)
        editor = PlantioRowEditorDialog(
            self,
            endereco=endereco_item.text() if endereco_item else "",
            qtd_mudas=qtd_item.text() if qtd_item else "",
        )
        if not editor.exec():
            return

        endereco, qtd_mudas = editor.values()
        if endereco_item is None:
            endereco_item = QTableWidgetItem("")
            self.table.setItem(row, 0, endereco_item)
        if qtd_item is None:
            qtd_item = QTableWidgetItem("")
            self.table.setItem(row, 1, qtd_item)

        endereco_item.setText(endereco)
        qtd_item.setText(qtd_mudas)
        self.table.setCurrentCell(row, 0)
        self._refresh_totals()

    def remove_selected_row(self):
        row = self.table.currentRow()
        if row < 0:
            row = self.table.rowCount() - 1
        if row < 0:
            return
        self.table.removeRow(row)
        if self.table.rowCount() == 0:
            self.add_empty_row(start_edit=False)
            return
        next_row = min(row, self.table.rowCount() - 1)
        self.table.setCurrentCell(next_row, 0)
        self._refresh_totals()
        self._refresh_row_actions()

    def _refresh_row_actions(self):
        has_rows = self.table.rowCount() > 0
        self.btn_edit_row.setEnabled(has_rows)
        self.btn_remove_row.setEnabled(has_rows)

    def _rows_from_table(self):
        rows = []
        for row in range(self.table.rowCount()):
            endereco_item = self.table.item(row, 0)
            qtd_item = self.table.item(row, 1)
            rows.append(
                (
                    endereco_item.text().strip() if endereco_item else "",
                    qtd_item.text().strip() if qtd_item else "",
                )
            )
        return rows

    def _refresh_totals(self, *_args):
        total = 0.0
        invalid = False
        rows = self._rows_from_table()
        for endereco, qtd in rows:
            if not endereco and not qtd:
                continue
            try:
                total += parse_numeric_value(qtd)
            except ValueError:
                invalid = True

        if invalid:
            total_text = "Soma dos plantios: valor inválido"
        else:
            total_text = f"Soma dos plantios: {total:g} mudas"

        if self._compensacao_total:
            total_text = f"{total_text} | Compensação: {self._compensacao_total}"
        self.lbl_total.setText(total_text)

    def _accept_with_validation(self):
        rows = self._rows_from_table()
        plantios = build_plantios_from_rows(rows, self._previous_plantios)
        for index, item in enumerate(plantios, start=1):
            if not item.endereco:
                QMessageBox.warning(self, "Aviso", f"Preencha o endereço do Plantio {index}.")
                return
            if not item.qtd_mudas:
                QMessageBox.warning(self, "Aviso", f"Preencha a quantidade de mudas do Plantio {index}.")
                return
            try:
                qtd = parse_numeric_value(item.qtd_mudas)
            except ValueError:
                QMessageBox.warning(
                    self,
                    "Aviso",
                    f"A quantidade de mudas do Plantio {index} deve ser numérica.",
                )
                return
            if qtd <= 0:
                QMessageBox.warning(
                    self,
                    "Aviso",
                    f"A quantidade de mudas do Plantio {index} deve ser maior que zero.",
                )
                return

        self._result_plantios = plantios
        self.accept()

class MapFullScreenDialog(QDialog):
    def __init__(self, parent, html_path, geojson_data, theme, marker_coords, gis_service, current_layer, heatmap_points):
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
        self._syncing = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        top_bar = QFrame()
        top_bar.setObjectName("TopBar")
        top_layout = QVBoxLayout(top_bar)
        top_layout.setContentsMargins(10, 8, 10, 8)
        top_layout.setSpacing(6)
        
        # Linha 1: Busca
        row1 = QHBoxLayout()
        row1.setSpacing(8)
        self.in_search = QLineEdit()
        self.in_search.setPlaceholderText("Pesquisar endereço no mapa...")
        self.in_search.setMinimumWidth(300)
        self.btn_search = QPushButton("Ir para")
        self.btn_search.setProperty("kind", "primary")
        self.btn_fs_batch = QPushButton("GPS em Lote")
        btn_close = QPushButton("Sair")
        btn_close.setProperty("kind", "secondary")
        row1.addWidget(self.in_search)
        row1.addWidget(self.btn_search)
        row1.addSpacing(10)
        row1.addWidget(self.btn_fs_batch)
        row1.addStretch(1)
        row1.addWidget(btn_close)

        # Linha 2: Calor e Status
        row2 = QHBoxLayout()
        row2.setSpacing(8)
        self.chk_fs_heatmap = QCheckBox("Mapa de Calor")
        self.chk_fs_heatmap.setChecked(parent.data_tab.chk_heatmap.isChecked())
        self.combo_fs_heatmap = QComboBox()
        self.combo_fs_heatmap.addItems(["Pendentes", "Realizadas", "Tudo"])
        self.combo_fs_heatmap.setCurrentText(parent.data_tab.combo_heatmap_type.currentText())
        self.combo_fs_heatmap.setMinimumWidth(150)
        self.lbl_status = QLabel("")
        self.lbl_status.setObjectName("MapStatus")
        row2.addWidget(self.chk_fs_heatmap)
        row2.addWidget(self.combo_fs_heatmap)
        row2.addSpacing(15)
        row2.addWidget(self.lbl_status, 1)

        top_layout.addLayout(row1); top_layout.addLayout(row2)
        layout.addWidget(top_bar)

        self.web = QWebEngineView()
        self.web.setPage(DebugPage(self.web))
        s = self.web.page().settings()
        s.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
        s.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
        
        self.channel = QWebChannel(self.web.page())
        self.bridge = MapBridge(self._on_map_click_fs, self._on_layer_changed_fs)
        self.channel.registerObject("bridge", self.bridge)
        self.web.page().setWebChannel(self.channel)
        
        url = QUrl.fromLocalFile(str(html_path))
        url.setQuery("tileScheme=compmap")
        self.web.setUrl(url)
        self.web.loadFinished.connect(self._on_loaded)
        layout.addWidget(self.web, 1)

        btn_close.clicked.connect(self.close)
        self.btn_search.clicked.connect(self.perform_search)
        self.in_search.returnPressed.connect(self.perform_search)
        self.btn_fs_batch.clicked.connect(self.parent_window.run_batch_geocode)
        
        # Sincronização Calor (FS -> Main)
        self.chk_fs_heatmap.toggled.connect(self._sync_heatmap_to_main)
        self.combo_fs_heatmap.currentTextChanged.connect(self._sync_heatmap_to_main)
        
        self.showMaximized()

    def _sync_heatmap_to_main(self):
        if self._syncing: return
        self._syncing = True
        try:
            self.parent_window.data_tab.chk_heatmap.setChecked(self.chk_fs_heatmap.isChecked())
            self.parent_window.data_tab.combo_heatmap_type.setCurrentText(self.combo_fs_heatmap.currentText())
            # Atualiza o próprio mapa
            self.parent_window.toggle_heatmap() # Isso gera os pontos no main
            # Injeta aqui
            pts = self._get_current_points_fs()
            self._run_map_js(f"if(window.setHeatmap) window.setHeatmap({json.dumps(pts)});", "fs-heatmap")
        finally:
            self._syncing = False

    def _get_current_points_fs(self) -> list:
        pts = []
        typ = self.combo_fs_heatmap.currentText()
        for r in self.parent_window.filtered_records:
            pts.extend(build_heatmap_points(r, typ))
        return pts

    def _on_map_click_fs(self, lat, lng):
        self.marker_coords = (lat, lng)
        self._run_map_js(f"if(window.setMarker) window.setMarker({lat}, {lng});", "marker")
        self.lbl_status.setText(f"Ponto: {lat:.5f}, {lng:.5f}")

    def _on_layer_changed_fs(self, name):
        if self.parent_window: self.parent_window.save_map_layer_preference(name)

    def _on_loaded(self, ok):
        if not ok: return
        # Aguarda um momento para o Leaflet estar estável
        QTimer.singleShot(500, self._initial_sync_fs)

    def _initial_sync_fs(self):
        if self.theme: self._run_map_js(f"if(window.setTheme) window.setTheme('{self.theme}');", "theme")
        if self.geojson_data: self._run_map_js(f"if(window.setMicrobacias) window.setMicrobacias({json.dumps(self.geojson_data)});", "micro")
        if self.current_layer: self._run_map_js(f"if(window.setBaseLayer) window.setBaseLayer('{self.current_layer}');", "layer")
        if self.marker_coords: self._run_map_js(f"if(window.setMarker) window.setMarker({self.marker_coords[0]}, {self.marker_coords[1]});", "marker")
        if self.chk_fs_heatmap.isChecked():
            pts = self._get_current_points_fs()
            self._run_map_js(f"if(window.setHeatmap) window.setHeatmap({json.dumps(pts)});", "heat")

    def _run_map_js(self, script: str, context: str):
        try: self.web.page().runJavaScript(script)
        except Exception as exc: print(f"[FS MAP JS] Falha em {context}: {exc}")

    def perform_search(self):
        addr = self.in_search.text().strip()
        if not addr: return
        coords = geocode_address_arcgis(addr)
        if coords:
            lat, lng = coords
            self._run_map_js(f"if(window.setMarker) window.setMarker({lat}, {lng});", "search")
            self.marker_coords = (lat, lng)
            self.lbl_status.setText("Localizado")
        else:
            self.lbl_status.setText("Não encontrado")

class TableFullScreenDialog(QDialog):
    _FULLSCREEN_COLUMN_BASE_WIDTHS = {
        display_column_index("oficio_processo"): 180,
        display_column_index("eletronico"): 115,
        display_column_index("caixa"): 110,
        display_column_index("av_tec"): 120,
        display_column_index("compensacao"): 110,
        display_column_index("endereco"): 300,
        display_column_index("microbacia"): 150,
        display_column_index("compensado"): 120,
        display_column_index("endereco_plantio"): 330,
    }
    _FULLSCREEN_COLUMN_EXTRA_WEIGHTS = {
        display_column_index("oficio_processo"): 0.9,
        display_column_index("eletronico"): 0.3,
        display_column_index("caixa"): 0.25,
        display_column_index("av_tec"): 0.35,
        display_column_index("compensacao"): 0.25,
        display_column_index("endereco"): 1.8,
        display_column_index("microbacia"): 0.5,
        display_column_index("compensado"): 0.3,
        display_column_index("endereco_plantio"): 2.1,
    }

    def __init__(self, parent, content_widget, on_close_callback):
        super().__init__(parent)
        self.setWindowFlags(Qt.Window)
        self.setWindowTitle("Planilha - Tela Cheia")
        self._mw = parent
        self._content = content_widget
        self._on_close_callback = on_close_callback
        self._table = self._find_primary_table()
        self._original_resize_modes = []
        self._original_section_sizes = []
        self._original_stretch_last = False
        self._syncing_filters = False
        self._has_filter_source = all(
            hasattr(parent, attr) for attr in ("data_tab", "search", "apply_filter")
        )
         
        sf = getattr(parent, "scale_factor", 1.0)
         
        layout = QVBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(0)
        top = QFrame(); top.setObjectName("TopBar")
        top_layout = QVBoxLayout(top); top_layout.setContentsMargins(10, 10, 10, 10); top_layout.setSpacing(8)
         
        # Adiciona busca exclusiva para a tela cheia
        self.search_fs = QLineEdit()
        self.search_fs.setPlaceholderText("Filtrar planilha (Ofício, Av. Técnica, Endereço...)")
        self.search_fs.setClearButtonEnabled(True)
        self.search_fs.setMinimumWidth(int(400 * sf))
         
        self.btn_exit = QPushButton("Sair da Tela Cheia")
        self.btn_exit.setProperty("kind", "secondary"); self.btn_exit.clicked.connect(self.close)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Busca:"))
        row1.addWidget(self.search_fs)
        row1.addStretch(1)
        row1.addWidget(self.btn_exit)

        row2 = QHBoxLayout()
        row2.setSpacing(8)
        self.filter_status_fs = None
        self.filter_year_fs = None
        self.filter_micro_fs = None
        self.filter_eletronico_fs = None
        self.btn_clear_filters_fs = None

        if self._has_filter_source:
            self.filter_status_fs = QComboBox()
            self.filter_year_fs = QComboBox()
            self.filter_micro_fs = CheckableComboBox(parent.data_tab.filter_micro._all_label)
            self.filter_eletronico_fs = CheckableComboBox(parent.data_tab.filter_eletronico._all_label)
            self.btn_clear_filters_fs = QPushButton("Limpar Filtros")
            self.btn_clear_filters_fs.setProperty("kind", "secondary")

            self.filter_micro_fs.setMinimumWidth(int(220 * sf))
            self.filter_eletronico_fs.setMinimumWidth(int(140 * sf))
            self.filter_status_fs.setMinimumWidth(int(130 * sf))
            self.filter_year_fs.setMinimumWidth(int(110 * sf))

            row2.addWidget(QLabel("Microbacia:"))
            row2.addWidget(self.filter_micro_fs)
            row2.addWidget(QLabel("Eletrônico:"))
            row2.addWidget(self.filter_eletronico_fs)
            row2.addWidget(QLabel("Status:"))
            row2.addWidget(self.filter_status_fs)
            row2.addWidget(QLabel("Ano:"))
            row2.addWidget(self.filter_year_fs)
            row2.addWidget(self.btn_clear_filters_fs)
            row2.addStretch(1)
         
        top_layout.addLayout(row1)
        if self._has_filter_source:
            top_layout.addLayout(row2)
         
        layout.addWidget(top); layout.addWidget(self._content, 1)
        if self._has_filter_source:
            self._copy_filters_from_main()
            self._connect_filter_signals()
        self._capture_table_layout()
        QTimer.singleShot(0, self._expand_table_to_fullscreen)
        self.showMaximized()

    def _find_primary_table(self):
        tables = self._content.findChildren(QTableView)
        if not tables:
            return None
        return max(
            tables,
            key=lambda table: table.model().columnCount() if table.model() else 0
        )

    def _capture_table_layout(self):
        if not self._table:
            return
        header = self._table.horizontalHeader()
        self._original_stretch_last = header.stretchLastSection()
        self._original_resize_modes = [header.sectionResizeMode(i) for i in range(header.count())]
        self._original_section_sizes = [header.sectionSize(i) for i in range(header.count())]

    def _fullscreen_visible_columns(self) -> List[int]:
        if not self._table:
            return []
        return [
            index
            for index in range(self._table.horizontalHeader().count())
            if not self._table.isColumnHidden(index)
        ]

    def _preferred_fullscreen_column_widths(self) -> Optional[Dict[int, int]]:
        if not self._table:
            return None

        header = self._table.horizontalHeader()
        visible_columns = self._fullscreen_visible_columns()
        if not visible_columns:
            return None

        available_width = self._table.viewport().width()
        if available_width <= 0:
            return None

        padding = max(int(28 * getattr(self._mw, "scale_factor", 1.0)), 28)
        min_widths: Dict[int, int] = {}
        weights: Dict[int, float] = {}

        for index in visible_columns:
            header_text = self._table.model().headerData(index, Qt.Horizontal, Qt.DisplayRole) or ""
            header_width = header.fontMetrics().horizontalAdvance(str(header_text)) + padding
            base_width = int(self._FULLSCREEN_COLUMN_BASE_WIDTHS.get(index, 140) * getattr(self._mw, "scale_factor", 1.0))
            min_widths[index] = max(base_width, header_width)
            weights[index] = self._FULLSCREEN_COLUMN_EXTRA_WEIGHTS.get(index, 0.5)

        total_min_width = sum(min_widths.values())
        if total_min_width >= available_width:
            return min_widths

        extra_width = available_width - total_min_width
        total_weight = sum(weights.values()) or 1.0
        return {
            index: int(min_widths[index] + (extra_width * (weights[index] / total_weight)))
            for index in visible_columns
        }

    def _copy_combo_items(self, source: QComboBox, target: QComboBox):
        target.clear()
        for index in range(source.count()):
            target.addItem(source.itemText(index))

    def _copy_checkable_items(self, source: CheckableComboBox, target: CheckableComboBox):
        model = source.model()
        items = [model.item(i).text() for i in range(1, model.rowCount())]
        target.set_items(items)

    def _copy_filters_from_main(self):
        if not self._has_filter_source:
            return
        self._copy_combo_items(self._mw.data_tab.filter_status, self.filter_status_fs)
        self._copy_combo_items(self._mw.data_tab.filter_year, self.filter_year_fs)
        self._copy_checkable_items(self._mw.data_tab.filter_micro, self.filter_micro_fs)
        self._copy_checkable_items(self._mw.data_tab.filter_eletronico, self.filter_eletronico_fs)
        self._sync_filters_from_main()

    def _sync_filters_from_main(self):
        if not self._has_filter_source:
            return
        self._syncing_filters = True
        try:
            self.search_fs.setText(self._mw.search.text())
            self.filter_status_fs.setCurrentText(self._mw.data_tab.filter_status.currentText())
            self.filter_year_fs.setCurrentText(self._mw.data_tab.filter_year.currentText())
            self.filter_micro_fs.set_checked_items(
                self._mw.data_tab.filter_micro.checked_items(),
                all_selected=self._mw.data_tab.filter_micro.is_all_selected(),
            )
            self.filter_eletronico_fs.set_checked_items(
                self._mw.data_tab.filter_eletronico.checked_items(),
                all_selected=self._mw.data_tab.filter_eletronico.is_all_selected(),
            )
        finally:
            self._syncing_filters = False

    def _connect_filter_signals(self):
        if not self._has_filter_source:
            return
        self.search_fs.textChanged.connect(self._apply_filters_to_main)
        self.filter_status_fs.currentTextChanged.connect(self._apply_filters_to_main)
        self.filter_year_fs.currentTextChanged.connect(self._apply_filters_to_main)
        self.filter_micro_fs.currentTextChanged.connect(self._apply_filters_to_main)
        self.filter_eletronico_fs.currentTextChanged.connect(self._apply_filters_to_main)
        self.btn_clear_filters_fs.clicked.connect(self._clear_filters)

    def _clear_filters(self):
        if not self._has_filter_source:
            return
        self._syncing_filters = True
        try:
            self.search_fs.clear()
            self.filter_status_fs.setCurrentIndex(0)
            self.filter_year_fs.setCurrentIndex(0)
            self.filter_micro_fs.select_all()
            self.filter_eletronico_fs.select_all()
        finally:
            self._syncing_filters = False
        self._apply_filters_to_main()

    def _apply_filters_to_main(self, *_args):
        if not self._has_filter_source or self._syncing_filters:
            return

        self._mw.search.blockSignals(True)
        self._mw.data_tab.filter_status.blockSignals(True)
        self._mw.data_tab.filter_year.blockSignals(True)
        self._mw.data_tab.filter_micro.blockSignals(True)
        self._mw.data_tab.filter_eletronico.blockSignals(True)
        try:
            self._mw.search.setText(self.search_fs.text())
            self._mw.data_tab.filter_status.setCurrentText(self.filter_status_fs.currentText())
            self._mw.data_tab.filter_year.setCurrentText(self.filter_year_fs.currentText())
            self._mw.data_tab.filter_micro.set_checked_items(
                self.filter_micro_fs.checked_items(),
                all_selected=self.filter_micro_fs.is_all_selected(),
            )
            self._mw.data_tab.filter_eletronico.set_checked_items(
                self.filter_eletronico_fs.checked_items(),
                all_selected=self.filter_eletronico_fs.is_all_selected(),
            )
        finally:
            self._mw.search.blockSignals(False)
            self._mw.data_tab.filter_status.blockSignals(False)
            self._mw.data_tab.filter_year.blockSignals(False)
            self._mw.data_tab.filter_micro.blockSignals(False)
            self._mw.data_tab.filter_eletronico.blockSignals(False)
        self._mw.apply_filter()

    def _expand_table_to_fullscreen(self):
        if not self._table:
            return
        header = self._table.horizontalHeader()
        header.setStretchLastSection(False)
        preferred_widths = self._preferred_fullscreen_column_widths()
        if not preferred_widths:
            for i in range(header.count()):
                header.setSectionResizeMode(i, QHeaderView.Stretch)
            return

        for i in range(header.count()):
            header.setSectionResizeMode(i, QHeaderView.Interactive)
        for index, width in preferred_widths.items():
            header.resizeSection(index, width)

    def _restore_table_layout(self):
        if not self._table:
            return
        header = self._table.horizontalHeader()
        header.setStretchLastSection(self._original_stretch_last)
        for i, mode in enumerate(self._original_resize_modes):
            header.setSectionResizeMode(i, mode)
        for i, size in enumerate(self._original_section_sizes):
            if self._original_resize_modes[i] == QHeaderView.Interactive:
                header.resizeSection(i, size)

    def closeEvent(self, event):
        if self._on_close_callback:
            self._on_close_callback(self._content)
        QTimer.singleShot(0, self._restore_table_layout)
        super().closeEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._table:
            QTimer.singleShot(0, self._expand_table_to_fullscreen)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Escape, Qt.Key_F11): self.close()
        super().keyPressEvent(event)
