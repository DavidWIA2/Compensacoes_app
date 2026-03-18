import argparse
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import __version__ as APP_VERSION
from app.services.release_notes import (
    DEFAULT_RELEASE_NOTE,
    build_markdown_release_notes,
    build_plain_release_notes,
    parse_git_log_subjects,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Gera notas de release a partir do historico do git.")
    parser.add_argument("--repo-root", default=str(PROJECT_ROOT))
    parser.add_argument("--version", default=APP_VERSION)
    parser.add_argument("--markdown-output", default=str(PROJECT_ROOT / "release" / "release-notes.md"))
    parser.add_argument("--text-output", default=str(PROJECT_ROOT / "release" / "release-notes.txt"))
    parser.add_argument("--previous-ref", default="")
    parser.add_argument("--current-ref", default="HEAD")
    parser.add_argument("--published-at", default="")
    parser.add_argument("--max-entries", type=int, default=20)
    return parser.parse_args()


def _run_git(repo_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "falha ao executar git"
        raise RuntimeError(message)
    return result.stdout.strip()


def _detect_previous_ref(repo_root: Path, current_ref: str) -> str:
    current_tags = {
        line.strip()
        for line in _run_git(repo_root, "tag", "--points-at", current_ref).splitlines()
        if line.strip()
    }
    for tag in _run_git(repo_root, "tag", "--sort=-creatordate").splitlines():
        candidate = tag.strip()
        if candidate and candidate not in current_tags:
            return candidate
    return ""


def _collect_release_entries(repo_root: Path, previous_ref: str, current_ref: str, max_entries: int) -> list[str]:
    args = ["log", "--no-merges", f"--max-count={max_entries}", "--format=%H%x1f%s"]
    if previous_ref:
        args.append(f"{previous_ref}..{current_ref}")
    else:
        args.append(current_ref)
    payload = _run_git(repo_root, *args)
    return parse_git_log_subjects(payload)


def _write_output(path: str, payload: str) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(payload, encoding="utf-8")
    return str(target)


def main() -> int:
    args = _parse_args()
    repo_root = Path(args.repo_root).resolve()
    previous_ref = str(args.previous_ref or "").strip()
    published_at = str(args.published_at or "").strip() or None

    try:
        if not previous_ref:
            previous_ref = _detect_previous_ref(repo_root, args.current_ref)
        entries = _collect_release_entries(repo_root, previous_ref, args.current_ref, max(args.max_entries, 1))
    except Exception as exc:
        print(f"Aviso: usando notas padrao porque nao foi possivel consultar o git: {exc}", file=sys.stderr)
        entries = [DEFAULT_RELEASE_NOTE]
        previous_ref = ""

    markdown = build_markdown_release_notes(
        version=args.version,
        entries=entries,
        published_at=published_at,
    )
    plain = build_plain_release_notes(entries)

    markdown_path = _write_output(args.markdown_output, markdown)
    text_path = _write_output(args.text_output, plain)

    if previous_ref:
        print(f"Notas de release geradas a partir do intervalo {previous_ref}..{args.current_ref}")
    else:
        print(f"Notas de release geradas a partir de {args.current_ref}")
    print(f"Markdown: {markdown_path}")
    print(f"Texto: {text_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
