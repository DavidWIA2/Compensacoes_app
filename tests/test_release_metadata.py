import subprocess
import sys
from pathlib import Path

from app.services.release_metadata import (
    build_release_display_name,
    build_release_version_label,
    build_windows_version_info,
    is_prerelease_version,
    normalize_version_tuple,
    release_channel_for_version,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_normalize_version_tuple_pads_to_four_segments():
    assert normalize_version_tuple("1.2") == (1, 2, 0, 0)
    assert normalize_version_tuple("1.2.3") == (1, 2, 3, 0)


def test_normalize_version_tuple_discards_suffix_noise():
    assert normalize_version_tuple("v1.2.3-beta4") == (1, 2, 3, 4)


def test_prerelease_helpers_flag_beta_versions():
    assert is_prerelease_version("1.2.3-beta.1") is True
    assert release_channel_for_version("1.2.3-beta.1") == "beta"
    assert build_release_version_label("1.2.3-beta.1") == "1.2.3-beta.1 (BETA)"
    assert build_release_display_name("1.2.3-beta.1", app_name="PGA") == "PGA v1.2.3-beta.1 (BETA)"


def test_build_windows_version_info_includes_core_metadata():
    payload = build_windows_version_info("1.2.3-beta.1", product_name="Compensacoes")

    assert "FileVersion', '1.2.3.0'" in payload
    assert "ProductName', 'Compensacoes'" in payload
    assert "ProductVersion', '1.2.3-beta.1'" in payload
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
