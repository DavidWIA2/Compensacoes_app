import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import __version__ as APP_VERSION
from app.services.release_distribution import build_release_guide, build_release_guide_filename


def _parse_bool(value: str) -> bool:
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "y", "sim"}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Gera um guia simples para distribuicao da release.")
    parser.add_argument("--output", default=str(PROJECT_ROOT / "release" / build_release_guide_filename()))
    parser.add_argument("--version", default=APP_VERSION)
    parser.add_argument("--primary-filename", required=True)
    parser.add_argument("--hash-filename", required=True)
    parser.add_argument("--signed", default="false")
    parser.add_argument("--signature-mode", default="")
    parser.add_argument("--homepage-url", default="")
    parser.add_argument("--checksum-script-name", default="verify_release_checksum.ps1")
    parser.add_argument("--signature-script-name", default="verify_signature.ps1")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    payload = build_release_guide(
        version=args.version,
        primary_filename=args.primary_filename,
        hash_filename=args.hash_filename,
        signed=_parse_bool(args.signed),
        signature_mode=args.signature_mode,
        homepage_url=args.homepage_url,
        checksum_script_name=args.checksum_script_name,
        signature_script_name=args.signature_script_name,
    )
    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(payload, encoding="utf-8")
    print(f"Guia de release gerado em: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
