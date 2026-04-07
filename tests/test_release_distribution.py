import subprocess
import sys
from pathlib import Path

from app.services.release_distribution import build_release_guide, build_release_guide_filename


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_build_release_guide_filename_includes_version_and_arch():
    assert build_release_guide_filename("1.2.3") == "Compensacoes-v1.2.3-win64-guide.txt"


def test_build_release_guide_mentions_checksum_for_unsigned_release():
    payload = build_release_guide(
        version="1.2.3-beta.1",
        primary_filename="Compensacoes-v1.2.3-win64.zip",
        hash_filename="Compensacoes-v1.2.3-win64.sha256",
        signed=False,
        homepage_url="https://example.com/app",
    )

    assert "verify_release_checksum.ps1" in payload
    assert "sem assinatura digital do Windows" in payload
    assert "https://example.com/app" in payload
    assert "Canal de distribuicao: beta." in payload
    assert "versao beta/prerelease" in payload


def test_generate_release_guide_script_supports_direct_execution(tmp_path):
    target = tmp_path / "guide.txt"

    result = subprocess.run(
        [
            sys.executable,
            "scripts/generate_release_guide.py",
            "--output",
            str(target),
            "--version",
            "1.2.3",
            "--primary-filename",
            "Compensacoes-v1.2.3-win64.zip",
            "--hash-filename",
            "Compensacoes-v1.2.3-win64.sha256",
            "--signed",
            "true",
            "--signature-mode",
            "pfx",
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    text = target.read_text(encoding="utf-8")
    assert "assinada digitalmente (pfx)" in text
    assert "verify_signature.ps1" in text
