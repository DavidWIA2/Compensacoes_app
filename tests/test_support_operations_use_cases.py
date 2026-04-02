from pathlib import Path

from app.application.use_cases.support_operations import SupportOperationsUseCases


def build_use_cases(snapshot=None, writer_calls=None):
    snapshot = dict(snapshot or {"app": {"version": "1.0.0"}})
    writer_calls = writer_calls if writer_calls is not None else []

    def snapshot_builder(_context):
        return dict(snapshot)

    def report_writer(path, payload):
        writer_calls.append((path, dict(payload)))
        Path(path).write_text("{}", encoding="utf-8")

    return SupportOperationsUseCases(
        app_name="Compensacoes",
        app_version="1.2.3",
        log_dir="C:/logs",
        update_url_env_var="COMPENSACOES_UPDATE_URL",
        manifest_url_resolver=lambda: "https://example.com/manifest.json",
        default_diagnostics_filename_builder=lambda: "diag.json",
        diagnostics_snapshot_builder=snapshot_builder,
        diagnostics_report_writer=report_writer,
        python_version_resolver=lambda: "3.12.0",
    )


def test_support_operations_build_about_dialog_data():
    use_cases = build_use_cases()

    about = use_cases.build_about_dialog_data()

    assert about.title == "Sobre o Compensacoes"
    assert "Compensacoes 1.2.3" in about.message
    assert "Python 3.12.0" in about.message
    assert "Manifest de atualizacao: https://example.com/manifest.json" in about.message
    assert "Variavel de override: COMPENSACOES_UPDATE_URL" in about.message


def test_support_operations_export_diagnostics_snapshot(tmp_path):
    writer_calls = []
    use_cases = build_use_cases(snapshot={"session": {"records_total": 2}}, writer_calls=writer_calls)
    target = tmp_path / "diag.json"

    result = use_cases.export_diagnostics_snapshot(object(), str(target))

    assert result.path == str(target)
    assert result.snapshot == {"session": {"records_total": 2}}
    assert writer_calls == [(str(target), {"session": {"records_total": 2}})]
    assert target.exists()


def test_support_operations_build_update_offer_presentations():
    use_cases = build_use_cases()

    automatic = use_cases.build_update_offer_presentation(
        {
            "version": "1.1.0",
            "notes": "- Melhorias",
            "download_url": "https://example.com/app.exe",
            "filename": "Compensacoes-Setup.exe",
            "sha256": "ABC123",
            "signed": False,
        },
        can_automatically_apply_update=lambda _payload: True,
    )
    download = use_cases.build_update_offer_presentation(
        {
            "version": "1.1.0",
            "notes": "- Melhorias",
            "download_url": "https://example.com/app.exe",
        },
        can_automatically_apply_update=lambda _payload: False,
    )
    info_only = use_cases.build_update_offer_presentation(
        {"version": "1.1.0", "notes": ""},
        can_automatically_apply_update=lambda _payload: False,
    )

    assert automatic.action_kind == "automatic_update"
    assert "Arquivo: Compensacoes-Setup.exe" in automatic.message
    assert "SHA-256: abc123" in automatic.message
    assert "Assinatura digital: ausente nesta release." in automatic.message
    assert "Deseja baixar e instalar a atualizacao agora?" in automatic.message

    assert download.action_kind == "open_download"
    assert download.download_url == "https://example.com/app.exe"
    assert "Deseja abrir o link da atualizacao agora?" in download.message

    assert info_only.action_kind == "informational"
    assert "Sem notas de versao." in info_only.message


def test_support_operations_builds_runtime_outcomes_for_updates():
    use_cases = build_use_cases()

    runtime_message = use_cases.build_update_offer_runtime_message(
        use_cases.build_update_offer_presentation(
            {"version": "1.1.0", "download_url": "https://example.com/app.exe"},
            can_automatically_apply_update=lambda _payload: False,
        )
    )
    progress = use_cases.normalize_update_progress(145, "")
    manual_cancel = use_cases.build_manual_update_cancel_outcome()
    auto_failed = use_cases.build_auto_update_failed_outcome("manifest invalido")
    no_update = use_cases.build_no_update_outcome("1.2.3")

    assert runtime_message == "Atualizacao disponivel com link de download."
    assert progress.percent == 100
    assert progress.message == "Baixando atualizacao... 100%"
    assert use_cases.build_manual_update_completion_message(cancel_requested=True) == (
        "Verificacao de atualizacoes interrompida."
    )
    assert manual_cancel.runtime_status == "cancelled"
    assert manual_cancel.busy_message == "Verificacao de atualizacoes interrompida."
    assert auto_failed.runtime_status == "failed"
    assert auto_failed.status_bar_message == "Falha ao baixar/preparar a atualizacao."
    assert auto_failed.dialog_message == "manifest invalido"
    assert no_update.runtime_status == "completed"
    assert "1.2.3" in no_update.dialog_message
