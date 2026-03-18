import os
import subprocess
import sys
from pathlib import Path

from app.utils.app_paths import resolve_app_data_dir, resolve_data_path, resolve_logs_dir


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_resolve_app_data_dir_uses_project_root_when_not_frozen(tmp_path):
    result = resolve_app_data_dir(frozen=False, project_root=tmp_path)

    assert result == tmp_path


def test_resolve_app_data_dir_uses_localappdata_when_frozen(tmp_path):
    result = resolve_app_data_dir(frozen=True, local_app_data=tmp_path)

    assert result == tmp_path / "CompensacoesApp" / "CompensacoesDesktop"


def test_resolve_logs_and_data_paths_follow_frozen_storage_root(tmp_path):
    logs_dir = resolve_logs_dir(frozen=True, local_app_data=tmp_path)
    cache_file = resolve_data_path("geocode_cache.json", frozen=True, local_app_data=tmp_path)

    expected_root = tmp_path / "CompensacoesApp" / "CompensacoesDesktop"
    assert logs_dir == expected_root / "logs"
    assert cache_file == expected_root / "data" / "geocode_cache.json"


def test_logger_import_uses_user_writable_dir_in_frozen_mode(tmp_path):
    env = dict(os.environ)
    env["LOCALAPPDATA"] = str(tmp_path)

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import os, sys; "
                "sys.frozen = True; "
                "import app.utils.logger as logger_module; "
                "print(logger_module.LOG_DIR)"
            ),
        ],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert str(tmp_path / "CompensacoesApp" / "CompensacoesDesktop" / "logs") in result.stdout.strip()
