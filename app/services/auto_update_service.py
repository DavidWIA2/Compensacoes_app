from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

from app.config import APP_EXECUTABLE_NAME
from app.utils.app_paths import ensure_dir, resolve_app_data_dir


class AutoUpdateError(RuntimeError):
    """Base error for automatic update operations."""


class AutoUpdateCancelled(AutoUpdateError):
    """Raised when the user cancels the update download."""


class AutoUpdateNotSupported(AutoUpdateError):
    """Raised when the manifest cannot be applied automatically."""


ProgressCallback = Callable[[int, Optional[int]], None]
InterruptCallback = Callable[[], bool]

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True)
class StagedUpdate:
    version: str
    staging_dir: str
    installer_path: str
    launcher_path: str
    log_path: str
    filename: str
    sha256: str
    download_url: str
    restart_executable: str = ""

    def to_payload(self) -> dict[str, str]:
        return asdict(self)


def infer_download_filename(download_url: str, preferred_filename: str = "") -> str:
    candidate = str(preferred_filename or "").strip()
    if not candidate:
        parsed = urlparse(str(download_url or "").strip())
        candidate = unquote(Path(parsed.path).name)
    candidate = candidate or "Compensacoes-Setup-update.exe"
    safe_name = _SAFE_NAME_RE.sub("_", candidate).strip("._")
    return safe_name or "Compensacoes-Setup-update.exe"


def supports_automatic_update(
    details: dict[str, object],
    *,
    frozen: Optional[bool] = None,
    platform_name: str = os.name,
) -> bool:
    if platform_name != "nt":
        return False

    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))
    if not frozen:
        return False

    download_url = str(details.get("download_url") or "").strip()
    if not download_url:
        return False

    filename = infer_download_filename(download_url, str(details.get("filename") or ""))
    if not filename.lower().endswith(".exe"):
        return False

    sha256 = str(details.get("sha256") or "").strip()
    return bool(sha256)


def resolve_update_staging_dir(version: str, *, app_data_dir: str | Path | None = None) -> Path:
    safe_version = _SAFE_NAME_RE.sub("_", str(version or "").strip() or "pending").strip("._") or "pending"
    base_dir = Path(app_data_dir) if app_data_dir else resolve_app_data_dir()
    updates_dir = ensure_dir(base_dir / "updates")
    _cleanup_old_update_directories(updates_dir, keep_name=safe_version)
    staging_dir = updates_dir / safe_version
    if staging_dir.exists():
        _remove_update_directory(staging_dir)
    return ensure_dir(staging_dir)


def _cleanup_old_update_directories(root: Path, *, keep_name: str) -> None:
    if not root.exists():
        return

    candidates = [path for path in root.iterdir() if path.is_dir() and path.name != keep_name]
    for stale_dir in candidates:
        _remove_update_directory(stale_dir)


def _remove_update_directory(path: Path) -> None:
    try:
        shutil.rmtree(path, ignore_errors=False)
    except OSError:
        return


def compute_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().lower()


def verify_sha256(path: str | Path, expected_sha256: str) -> str:
    expected = str(expected_sha256 or "").strip().lower()
    if not expected:
        raise AutoUpdateError("Manifest de atualizacao sem checksum SHA-256.")

    actual = compute_sha256(path)
    if actual != expected:
        raise AutoUpdateError("Checksum SHA-256 da atualizacao nao confere com o manifest.")
    return actual


def download_release_artifact(
    download_url: str,
    destination: str | Path,
    *,
    progress_callback: Optional[ProgressCallback] = None,
    interruption_requested: Optional[InterruptCallback] = None,
    timeout: int = 30,
) -> Path:
    target = Path(destination)
    ensure_dir(target.parent)
    temp_target = target.with_suffix(target.suffix + ".part")
    request = Request(str(download_url).strip(), headers={"User-Agent": "CompensacoesAppAutoUpdater/1.0"})

    downloaded = 0
    total_bytes: Optional[int] = None

    try:
        with urlopen(request, timeout=timeout) as response:
            header_size = response.headers.get("Content-Length")
            if header_size:
                try:
                    total_bytes = int(header_size)
                except ValueError:
                    total_bytes = None

            with temp_target.open("wb") as output:
                while True:
                    if interruption_requested and interruption_requested():
                        raise AutoUpdateCancelled("Download da atualizacao cancelado.")

                    chunk = response.read(1024 * 256)
                    if not chunk:
                        break

                    output.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback:
                        progress_callback(downloaded, total_bytes)

        temp_target.replace(target)
    except AutoUpdateCancelled:
        temp_target.unlink(missing_ok=True)
        raise
    except Exception as exc:
        temp_target.unlink(missing_ok=True)
        raise AutoUpdateError(f"Nao foi possivel baixar a atualizacao: {exc}") from exc

    return target


