from typing import Tuple

import requests

from app.services.access_service import AccessAuthError
from app.services.excel_service import WorkbookModifiedExternallyError
from app.services.supabase_compensacoes_rpc_service import (
    SupabaseCompensacoesConflictError,
    SupabaseCompensacoesRpcError,
)


def friendly_error_message(exc: Exception, action: str = "processar") -> Tuple[str, str]:
    if isinstance(exc, PermissionError):
        return (
            "Erro de Permissão",
            f"Não foi possível {action}. Verifique se o arquivo está aberto em outro programa e tente novamente.",
        )

    if isinstance(exc, FileNotFoundError):
        return (
            "Arquivo Não Encontrado",
            "O arquivo selecionado não foi encontrado. Confira o caminho informado e tente novamente.",
        )

    if isinstance(exc, WorkbookModifiedExternallyError):
        return (
            "Base Desatualizada",
            "A base foi alterada fora do aplicativo. Recarregue os dados antes de continuar para evitar conflito.",
        )

    if isinstance(exc, AccessAuthError):
        return (
            "Sessão de Produção",
            (
                "Não foi possível concluir a operação porque a sessão autenticada do Supabase não está válida. "
                "Entre novamente em Produção e tente de novo."
            ),
        )

    if isinstance(exc, SupabaseCompensacoesConflictError):
        return (
            "Conflito de Edição",
            (
                "Este registro foi alterado na base oficial por outra sessão. "
                "Atualize a base sincronizada, revise os dados mais recentes e tente novamente."
            ),
        )

    if isinstance(exc, SupabaseCompensacoesRpcError):
        return (
            "Falha na Base Oficial",
            (
                f"Não foi possível {action} na base oficial do Supabase. "
                f"{exc} Verifique a conexão ou tente novamente em instantes."
            ),
        )

    if isinstance(exc, requests.exceptions.Timeout):
        return (
            "Tempo Esgotado",
            f"Não foi possível {action} porque a operação demorou demais. Tente novamente.",
        )

    if isinstance(exc, requests.exceptions.ConnectionError):
        return (
            "Sem Conexão",
            (
                f"Não foi possível {action} por falha de conexão. "
                "Verifique a internet ou a rede da Prefeitura e tente novamente."
            ),
        )

    text = str(exc).lower()
    if "being used by another process" in text or "esta aberto" in text:
        return (
            "Arquivo em Uso",
            f"Não foi possível {action}. Feche o arquivo em outro programa e tente novamente.",
        )

    return ("Erro", f"Não foi possível {action}: {exc}")
