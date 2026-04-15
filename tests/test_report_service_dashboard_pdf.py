import base64

from app.services.report_service import export_dashboard_pdf


def test_export_dashboard_pdf_generates_pdf_with_chart_section(tmp_path):
    png_bytes = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/qxoAAAAASUVORK5CYII="
    )
    pie_path = tmp_path / "pie.png"
    bar_path = tmp_path / "bar.png"
    pie_path.write_bytes(png_bytes)
    bar_path.write_bytes(png_bytes)
    pdf_path = tmp_path / "painel.pdf"

    export_dashboard_pdf(
        str(pdf_path),
        "Painel Geral",
        ["Total geral: 10", "Pendentes: 6"],
        "Status: Todos",
        [str(pie_path), str(bar_path)],
        emitted_by="david.oliveira",
    )

    pdf_bytes = pdf_path.read_bytes()
    assert pdf_bytes.startswith(b"%PDF")
    assert pdf_bytes.count(b"/Type /Page") >= 3
