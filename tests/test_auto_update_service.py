import hashlib
from pathlib import Path

from app.services.auto_update_service import (
    AutoUpdateNotSupported,
    launch_update_installer,
    prepare_staged_update,
    supports_automatic_update,
)


def test_supports_automatic_update_requires_windows_frozen_installer_with_checksum():
    details = {
        "download_url": "https://example.com/Compensacoes-Setup-v1.2.3-win64.exe",
        "filename": "Compensacoes-Setup-v1.2.3-win64.exe",
        "sha256": "abc123",
    }

    assert supports_automatic_update(details, frozen=True, platform_name="nt") is True
    assert supports_automatic_update(details, frozen=False, platform_name="nt") is False
    assert supports_automatic_update(details, frozen=True, platform_name="posix") is False
    assert supports_automatic_update({**details, "sha256": ""}, frozen=True, platform_name="nt") is False
    assert supports_automatic_update({**details, "filename": "Compensacoes-v1.2.3-win64.zip"}, frozen=True, platform_name="nt") is False


def test_prepare_staged_update_downloads_validates_and_writes_launcher(tmp_path):
    content = b"fake-installer-binary"
    checksum = hashlib.sha256(content).hexdigest()

    def fake_download(download_url, destination, progress_callback=None, interruption_requested=None):
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        if progress_callback:
            progress_callback(len(content), len(content))
        return target

    staged = prepare_staged_update(
        {
            "version": "1.2.3",
            "download_url": "https://example.com/Compensacoes-Setup-v1.2.3-win64.exe",
            "filename": "Compensacoes-Setup-v1.2.3-win64.exe",
            "sha256": checksum,
        },
        current_pid=4321,
        current_executable=r"C:\Program Files\Compensacoes\Compensacoes.exe",
        app_data_dir=tmp_path,
        download_fn=fake_download,
    )

    installer_path = Path(staged.installer_path)
    launcher_path = Path(staged.launcher_path)
    script_text = launcher_path.read_text(encoding="utf-8")

    assert installer_path.read_bytes() == content
    assert installer_path.parent == tmp_path / "updates" / "1.2.3"
    assert launcher_path.exists()
    assert "4321" in script_text
    assert "/VERYSILENT" in script_text
    assert "Compensacoes.exe" in script_text
    assert staged.restart_executable.endswith("Compensacoes.exe")


def test_prepare_staged_update_rejects_non_installer_assets(tmp_path):
    details = {
        "version": "1.2.3",
        "download_url": "https://example.com/Compensacoes-v1.2.3-win64.zip",
        "filename": "Compensacoes-v1.2.3-win64.zip",
        "sha256": "abc123",
    }

    try:
        prepare_staged_update(details, current_pid=1, app_data_dir=tmp_path)
    except AutoUpdateNotSupported as exc:
        assert ".exe" in str(exc)
    else:
        raise AssertionError("Era esperado rejeitar artefatos que nao sao instaladores.")


def test_launch_update_installer_uses_detached_powershell(monkeypatch, tmp_path):
    launcher_path = tmp_path / "install_update.ps1"
    launcher_path.write_text("Write-Host 'stub'", encoding="utf-8")
    captured = {}

    def fake_popen(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr("app.services.auto_update_service.subprocess.Popen", fake_popen)

    launch_update_installer(launcher_path, powershell_executable="pwsh.exe")

    assert captured["command"][:4] == ["pwsh.exe", "-NoProfile", "-ExecutionPolicy", "Bypass"]
    assert captured["command"][-1] == str(launcher_path.resolve())
    assert captured["kwargs"]["cwd"] == str(tmp_path.resolve())
