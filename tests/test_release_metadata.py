import subprocess
import sys
from pathlib import Path

from app.services.release_metadata import build_windows_version_info, normalize_version_tuple


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_normalize_version_tuple_pads_to_four_segments():
    assert normalize_version_tuple("1.2") == (1, 2, 0, 0)
    assert normalize_version_tuple("1.2.3") == (1, 2, 3, 0)


def test_normalize_version_tuple_discards_suffix_noise():
    assert normalize_version_tuple("v1.2.3-beta4") == (1, 2, 3, 4)


def test_build_windows_version_info_includes_core_metadata():
    payload = build_windows_version_info("1.2.3", product_name="Compensacoes")

    assert "FileVersion', '1.2.3.0'" in payload
    assert "ProductName', 'Compensacoes'" in payload
    assert "VSVersionInfo(" in payload


def test_generate_version_info_script_supports_direct_execution(tmp_path):
    target = tmp_path / "windows_version_info.txt"

    result = subprocess.run(
        [
            sys.executable,
            "scripts/generate_version_info.py",
            "--output",
            str(target),
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert target.exists()
    assert "VSVersionInfo(" in target.read_text(encoding="utf-8")
