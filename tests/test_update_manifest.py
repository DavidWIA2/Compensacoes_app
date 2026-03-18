import json
import subprocess
import sys
from pathlib import Path

from app.services.update_manifest import (
    build_release_manifest,
    normalize_release_notes,
    read_sha256_value,
    write_release_manifest,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_build_release_manifest_includes_optional_metadata():
    payload = build_release_manifest(
        version="1.2.0",
        notes="Linha 1\n\nLinha 2",
        download_url="https://example.com/download.zip",
        sha256="ABC123",
        published_at="2026-03-18T12:00:00Z",
        homepage_url="https://example.com/app",
        filename="download.zip",
        signed=False,
        signature_mode="unsigned",
    )

    assert payload == {
        "version": "1.2.0",
        "notes": "Linha 1\nLinha 2",
        "published_at": "2026-03-18T12:00:00Z",
        "channel": "stable",
        "download_url": "https://example.com/download.zip",
        "homepage_url": "https://example.com/app",
        "filename": "download.zip",
        "sha256": "abc123",
        "signed": False,
        "signature_mode": "unsigned",
    }


def test_normalize_release_notes_removes_blank_lines():
    assert normalize_release_notes("A\n\nB\n") == "A\nB"


def test_write_release_manifest_persists_json(tmp_path):
    target = tmp_path / "latest.json"
    write_release_manifest(str(target), {"version": "1.0.0"})

    assert json.loads(target.read_text(encoding="utf-8")) == {"version": "1.0.0"}


def test_read_sha256_value_reads_hash_prefix(tmp_path):
    path = tmp_path / "artifact.sha256"
    path.write_text("abc123  artifact.zip\n", encoding="utf-8")

    assert read_sha256_value(str(path)) == "abc123"


def test_generate_release_manifest_script_supports_direct_execution(tmp_path):
    hash_file = tmp_path / "artifact.sha256"
    notes_file = tmp_path / "notes.txt"
    target = tmp_path / "latest.json"
    hash_file.write_text("abc123  Compensacoes.zip\n", encoding="utf-8")
    notes_file.write_text("Primeira linha\n\nSegunda linha\n", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "scripts/generate_release_manifest.py",
            "--output",
            str(target),
            "--version",
            "1.3.0",
            "--download-url",
            "https://example.com/Compensacoes.zip",
            "--sha256-file",
            str(hash_file),
            "--notes-file",
            str(notes_file),
            "--homepage-url",
            "https://example.com/app",
            "--filename",
            "Compensacoes.zip",
            "--signed",
            "true",
            "--signature-mode",
            "store-thumbprint",
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["version"] == "1.3.0"
    assert payload["sha256"] == "abc123"
    assert payload["notes"] == "Primeira linha\nSegunda linha"
    assert payload["download_url"] == "https://example.com/Compensacoes.zip"
    assert payload["signed"] is True
    assert payload["signature_mode"] == "store-thumbprint"
