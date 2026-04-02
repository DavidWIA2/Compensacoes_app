from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class AboutDialogData:
    title: str
    message: str


@dataclass(frozen=True)
class DiagnosticsExportResult:
    path: str
    snapshot: dict[str, Any]


@dataclass(frozen=True)
class UpdateOfferPresentation:
    title: str
    message: str
    action_kind: str
    payload: dict[str, Any]
    download_url: str = ""


@dataclass(frozen=True)
class UpdateProgressState:
    percent: int
    message: str


@dataclass(frozen=True)
class UpdateJobOutcome:
    runtime_status: str
    runtime_message: str
    status_bar_message: str
    busy_message: str = ""
    dialog_title: str = ""
    dialog_message: str = ""


class SupportOperationsUseCases:
    def __init__(
        self,
        *,
        app_name: str,
        app_version: str,
        log_dir: str,
        update_url_env_var: str,
        manifest_url_resolver: Callable[[], str],
        default_diagnostics_filename_builder: Callable[[], str],
        diagnostics_snapshot_builder: Callable[[Any], dict[str, Any]],
        diagnostics_report_writer: Callable[[str, dict[str, Any]], None],
        python_version_resolver: Callable[[], str],
    ):
        self.app_name = app_name
        self.app_version = app_version
        self.log_dir = log_dir
        self.update_url_env_var = update_url_env_var
        self.manifest_url_resolver = manifest_url_resolver
        self.default_diagnostics_filename_builder = default_diagnostics_filename_builder
        self.diagnostics_snapshot_builder = diagnostics_snapshot_builder
        self.diagnostics_report_writer = diagnostics_report_writer
        self.python_version_resolver = python_version_resolver

    def build_about_dialog_data(self) -> AboutDialogData:
        update_source = self.manifest_url_resolver()
        lines = [
            f"{self.app_name} {self.app_version}",
            "",
            "Gestao de compensacoes ambientais com cadastro, filtros, mapa e exportacoes.",
            f"Python {self.python_version_resolver()}",
            f"Logs: {self.log_dir}",
            f"Manifest de atualizacao: {update_source}",
            f"Variavel de override: {self.update_url_env_var}",
        ]
        return AboutDialogData(
            title=f"Sobre o {self.app_name}",
            message="\n".join(lines),
        )

    def build_diagnostics_default_path(self, initial_dir: str) -> str:
        return os.path.join(initial_dir, self.default_diagnostics_filename_builder())

    def export_diagnostics_snapshot(self, context: Any, path: str) -> DiagnosticsExportResult:
        snapshot = self.diagnostics_snapshot_builder(context)
        self.diagnostics_report_writer(path, snapshot)
        return DiagnosticsExportResult(path=path, snapshot=snapshot)

    def build_update_offer_presentation(
        self,
        details: dict[str, Any] | None,
        *,
        can_automatically_apply_update: Callable[[dict[str, Any]], bool],
    ) -> UpdateOfferPresentation:
        payload = dict(details or {})
        version = str(payload.get("version") or "").strip()
        notes = str(payload.get("notes") or "Sem notas de versao.").strip() or "Sem notas de versao."
        download_url = str(payload.get("download_url") or payload.get("homepage_url") or "").strip()
        published_at = str(payload.get("published_at") or "").strip()
        filename = str(payload.get("filename") or "").strip()
        sha256 = str(payload.get("sha256") or "").strip().lower()
        signed = payload.get("signed")
        signature_mode = str(payload.get("signature_mode") or "").strip()
        automatic = can_automatically_apply_update(payload)

        lines = [f"Uma nova versao ({version}) esta disponivel."]
        if published_at:
            lines.append(f"Publicado em: {published_at}")
        if filename:
            lines.append(f"Arquivo: {filename}")
        if sha256:
            lines.append(f"SHA-256: {sha256}")
        if signed is True:
            mode_text = f" ({signature_mode})" if signature_mode else ""
            lines.append(f"Assinatura digital: presente{mode_text}.")
        elif signed is False:
            lines.append("Assinatura digital: ausente nesta release.")
        lines.extend(["", "Novidades:", notes])

        if automatic:
            lines.extend(["", "Deseja baixar e instalar a atualizacao agora?"])
            action_kind = "automatic_update"
        elif download_url:
            lines.extend(["", "Deseja abrir o link da atualizacao agora?"])
            action_kind = "open_download"
        else:
            action_kind = "informational"

        return UpdateOfferPresentation(
            title="Atualizacao Disponivel",
            message="\n".join(lines),
            action_kind=action_kind,
            payload=payload,
            download_url=download_url,
        )

    @staticmethod
    def build_update_offer_runtime_message(presentation: UpdateOfferPresentation) -> str:
        if presentation.action_kind == "automatic_update":
            return "Atualizacao disponivel encontrada."
        if presentation.action_kind == "open_download":
            return "Atualizacao disponivel com link de download."
        return "Atualizacao encontrada sem link de download."

    @staticmethod
    def normalize_update_progress(percent: int, message: str) -> UpdateProgressState:
        resolved_percent = max(0, min(int(percent), 100))
        resolved_message = str(message or "").strip() or f"Baixando atualizacao... {resolved_percent}%"
        return UpdateProgressState(percent=resolved_percent, message=resolved_message)

    @staticmethod
    def build_manual_update_completion_message(cancel_requested: bool) -> str:
        if cancel_requested:
            return "Verificacao de atualizacoes interrompida."
        return "Verificacao de atualizacoes concluida."

    @staticmethod
    def build_manual_update_cancel_outcome() -> UpdateJobOutcome:
        message = "Verificacao de atualizacoes interrompida."
        return UpdateJobOutcome(
            runtime_status="cancelled",
            runtime_message=message,
            status_bar_message=message,
            busy_message=message,
        )

    @staticmethod
    def build_auto_update_ready_outcome() -> UpdateJobOutcome:
        message = "Atualizacao pronta para instalar."
        return UpdateJobOutcome(
            runtime_status="completed",
            runtime_message=message,
            status_bar_message=message,
            busy_message=message,
        )

    @staticmethod
    def build_auto_update_failed_outcome(message: str) -> UpdateJobOutcome:
        return UpdateJobOutcome(
            runtime_status="failed",
            runtime_message=message,
            status_bar_message="Falha ao baixar/preparar a atualizacao.",
            busy_message="Falha ao baixar/preparar a atualizacao.",
            dialog_title="Atualizacao Automatica",
            dialog_message=message,
        )

    @staticmethod
    def build_auto_update_cancelled_outcome(message: str) -> UpdateJobOutcome:
        resolved_message = str(message or "").strip() or "Atualizacao automatica cancelada."
        return UpdateJobOutcome(
            runtime_status="cancelled",
            runtime_message=resolved_message,
            status_bar_message="Atualizacao automatica cancelada.",
            busy_message="Atualizacao automatica cancelada.",
            dialog_title="Atualizacao Automatica",
            dialog_message=resolved_message,
        )

    @staticmethod
    def build_no_update_outcome(current_version: str) -> UpdateJobOutcome:
        return UpdateJobOutcome(
            runtime_status="completed",
            runtime_message="Nenhuma atualizacao encontrada.",
            status_bar_message="Nenhuma atualizacao encontrada.",
            dialog_title="Atualizacoes",
            dialog_message=f"Voce ja esta na versao mais recente disponivel ({current_version}).",
        )

    @staticmethod
    def build_update_check_failure_outcome(message: str) -> UpdateJobOutcome:
        return UpdateJobOutcome(
            runtime_status="failed",
            runtime_message=message,
            status_bar_message="Falha ao verificar atualizacoes.",
            dialog_title="Atualizacoes",
            dialog_message=message,
        )
