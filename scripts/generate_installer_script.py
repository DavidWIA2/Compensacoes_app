import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import __version__ as APP_VERSION
from app.config import (
    APP_COMPANY_NAME,
    APP_EXECUTABLE_NAME,
    APP_INSTALLER_ID,
    APP_NAME,
    APP_PRODUCT_DESCRIPTION,
)
from app.services.installer_metadata import (
    build_inno_setup_script,
    build_installer_base_filename,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Gera o script .iss do instalador Windows.")
    parser.add_argument("--output", default=str(PROJECT_ROOT / "build" / "installer" / "CompensacoesInstaller.iss"))
    parser.add_argument("--source-dir", default=str(PROJECT_ROOT / "dist" / "Compensacoes"))
    parser.add_argument("--output-dir", default=str(PROJECT_ROOT / "release"))
    parser.add_argument("--version", default=APP_VERSION)
    parser.add_argument("--app-name", default=APP_NAME)
    parser.add_argument("--app-publisher", default=APP_COMPANY_NAME)
    parser.add_argument("--app-description", default=APP_PRODUCT_DESCRIPTION)
    parser.add_argument("--main-executable", default=APP_EXECUTABLE_NAME)
    parser.add_argument("--app-id", default=APP_INSTALLER_ID)
    parser.add_argument("--base-filename", default="")
    parser.add_argument("--setup-icon-file", default=str(PROJECT_ROOT / "assets" / "app.ico"))
    parser.add_argument("--publisher-url", default="")
    parser.add_argument("--support-url", default="")
    parser.add_argument("--updates-url", default="")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    source_dir = Path(args.source_dir).resolve()
    output_path = Path(args.output).resolve()
    icon_path = Path(args.setup_icon_file).resolve() if args.setup_icon_file else None
    main_executable = (source_dir / args.main_executable).resolve()

    if not source_dir.exists():
        raise SystemExit(f"Diretorio de origem nao encontrado: {source_dir}")
    if not main_executable.exists():
        raise SystemExit(f"Executavel principal nao encontrado: {main_executable}")
    if icon_path is not None and not icon_path.exists():
        raise SystemExit(f"Icone do instalador nao encontrado: {icon_path}")

    script = build_inno_setup_script(
        source_dir=str(source_dir),
        output_dir=args.output_dir,
        version=args.version,
        app_name=args.app_name,
        app_publisher=args.app_publisher,
        app_description=args.app_description,
        main_executable=args.main_executable,
        app_id=args.app_id,
        base_filename=args.base_filename or build_installer_base_filename(args.version),
        setup_icon_file=str(icon_path) if icon_path is not None else "",
        publisher_url=args.publisher_url,
        support_url=args.support_url,
        updates_url=args.updates_url,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(script, encoding="utf-8")
    print(f"Script do instalador gerado em: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
