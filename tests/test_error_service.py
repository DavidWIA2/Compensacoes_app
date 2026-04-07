from app.services.access_service import AccessAuthError
from app.services.error_service import friendly_error_message
from app.services.excel_service import WorkbookModifiedExternallyError
from app.services.supabase_compensacoes_rpc_service import SupabaseCompensacoesRpcError


class FakeConnectionError(Exception):
    pass


def test_friendly_error_message_handles_permission_error():
    title, msg = friendly_error_message(PermissionError("denied"), "salvar")

    assert title == "Erro de Permissao"
    assert "arquivo" in msg.lower()


def test_friendly_error_message_handles_file_not_found():
    title, msg = friendly_error_message(FileNotFoundError("missing"), "abrir")

    assert title == "Arquivo Nao Encontrado"
    assert "nao foi encontrado" in msg.lower()


def test_friendly_error_message_handles_external_workbook_change():
    title, msg = friendly_error_message(WorkbookModifiedExternallyError("stale"), "salvar")

    assert title == "Planilha Desatualizada"
    assert "recarregue" in msg.lower()


def test_friendly_error_message_handles_file_in_use_text():
    title, msg = friendly_error_message(Exception("File is being used by another process"), "salvar")

    assert title == "Arquivo em Uso"
    assert "feche o arquivo" in msg.lower()


def test_friendly_error_message_fallback():
    title, msg = friendly_error_message(RuntimeError("falha x"), "processar")

    assert title == "Erro"
    assert "falha x" in msg


def test_friendly_error_message_handles_access_auth_error():
    title, msg = friendly_error_message(AccessAuthError("tokens invalidos"), "salvar")

    assert title == "Sessão de Produção"
    assert "supabase" in msg.lower()


def test_friendly_error_message_handles_supabase_rpc_error():
    title, msg = friendly_error_message(SupabaseCompensacoesRpcError("rpc offline"), "salvar")

    assert title == "Falha na Base Oficial"
    assert "rpc offline" in msg.lower()
