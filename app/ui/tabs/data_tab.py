import os
from typing import List, Dict, Optional

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QIntValidator, QDoubleValidator, QStandardItemModel, QStandardItem
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QTableView, QHeaderView,
    QGroupBox, QGridLayout, QLabel, QLineEdit, QCheckBox, QComboBox,
    QPushButton, QSizePolicy, QButtonGroup,
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEngineSettings

from app.models.display_columns import display_column_index
from app.ui.components.widgets import CheckableComboBox, NumericSortProxy, MapBridge, DebugPage
from app.ui.components.model import CompensacoesTableModel
from app.ui.components.ui_utils import resource_path


class DataTab(QWidget):
    OFICIO_COLUMN_INDEX = display_column_index("oficio_processo")
    TIPO_COLUMN_INDEX = display_column_index("eletronico")
    PLANTIO_COLUMN_INDEX = display_column_index("endereco_plantio")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = parent
        self.sf = getattr(parent, "scale_factor", 1.0)
        self._map_loaded = False
        self._locked_table_height: Optional[int] = None
        self._locked_splitter_height: Optional[int] = None
        self.setup_ui()

    def showEvent(self, event):
        super().showEvent(event)
        if not self._map_loaded:
            self.load_map()
        self._update_form_group_height()
        self._sync_left_panel_heights()
        self._update_responsive_constraints()
        QTimer.singleShot(0, self.align_splitter_to_table_width)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_form_group_height()
        self._sync_left_panel_heights()
        self._update_responsive_constraints()

    def setup_ui(self):
        panel_gap = max(int(10 * self.sf), 8)
        panel_bottom_gap = max(int(12 * self.sf), 12)
        self._panel_gap = panel_gap
        layout = QVBoxLayout(self)
        layout.setContentsMargins(int(10 * self.sf), int(10 * self.sf), int(10 * self.sf), int(10 * self.sf))
        layout.setSpacing(int(10 * self.sf))

        filters = QHBoxLayout()
        filters.setSpacing(int(15 * self.sf))

        def mk_f(lbl, w):
            v = QVBoxLayout()
            v.setSpacing(int(2 * self.sf))
            l = QLabel(lbl)
            l.setStyleSheet(f"font-size: {int(10 * self.sf)}px; font-weight: 800; color: #888;")
            v.addWidget(l)
            v.addWidget(w)
            filters.addLayout(v)

        self.filter_micro = CheckableComboBox("Todas as Microbacias")
        self.filter_micro.setMinimumWidth(int(220 * self.sf))
        self.filter_eletronico = CheckableComboBox("Todos os Tipos")
        self.filter_eletronico.setMinimumWidth(int(140 * self.sf))
        self.filter_status = QComboBox()
        self.filter_status.addItems(["Todos", "Compensados", "Pendentes"])
        self.filter_status.setMinimumWidth(int(130 * self.sf))
        self.filter_year = QComboBox()
        self.filter_year.addItem("Todos")
        self.filter_year.setMinimumWidth(int(90 * self.sf))

        self.btn_clear_filters = QPushButton("Limpar Filtros")
        self.btn_reset_sort = QPushButton("Redefinir Ordem")
        self.btn_columns = QPushButton("Colunas Visíveis")
        self.btn_table_full = QPushButton("Tabela Tela Cheia")
        for b in [self.btn_clear_filters, self.btn_reset_sort, self.btn_columns, self.btn_table_full]:
            b.setProperty("kind", "secondary")
            b.setMinimumHeight(int(28 * self.sf))

        mk_f("MICROBACIAS", self.filter_micro)
        mk_f("TIPO", self.filter_eletronico)
        mk_f("STATUS", self.filter_status)
        mk_f("ANO", self.filter_year)

        btns = QHBoxLayout()
        btns.setSpacing(int(6 * self.sf))
        btns.setContentsMargins(0, int(14 * self.sf), 0, 0)
        btns.addWidget(self.btn_clear_filters)
        btns.addWidget(self.btn_reset_sort)
        btns.addWidget(self.btn_columns)
        btns.addWidget(self.btn_table_full)
        filters.addLayout(btns)
        filters.addStretch(1)
        self.lbl_results = QLabel("0 registros")
        self.lbl_results.setContentsMargins(0, int(14 * self.sf), 0, 0)
        filters.addWidget(self.lbl_results)
        layout.addLayout(filters)

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(int(8 * self.sf))
        self.splitter.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
        layout.addWidget(self.splitter, 1)

        self.left_panel = QWidget()
        self.left_panel.setMinimumHeight(0)
        self.left_panel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Ignored)
        l_lay = QVBoxLayout(self.left_panel)
        l_lay.setContentsMargins(0, 0, panel_gap, panel_bottom_gap)
        l_lay.setSpacing(int(8 * self.sf))
        self.table_model = CompensacoesTableModel()
        self.proxy = NumericSortProxy()
        self.proxy.setSourceModel(self.table_model)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setSelectionMode(QTableView.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setMinimumHeight(0)
        self.table.setMinimumWidth(0)
        self.table.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self._resize_column_to_texts(self.TIPO_COLUMN_INDEX, ["Eletrônico", "Ofício", "Físico", "Nulo"])
        self._resize_column_to_texts(self.PLANTIO_COLUMN_INDEX, [])
        l_lay.addWidget(self.table, 1)

        self.group_totals = self._create_totals_group()
        l_lay.addWidget(self.group_totals)
        self.bar_export = self._create_export_bar()
        l_lay.addWidget(self.bar_export)
        self.splitter.addWidget(self.left_panel)

        self.right_panel = QWidget()
        self.right_panel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Ignored)
        r_lay = QVBoxLayout(self.right_panel)
        r_lay.setContentsMargins(panel_gap, 0, 0, 0)
        r_lay.setSpacing(int(8 * self.sf))
        self.form_group = self._create_form_group()
        self._update_form_group_height()
        r_lay.addWidget(self.form_group, 0)

        crud = QHBoxLayout()
        crud.setContentsMargins(0, int(8 * self.sf), 0, 0)
        crud.setSpacing(int(8 * self.sf))
        self._crud_spacing = crud.spacing()
        self.btn_clear = QPushButton("Limpar Form")
        self.btn_add = QPushButton("Adicionar")
        self.btn_save_edit = QPushButton("Salvar")
        self.btn_delete = QPushButton("Excluir")
        self.btn_ficha_pdf = QPushButton("Gerar Ficha")
        self.btn_add.setProperty("kind", "success")
        self.btn_save_edit.setProperty("kind", "primary")
        self.btn_delete.setProperty("kind", "danger")
        self.btn_clear.setProperty("kind", "secondary")
        self.btn_ficha_pdf.setProperty("kind", "secondary")
        for b in [self.btn_clear, self.btn_add, self.btn_save_edit, self.btn_delete, self.btn_ficha_pdf]:
            b.setMinimumHeight(int(30 * self.sf))
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            crud.addWidget(b)
        r_lay.addLayout(crud)

        self.map_group = self._create_map_group()
        r_lay.addWidget(self.map_group)

        self.web = QWebEngineView()
        self.web.setMinimumHeight(int(350 * self.sf))
        self.web.setPage(DebugPage(self.web))
        s = self.web.page().settings()
        s.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
        s.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
        self.channel = QWebChannel(self.web.page())
        self.bridge = MapBridge(
            getattr(self.main_window, "_on_map_click", None) if self.main_window else None,
            getattr(self.main_window, "save_map_layer_preference", None) if self.main_window else None,
        )
        self.channel.registerObject("bridge", self.bridge)
        self.web.page().setWebChannel(self.channel)

        r_lay.addWidget(self.web, 1)
        self.splitter.addWidget(self.right_panel)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)
        self._update_responsive_constraints()
        self.splitter.setSizes([max(int(980 * self.sf), 720), self.right_panel.minimumWidth()])
        QTimer.singleShot(0, self._sync_left_panel_heights)
        QTimer.singleShot(0, self._update_responsive_constraints)
        QTimer.singleShot(0, self.align_splitter_to_table_width)

    def _sync_left_panel_heights(self):
        if not hasattr(self, "left_panel") or not self.left_panel:
            return

        layout = self.left_panel.layout()
        if layout is None:
            return

        margins = layout.contentsMargins()
        available = self.left_panel.height() - margins.top() - margins.bottom()
        if available <= 0:
            return

        fixed_children_height = 0
        if hasattr(self, "group_totals") and self.group_totals:
            fixed_children_height += self.group_totals.height() or self.group_totals.sizeHint().height()
        if hasattr(self, "bar_export") and self.bar_export:
            fixed_children_height += self.bar_export.height() or self.bar_export.sizeHint().height()

        spacing_count = max(layout.count() - 1, 0)
        available_table_height = available - fixed_children_height - (layout.spacing() * spacing_count)
        target_height = max(available_table_height, 0)
        if self._locked_table_height is not None:
            target_height = min(target_height, self._locked_table_height)
            self.table.setMinimumHeight(0)
            self.table.setMaximumHeight(target_height)
            return

        self.table.setMinimumHeight(0)
        self.table.setMaximumHeight(target_height)

    def lock_table_height(self):
        current_height = self.table.height()
        if current_height <= 0:
            return

        self._locked_table_height = current_height
        self.table.setFixedHeight(self._locked_table_height)

    def lock_splitter_height(self):
        current_height = self.splitter.height()
        if current_height <= 0:
            return

        self._locked_splitter_height = current_height
        self.splitter.setFixedHeight(current_height)

    def preferred_left_panel_width(self) -> int:
        header = self.table.horizontalHeader()
        visible_columns_width = sum(
            header.sectionSize(index)
            for index in range(header.count())
            if not self.table.isColumnHidden(index)
        )
        table_chrome_width = (
            self.table.verticalHeader().width()
            + (self.table.frameWidth() * 2)
            + self.table.verticalScrollBar().sizeHint().width()
        )
        totals_min_width = self.group_totals.minimumSizeHint().width()
        export_min_width = self.bar_export.minimumSizeHint().width()
        return max(
            visible_columns_width + table_chrome_width + self._panel_gap,
            totals_min_width + self._panel_gap,
            export_min_width + self._panel_gap,
        )

    def _crud_buttons_minimum_width(self) -> int:
        buttons = [self.btn_clear, self.btn_add, self.btn_save_edit, self.btn_delete, self.btn_ficha_pdf]
        return sum(button.minimumSizeHint().width() for button in buttons) + (self._crud_spacing * (len(buttons) - 1))

    def preferred_right_panel_width(self) -> int:
        widths = [max(int(620 * self.sf), 560)]
        if hasattr(self, "map_group"):
            widths.append(self.map_group.minimumSizeHint().width())
        if hasattr(self, "btn_ficha_pdf"):
            widths.append(self._crud_buttons_minimum_width())
        return max(widths)

    def _update_responsive_constraints(self):
        if not hasattr(self, "right_panel"):
            return
        self.right_panel.setMinimumWidth(self.preferred_right_panel_width())

    def align_splitter_to_table_width(self):
        if not hasattr(self, "splitter") or self.splitter.count() < 2:
            return

        sizes = self.splitter.sizes()
        total_width = sum(sizes)
        if total_width <= 0:
            return

        self._update_responsive_constraints()
        right_min_width = self.right_panel.minimumWidth()
        target_left_width = min(
            max(self.preferred_left_panel_width(), 0),
            max(total_width - right_min_width, 0),
        )
        if target_left_width <= 0:
            return

        self.splitter.setSizes([target_left_width, max(total_width - target_left_width, 0)])

    def _resize_column_to_texts(self, column_index: int, texts: List[str]):
        header = self.table.horizontalHeader()
        if column_index < 0 or column_index >= header.count():
            return

        header_text = self.table_model.headerData(column_index, Qt.Horizontal, Qt.DisplayRole) or ""
        widths = [header.fontMetrics().horizontalAdvance(str(header_text))]
        widths.extend(self.table.fontMetrics().horizontalAdvance(str(text or "")) for text in texts)
        target_width = max(widths) + max(int(28 * self.sf), 28)
        header.resizeSection(column_index, target_width)

    def load_map(self):
        self._map_loaded = True
        map_html = resource_path("app", "ui", "map_leaflet.html")
        if os.path.exists(map_html):
            url = QUrl.fromLocalFile(map_html)
            url.setQuery("tileScheme=compmap")
            self.web.setUrl(url)

    def _create_totals_group(self):
        g = QGroupBox("Totais (Filtro Atual)")
        l = QHBoxLayout(g)
        l.setContentsMargins(int(8 * self.sf), int(10 * self.sf), int(8 * self.sf), int(8 * self.sf))
        l.setSpacing(int(8 * self.sf))
        self.kpi_table = QTableView()
        self.kpi_model = QStandardItemModel(0, 2)
        self.kpi_model.setHorizontalHeaderLabels(["Métrica", "Valor"])
        self.kpi_table.setModel(self.kpi_model)
        self.kpi_table.horizontalHeader().setStretchLastSection(True)
        self.kpi_table.setMinimumHeight(int(120 * self.sf))
        self.micro_table = QTableView()
        self.micro_model = QStandardItemModel(0, 2)
        self.micro_model.setHorizontalHeaderLabels(["Microbacia", "Pendente"])
        self.micro_table.setModel(self.micro_model)
        self.micro_table.horizontalHeader().setStretchLastSection(True)
        self.micro_table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.micro_table.setMinimumHeight(int(120 * self.sf))
        l.addWidget(self.kpi_table, 1)
        l.addWidget(self.micro_table, 1)
        g.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        g.setFixedHeight(max(int(230 * self.sf), 200))
        return g

    def update_totals_tables(self, metrics: Dict):
        self.kpi_model.removeRows(0, self.kpi_model.rowCount())
        rows = [
            ("Total Mudas", f"{metrics['total_geral']:g}"),
            ("Pendente", f"{metrics['total_pendente']:g}"),
            ("Compensado", f"{metrics['total_compensado']:g}"),
        ]
        for k, v in rows:
            self.kpi_model.appendRow([QStandardItem(k), QStandardItem(v)])
        self.micro_model.removeRows(0, self.micro_model.rowCount())
        for m, v in metrics["pend_micro_sorted"]:
            self.micro_model.appendRow([QStandardItem(m), QStandardItem(f"{v:g}")])

    def _create_export_bar(self):
        w = QWidget()
        w.setFixedHeight(int(46 * self.sf))
        l = QHBoxLayout(w)
        l.setContentsMargins(0, 0, 0, 0)
        l.setSpacing(int(8 * self.sf))
        self.btn_export_csv = QPushButton("Exportar CSV")
        self.btn_export_excel = QPushButton("Exportar Excel (2 abas)")
        self.btn_export_pdf = QPushButton("Exportar PDF")
        for b in [self.btn_export_csv, self.btn_export_excel, self.btn_export_pdf]:
            b.setProperty("kind", "secondary")
            b.setMinimumHeight(int(28 * self.sf))
            l.addWidget(b)
        l.addStretch(1)
        return w

    def _create_form_group(self):
        top_margin = max(int(14 * self.sf), 14)
        row_spacing = max(int(10 * self.sf), 10)
        column_spacing = max(int(10 * self.sf), 8)
        input_h = max(int(30 * self.sf), 30)
        label_w = max(int(112 * self.sf), 96)
        primary_field_w = max(int(190 * self.sf), 140)
        secondary_field_w = max(int(150 * self.sf), 110)
        aux_col_w = max(int(108 * self.sf), 90)

        g = QGroupBox("Cadastro / Edição")
        g.setObjectName("formGroup")
        l = QGridLayout(g)
        l.setContentsMargins(int(15 * self.sf), top_margin, int(15 * self.sf), int(10 * self.sf))
        l.setHorizontalSpacing(column_spacing)
        l.setVerticalSpacing(row_spacing)

        def mk_lbl(t):
            lbl = QLabel(t)
            lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            lbl.setMinimumWidth(label_w)
            lbl.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
            return lbl

        def mk_in(min_width):
            le = QLineEdit()
            le.setFixedHeight(input_h)
            le.setMinimumWidth(min_width)
            le.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            return le

        self.in_oficio = mk_in(primary_field_w)
        self.chk_sn = QCheckBox("S/N")
        self.chk_sn.setFixedWidth(aux_col_w)

        self.in_avtec = mk_in(secondary_field_w)
        self.in_comp = mk_in(secondary_field_w)
        self.in_comp.setValidator(QDoubleValidator(0, 9999999, 2))
        self.in_end = mk_in(primary_field_w)
        self.in_end_plantio = mk_in(primary_field_w)
        self.in_end_plantio.setReadOnly(True)
        self.in_end_plantio.setEnabled(False)
        self.in_end_plantio.setPlaceholderText("Nenhum plantio cadastrado")
        self.in_end_plantio.setMinimumWidth(max(int(220 * self.sf), 170))
        self.btn_manage_plantios = QPushButton("Plantios...")
        self.btn_manage_plantios.setProperty("kind", "secondary")
        self.btn_manage_plantios.setFixedHeight(input_h)
        plantio_button_w = max(int(132 * self.sf), 122)
        self.btn_manage_plantios.setMinimumWidth(plantio_button_w)
        self.btn_manage_plantios.setEnabled(False)
        self.plantio_summary_container = QWidget()
        self.plantio_summary_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.plantio_summary_layout = QHBoxLayout(self.plantio_summary_container)
        self.plantio_summary_layout.setContentsMargins(0, 0, 0, 0)
        self.plantio_summary_layout.setSpacing(0)
        self.plantio_summary_layout.addWidget(self.in_end_plantio, 1)
        self.plantio_actions_container = QWidget()
        self.plantio_actions_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.plantio_actions_layout = QHBoxLayout(self.plantio_actions_container)
        self.plantio_actions_layout.setContentsMargins(0, 0, 0, 0)
        self.plantio_actions_layout.setSpacing(int(10 * self.sf))
        self.in_micro = QComboBox()
        self.in_micro.setEditable(True)
        self.in_micro.setFixedHeight(input_h)
        self.in_micro.setMinimumWidth(secondary_field_w)
        self.in_micro.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.in_caixa = mk_in(secondary_field_w)
        self.in_caixa.setValidator(QIntValidator(0, 999999))
        self.chk_arquivado = QCheckBox("Arquivado")
        self.chk_compensado = QCheckBox("Compensado (SIM)")
        self.plantio_actions_layout.addWidget(self.btn_manage_plantios, 0, Qt.AlignLeft | Qt.AlignVCenter)
        self.plantio_actions_layout.addWidget(self.chk_compensado, 0, Qt.AlignLeft | Qt.AlignVCenter)
        self.plantio_actions_layout.addStretch(1)

        self.eletronico_cont = QWidget()
        self.eletronico_cont.setFixedHeight(input_h)
        self.eletronico_cont.setMinimumWidth(primary_field_w + aux_col_w)
        self.eletronico_layout = QHBoxLayout(self.eletronico_cont)
        self.eletronico_layout.setContentsMargins(0, 0, 0, 0)
        self.eletronico_layout.setSpacing(int(10 * self.sf))
        self.eletronico_group = QButtonGroup(self)
        self.eletronico_group.setExclusive(True)

        lbl_oficio = mk_lbl("Ofício/Processo:")
        lbl_avtec = mk_lbl("Av. Tec.:")
        lbl_eletronico = mk_lbl("Tipo:")
        lbl_compensacao = mk_lbl("Compensação:")
        lbl_endereco = mk_lbl("Endereço:")
        lbl_microbacia = mk_lbl("Microbacia:")
        lbl_endereco_plantio = mk_lbl("Endereço Plantio:")
        lbl_caixa = mk_lbl("Caixa:")

        l.addWidget(lbl_oficio, 0, 0)
        l.addWidget(self.in_oficio, 0, 1)
        l.addWidget(self.chk_sn, 0, 2, Qt.AlignLeft | Qt.AlignVCenter)
        l.addWidget(lbl_avtec, 0, 3)
        l.addWidget(self.in_avtec, 0, 4)

        l.addWidget(lbl_eletronico, 1, 0)
        l.addWidget(self.eletronico_cont, 1, 1, 1, 2)
        l.addWidget(lbl_compensacao, 1, 3)
        l.addWidget(self.in_comp, 1, 4)

        l.addWidget(lbl_endereco, 2, 0)
        l.addWidget(self.in_end, 2, 1, 1, 2)
        l.addWidget(lbl_microbacia, 2, 3)
        l.addWidget(self.in_micro, 2, 4)

        l.addWidget(lbl_endereco_plantio, 3, 0)
        l.addWidget(self.plantio_summary_container, 3, 1, 1, 2)
        l.addWidget(lbl_caixa, 3, 3)
        l.addWidget(self.in_caixa, 3, 4)

        l.addWidget(self.plantio_actions_container, 4, 1, 1, 2)
        l.addWidget(self.chk_arquivado, 4, 4)

        l.setColumnMinimumWidth(0, label_w)
        l.setColumnMinimumWidth(1, primary_field_w)
        l.setColumnMinimumWidth(2, aux_col_w + int(10 * self.sf))
        l.setColumnMinimumWidth(3, label_w)
        l.setColumnMinimumWidth(4, secondary_field_w)
        l.setRowMinimumHeight(0, input_h)
        l.setRowMinimumHeight(1, input_h)
        l.setRowMinimumHeight(2, input_h)
        l.setRowMinimumHeight(3, input_h)
        l.setColumnStretch(1, 1)
        l.setColumnStretch(2, 0)
        l.setColumnStretch(4, 1)
        g.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        return g

    def _update_form_group_height(self):
        if not hasattr(self, "form_group") or self.form_group is None:
            return

        target_height = self.form_group.minimumSizeHint().height()
        if target_height > 0 and self.form_group.minimumHeight() != target_height:
            self.form_group.setMinimumHeight(target_height)

    def _create_map_group(self):
        g = QGroupBox("Mapa")
        l = QGridLayout(g)
        l.setContentsMargins(int(10 * self.sf), int(10 * self.sf), int(10 * self.sf), int(10 * self.sf))
        l.setHorizontalSpacing(int(8 * self.sf))
        l.setVerticalSpacing(int(6 * self.sf))
        self.btn_maps = QPushButton("Buscar Endereço")
        self.btn_maps_plantio = QPushButton("Buscar Plantio")
        self.btn_batch_geo = QPushButton("GPS em Lote")
        self.btn_map_full = QPushButton("Mapa Tela Cheia")
        self.btn_street_view = QPushButton("Street View")
        self.btn_add_layer = QPushButton("Adicionar Camada GIS")
        self.btn_add_layer.setToolTip("Adicione camadas externas ao mapa (.geojson, .json ou .kml)")
        self.chk_heatmap = QCheckBox("Mapa de Calor")
        self.combo_heatmap_type = QComboBox()
        self.combo_heatmap_type.addItems(["Pendentes", "Realizadas", "Tudo"])
        self.combo_heatmap_type.setMinimumWidth(max(int(150 * self.sf), 120))
        self.map_notice_label = QLabel("")
        self.map_notice_label.setObjectName("MapNoticeLabel")
        self.map_notice_label.setWordWrap(True)
        self.map_notice_label.setVisible(False)
        for b in [self.btn_maps, self.btn_maps_plantio, self.btn_batch_geo, self.btn_map_full, self.btn_street_view, self.btn_add_layer]:
            b.setMinimumHeight(int(24 * self.sf))
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            b.setProperty("kind", "secondary")
        l.addWidget(self.btn_maps, 0, 0)
        l.addWidget(self.btn_maps_plantio, 0, 1)
        l.addWidget(self.btn_batch_geo, 1, 0)
        l.addWidget(self.btn_map_full, 1, 1)
        l.addWidget(self.btn_street_view, 2, 0)
        l.addWidget(self.btn_add_layer, 2, 1)
        l.addWidget(self.chk_heatmap, 3, 0)
        l.addWidget(self.combo_heatmap_type, 3, 1)
        l.addWidget(self.map_notice_label, 4, 0, 1, 2)
        l.setColumnStretch(0, 1)
        l.setColumnStretch(1, 1)
        return g

    def set_map_notice(self, message: str = ""):
        text = str(message or "").strip()
        self.map_notice_label.setText(text)
        self.map_notice_label.setVisible(bool(text))
