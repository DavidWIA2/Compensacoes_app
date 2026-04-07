import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import __version__ as APP_VERSION
from app.services.update_manifest import (
    build_release_manifest,
    read_sha256_value,
    write_release_manifest,
)


def _parse_optional_bool(value: str):
    text = str(value or "").strip().lower()
    if not text:
        return None
    if text in {"1", "true", "yes", "y", "sim"}:
        return True
    if text in {"0", "false", "no", "n", "nao"}:
        return False
    raise SystemExit(f"Valor invalido para --signed: {value}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Gera o manifest JSON da release.")
    parser.add_argument("--output", default=str(PROJECT_ROOT / "release" / "latest.json"))
    parser.add_argument("--version", default=APP_VERSION)
    parser.add_argument("--download-url", default="")
    parser.add_argument("--homepage-url", default="")
    parser.add_argument("--filename", default="")
    parser.add_argument("--sha256", default="")
    parser.add_argument("--sha256-file", default="")
    parser.add_argument("--notes", default="")
    parser.add_argument("--notes-file", default="")
    parser.add_argument("--published-at", default="")
    parser.add_argument("--channel", default="")
    parser.add_argument("--signed", default="")
    parser.add_argument("--signature-mode", default="")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    notes = args.notes
    if args.notes_file:
        notes = Path(args.notes_file).read_text(encoding="utf-8")

    sha256 = args.sha256
    if args.sha256_file:
        sha256 = read_sha256_value(args.sha256_file)

    payload = build_release_manifest(
        version=args.version,
        notes=notes,
        download_url=args.download_url,
        sha256=sha256,
        published_at=args.published_at or None,
        homepage_url=args.homepage_url,
        filename=args.filename,
        channel=args.channel,
        signed=_parse_optional_bool(args.signed),
        signature_mode=args.signature_mode,
    )
    target = write_release_manifest(args.output, payload)
    print(f"Manifest de release gerado em: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
