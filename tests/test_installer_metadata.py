import subprocess
import sys
from pathlib import Path

from app.services.installer_metadata import (
    build_inno_setup_script,
    build_installer_base_filename,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_build_installer_base_filename_includes_version_and_arch():
    assert build_installer_base_filename("1.2.3") == "Compensacoes-Setup-v1.2.3-win64"


def test_build_inno_setup_script_contains_core_sections(tmp_path):
    source_dir = tmp_path / "dist" / "Compensacoes"
    output_dir = tmp_path / "release"
    source_dir.mkdir(parents=True)

    payload = build_inno_setup_script(
        source_dir=str(source_dir),
        output_dir=str(output_dir),
        version="1.2.0",
        base_filename="Compensacoes-Setup-v1.2.0-win64",
        setup_icon_file=str(tmp_path / "app.ico"),
        publisher_url="https://example.com",
        support_url="https://example.com/support",
        updates_url="https://example.com/releases",
    )

    assert "[Setup]" in payload
    assert "ArchitecturesInstallIn64BitMode=x64compatible" in payload
    assert 'Name: "desktopicon"' in payload
    assert 'Filename: "{app}\\{#MyAppExeName}"' in payload
    assert 'AppPublisherURL={#MyAppPublisherURL}' in payload
    assert 'Source: "{#MySetupIconFile}"; DestDir: "{app}"; DestName: "PlataformaGestaoAmbiental.ico"' in payload
    assert 'Type: files; Name: "{app}\\_internal\\assets\\Logo_mono_512.png"' in payload
    assert 'IconFilename: "{app}\\PlataformaGestaoAmbiental.ico"' in payload
    assert 'Check: ShouldInstallDesktopShortcut' in payload
    assert "function ShouldInstallDesktopShortcut(): Boolean;" in payload


def test_build_inno_setup_script_marks_beta_in_display_version(tmp_path):
    source_dir = tmp_path / "dist" / "Compensacoes"
    output_dir = tmp_path / "release"
    source_dir.mkdir(parents=True)

    payload = build_inno_setup_script(
        source_dir=str(source_dir),
        output_dir=str(output_dir),
        version="1.2.0-beta.1",
    )

    assert '#define MyAppVersion "1.2.0-beta.1"' in payload
    assert '#define MyAppVersionLabel "1.2.0-beta.1 (BETA)"' in payload
    assert "AppVerName={#MyAppName} {#MyAppVersionLabel}" in payload


def test_generate_installer_script_supports_direct_execution(tmp_path):
    source_dir = tmp_path / "dist" / "Compensacoes"
    output_dir = tmp_path / "release"
    output_path = tmp_path / "build" / "installer" / "CompensacoesInstaller.iss"
    icon_path = tmp_path / "assets" / "app.ico"
    source_dir.mkdir(parents=True)
    output_dir.mkdir(parents=True)
    icon_path.parent.mkdir(parents=True)
    (source_dir / "Compensacoes.exe").write_bytes(b"stub")
    icon_path.write_bytes(b"ico")

    result = subprocess.run(
        [
            sys.executable,
            "scripts/generate_installer_script.py",
            "--output",
            str(output_path),
            "--source-dir",
            str(source_dir),
            "--output-dir",
            str(output_dir),
            "--version",
            "1.2.0",
            "--setup-icon-file",
            str(icon_path),
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    text = output_path.read_text(encoding="utf-8")
    assert "Compensacoes-Setup-v1.2.0-win64" in text
    assert "Compensacoes.exe" in text
    assert "[Files]" in text
