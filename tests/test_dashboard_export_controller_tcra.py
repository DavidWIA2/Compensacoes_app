from types import SimpleNamespace

from app.ui.controllers.export_controller import ExportController
from app.ui.tabs.dashboard_tab_support import DashboardExportContext


def test_export_dashboard_pdf_uses_tcra_dashboard_context(monkeypatch, tmp_path):
    captured = {}

    class DummyWindow:
        def __init__(self):
            self.settings_controller = SimpleNamespace(preferred_export_dir=lambda: str(tmp_path))
            self.dash_tab = SimpleNamespace(
                current_export_context=lambda: DashboardExportContext(
                    title="Painel TCRA",
                    kpi_lines=("Total de TCRAs: 18", "Alertas: 5"),
                    filter_summary="Agenda TCRA: Prazo vencido: TCRA-2024-001",
                ),
                export_images=lambda: ("pie.png", "bar.png"),
            )

        def _get_save_path(self, *_args, **_kwargs):
            return str(tmp_path / "painel_tcra.pdf")

        def run_blocking_spec(self, spec):
            return spec.operation()

    window = DummyWindow()
    controller = ExportController(window)

    monkeypatch.setattr(
        "app.ui.controllers.export_controller.export_dashboard_pdf",
        lambda path, titulo, kpi_lines, filtros_txt, chart_images: captured.update(
            {
                "path": path,
                "titulo": titulo,
                "kpi_lines": list(kpi_lines),
                "filtros_txt": filtros_txt,
                "chart_images": list(chart_images),
            }
        ),
    )
    monkeypatch.setattr(
        "app.ui.controllers.export_controller.QMessageBox.information",
        lambda *args, **kwargs: None,
    )

    controller.export_dashboard_pdf_clicked()

    assert captured["path"].endswith("painel_tcra.pdf")
    assert captured["titulo"] == "Painel TCRA"
    assert captured["kpi_lines"] == ["Total de TCRAs: 18", "Alertas: 5"]
    assert captured["filtros_txt"] == "Agenda TCRA: Prazo vencido: TCRA-2024-001"
    assert captured["chart_images"] == ["pie.png", "bar.png"]
