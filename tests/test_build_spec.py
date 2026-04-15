from pathlib import Path


def test_pyinstaller_spec_bundles_dashboard_html() -> None:
    spec_path = Path(__file__).resolve().parents[1] / "Compensacoes.spec"
    spec_text = spec_path.read_text(encoding="utf-8")

    assert "('app/ui/dashboard_echarts.html', 'app/ui')" in spec_text
