from typing import Tuple

import requests

from app.services.access_service import AccessAuthError
from app.services.excel_service import WorkbookModifiedExternallyError
from app.services.supabase_compensacoes_rpc_service import SupabaseCompensacoesRpcError


def friendly_error_message(exc: Exception, action: str = "processar") -> Tuple[str, str]:
    if isinstance(exc, PermissionError):
        return (
            "Erro de Permissao",
            f"Nao foi possivel {action}. Verifique se o arquivo esta aberto em outro programa.",
        )

    if isinstance(exc, FileNotFoundError):
        return (
            "Arquivo Nao Encontrado",
            "O arquivo selecionado nao foi encontrado. Confira o caminho e tente novamente.",
        )

    if isinstance(exc, WorkbookModifiedExternallyError):
        return (
            "Planilha Desatualizada",
            "A planilha foi alterada fora do aplicativo. Recarregue antes de continuar.",
        )

    if isinstance(exc, AccessAuthError):
        return (
            "Sessão de Produção",
            "Não foi possível concluir a operação porque a sessão autenticada do Supabase não está válida. Entre novamente em Produção e tente de novo.",
        )

    if isinstance(exc, SupabaseCompensacoesRpcError):
        return (
            "Falha na Base Oficial",
            f"Nao foi possivel {action} na base oficial do Supabase. {exc}",
        )

    if isinstance(exc, requests.exceptions.Timeout):
        return (
            "Tempo Esgotado",
            f"Não foi possível {action} porque a operação demorou demais. Tente novamente.",
        )

    if isinstance(exc, requests.exceptions.ConnectionError):
        return (
            "Sem Conexao",
            f"Nao foi possivel {action} por falha de conexao. Verifique a internet e tente novamente.",
        )

    text = str(exc).lower()
    if "being used by another process" in text or "esta aberto" in text:
        return (
            "Arquivo em Uso",
            f"Nao foi possivel {action}. Feche o arquivo em outro programa e tente novamente.",
        )

    return ("Erro", f"Nao foi possivel {action}: {exc}")