def write_update_launcher_script(
    installer_path: str | Path,
    *,
    launcher_path: str | Path,
    current_pid: int,
    restart_executable: str = "",
    log_path: str | Path = "",
) -> Path:
    installer = Path(installer_path).resolve()
    launcher = Path(launcher_path).resolve()
    staging_dir = launcher.parent.resolve()
    log_target = Path(log_path).resolve() if log_path else launcher.with_name("install-update.log")
    restart_target = str(restart_executable or "").strip()

    script = f"""$ErrorActionPreference = 'Stop'
$installerPath = '{_ps_literal(str(installer))}'
$stagingDir = '{_ps_literal(str(staging_dir))}'
$restartExecutable = '{_ps_literal(restart_target)}'
$logPath = '{_ps_literal(str(log_target))}'
$pidToWait = {int(current_pid)}
$arguments = @('/SILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-', '/NOCANCEL', '/CLOSEAPPLICATIONS', '/FORCECLOSEAPPLICATIONS')

function Write-UpdateLog([string]$message) {{
    if (-not $logPath) {{
        return
    }}

    $timestamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    Add-Content -Path $logPath -Value "[$timestamp] $message"
}}

function Start-UpdateCleanup() {{
    if (-not $stagingDir) {{
        return
    }}

    $cleanupArgs = '/c timeout /t 3 /nobreak >nul & if exist "{0}" rmdir /s /q "{0}"' -f $stagingDir
    Start-Process -FilePath 'cmd.exe' -ArgumentList $cleanupArgs -WindowStyle Hidden | Out-Null
}}

try {{
    Write-UpdateLog "Aguardando o encerramento do aplicativo (PID $pidToWait)."
    Write-UpdateLog "Caminho de reinicio: $restartExecutable"
    while (Get-Process -Id $pidToWait -ErrorAction SilentlyContinue) {{
        Start-Sleep -Milliseconds 500
    }}

    Write-UpdateLog "Iniciando instalador silencioso: $installerPath"
    # Start-Process com -Verb RunAs pode retornar null se o UAC for aceito mas o processo nao for capturado imediatamente
    $installProcess = Start-Process -FilePath $installerPath -ArgumentList $arguments -Wait -PassThru -Verb RunAs
    
    if ($installProcess) {{
        Write-UpdateLog ("Instalador finalizado com codigo {{0}}." -f $installProcess.ExitCode)
        $exitCode = $installProcess.ExitCode
    }} else {{
        Write-UpdateLog "Instalador iniciado (processo elevado, aguardando conclusao via arquivo se possivel)."
        $exitCode = 0
    }}

    if ($exitCode -eq 0) {{
        Write-UpdateLog "Instalacao concluida com sucesso. Agendando limpeza dos arquivos temporarios."
        if ($restartExecutable -and (Test-Path $restartExecutable)) {{
            Write-UpdateLog "Relancando aplicativo atualizado."
            Start-Process -FilePath $restartExecutable -WorkingDirectory ([System.IO.Path]::GetDirectoryName($restartExecutable))
        }}
        Start-UpdateCleanup
    }} else {{
        Write-UpdateLog ("Instalacao retornou codigo de falha {{0}}." -f $exitCode)
        exit $exitCode
    }}
}} catch {{
    Write-UpdateLog "ERRO FATAL DURANTE A ATUALIZACAO: $_"
    exit 1
}}

exit $exitCode
"""

    ensure_dir(launcher.parent)
    launcher.write_text(script, encoding="utf-8")
    return launcher


def launch_update_installer(launcher_path: str | Path, *, powershell_executable: str = "powershell.exe") -> None:
    command = [
        powershell_executable,
        "-NoProfile",
        "-WindowStyle",
        "Hidden",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(Path(launcher_path).resolve()),
    ]
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)

    try:
        if os.name == "nt":
            subprocess.Popen(
                command,
                cwd=str(Path(launcher_path).resolve().parent),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
            )
        else:
            subprocess.Popen(
                command,
                cwd=str(Path(launcher_path).resolve().parent),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
    except OSError as exc:
        raise AutoUpdateError(f"Nao foi possivel iniciar o instalador da atualizacao: {exc}") from exc


def prepare_staged_update(
    details: dict[str, object],
    *,
    current_pid: int,
    current_executable: str = "",
    app_data_dir: str | Path | None = None,
    progress_callback: Optional[ProgressCallback] = None,
    interruption_requested: Optional[InterruptCallback] = None,
    download_fn: Callable[..., Path] = download_release_artifact,
) -> StagedUpdate:
    version = str(details.get("version") or "").strip()
    download_url = str(details.get("download_url") or "").strip()
    filename = infer_download_filename(download_url, str(details.get("filename") or ""))
    sha256 = str(details.get("sha256") or "").strip().lower()

    if not version:
        raise AutoUpdateError("Manifest de atualizacao sem versao valida.")
    if not download_url:
        raise AutoUpdateError("Manifest de atualizacao sem link de download.")
    if not filename.lower().endswith(".exe"):
        raise AutoUpdateNotSupported("A atualizacao automatica requer um instalador .exe.")
    if not sha256:
        raise AutoUpdateNotSupported("A atualizacao automatica requer checksum SHA-256 no manifest.")

    staging_dir = resolve_update_staging_dir(version, app_data_dir=app_data_dir)
    installer_path = staging_dir / filename
    launcher_path = staging_dir / "install_update.ps1"
    log_path = staging_dir / "install_update.log"
    restart_executable = _resolve_restart_executable(current_executable)

    download_fn(
        download_url,
        installer_path,
        progress_callback=progress_callback,
        interruption_requested=interruption_requested,
    )
    verify_sha256(installer_path, sha256)
    write_update_launcher_script(
        installer_path,
        launcher_path=launcher_path,
        current_pid=current_pid,
        restart_executable=restart_executable,
        log_path=log_path,
    )

    return StagedUpdate(
        version=version,
        staging_dir=str(staging_dir),
        installer_path=str(installer_path),
        launcher_path=str(launcher_path),
        log_path=str(log_path),
        filename=filename,
        sha256=sha256,
        download_url=download_url,
        restart_executable=restart_executable,
    )


def _resolve_restart_executable(current_executable: str) -> str:
    candidate = str(current_executable or "").strip()
    if not candidate:
        return ""

    path = Path(candidate)
    if path.name.lower() != APP_EXECUTABLE_NAME.lower():
        return ""
    return str(path.resolve())


def _ps_literal(value: str) -> str:
    return str(value or "").replace("'", "''")
