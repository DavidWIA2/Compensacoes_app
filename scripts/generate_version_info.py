import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.release_metadata import build_windows_version_info


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Gera metadados de versao do executavel Windows.")
    parser.add_argument(
        "--output",
        default=str(PROJECT_ROOT / "build" / "windows_version_info.txt"),
        help="Arquivo de saida para o metadata do executavel.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    target = Path(args.output).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(build_windows_version_info(), encoding="utf-8")
    print(f"Arquivo de versao gerado em: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
