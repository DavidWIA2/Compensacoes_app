import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from app.config import APP_NAME
from app.services.release_notes import (
    DEFAULT_RELEASE_NOTE,
    build_markdown_release_notes,
    build_plain_release_notes,
    normalize_release_entries,
    parse_git_log_subjects,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_normalize_release_entries_deduplicates_and_keeps_fallback():
    assert normalize_release_entries(["  - Ajuste A  ", "", "* Ajuste A", "Ajuste B"]) == ["Ajuste A", "Ajuste B"]
    assert normalize_release_entries([]) == [DEFAULT_RELEASE_NOTE]


def test_parse_git_log_subjects_supports_hash_separator():
    payload = "\n".join(
        [
            "abc123\x1fCorrige exportacao",
            "def456\x1fMelhora o instalador",
        ]
    )

    assert parse_git_log_subjects(payload) == ["Corrige exportacao", "Melhora o instalador"]


def test_build_release_notes_formats_markdown_and_plain_text():
    entries = ["Corrige exportacao", "Melhora o instalador"]

    markdown = build_markdown_release_notes(version="1.2.0", entries=entries, published_at="2026-03-18T12:00:00Z")
    plain = build_plain_release_notes(entries)

    assert f"# {APP_NAME} 1.2.0" in markdown
    assert "## Novidades" in markdown
    assert "- Corrige exportacao" in markdown
    assert plain == "- Corrige exportacao\n- Melhora o instalador"


@pytest.mark.skipif(shutil.which("git") is None, reason="git nao disponivel")
def test_generate_release_notes_script_supports_direct_execution(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    def run_git(*args: str) -> None:
        result = subprocess.run(
            ["git", *args],
            cwd=repo,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr

    run_git("init")
    run_git("config", "user.name", "Codex Tests")
    run_git("config", "user.email", "codex@example.com")

    tracked = repo / "tracked.txt"
    tracked.write_text("v1\n", encoding="utf-8")
    run_git("add", "tracked.txt")
    run_git("commit", "-m", "Base inicial")
    run_git("tag", "v0.9.0")

    tracked.write_text("v2\n", encoding="utf-8")
    run_git("commit", "-am", "Entrega instalador")

    markdown_output = tmp_path / "release-notes.md"
    text_output = tmp_path / "release-notes.txt"

    result = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "generate_release_notes.py"),
            "--repo-root",
            str(repo),
            "--version",
            "1.0.0",
            "--previous-ref",
            "v0.9.0",
            "--current-ref",
            "HEAD",
            "--markdown-output",
            str(markdown_output),
            "--text-output",
            str(text_output),
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "v0.9.0..HEAD" in result.stdout
    assert "Entrega instalador" in markdown_output.read_text(encoding="utf-8")
    assert "Entrega instalador" in text_output.read_text(encoding="utf-8")
