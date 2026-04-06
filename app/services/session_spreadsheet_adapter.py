from __future__ import annotations

from app.services.excel_service import ExcelService


class SessionSpreadsheetAdapter(ExcelService):
    """Adaptador de borda para carregar ou exportar dados externos em XLSX."""


ExternalSpreadsheetAdapter = SessionSpreadsheetAdapter
