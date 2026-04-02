from typing import Tuple

import requests

from app.services.excel_service import WorkbookModifiedExternallyError


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

    if isinstance(exc, requests.exceptions.Timeout):
        return (
            "Tempo Esgotado",
            f"Nao foi possivel {action} porque a operacao demorou demais. Tente novamente.",
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
