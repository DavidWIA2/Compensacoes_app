from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.services.access_service import AccessAuthError, AppAccessSession, SupabaseAccessService
from app.services.app_settings import AppSettings


class AccessDialog(QDialog):
    def __init__(
        self,
        *,
        settings: AppSettings,
        access_service: SupabaseAccessService,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.settings = settings
        self.access_service = access_service
        self.access_session: AppAccessSession | None = None

        self.setWindowTitle("Acesso ao sistema")
        self.setModal(True)
        self.setMinimumWidth(520)

        self._build_ui()
        self._apply_defaults()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        title = QLabel("Escolha como deseja abrir o aplicativo")
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        subtitle = QLabel(
            "Producao usa acesso autenticado ao ambiente oficial. Demonstracao abre uma base ficticia isolada para testes."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color: #9aa3b2;")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        production_group = QGroupBox("Producao")
        production_layout = QVBoxLayout(production_group)
        production_layout.setSpacing(10)

        production_hint = QLabel("Acesso restrito para usuarios autorizados.")
        production_hint.setWordWrap(True)
        production_layout.addWidget(production_hint)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText("email@dominio.gov.br")
        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Senha")
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.returnPressed.connect(self._handle_production_login)

        form.addRow("Email:", self.email_input)
        form.addRow("Senha:", self.password_input)
        production_layout.addLayout(form)

        self.production_status = QLabel("")
        self.production_status.setWordWrap(True)
        production_layout.addWidget(self.production_status)

        self.production_button = QPushButton("Entrar em Producao")
        self.production_button.clicked.connect(self._handle_production_login)
        production_layout.addWidget(self.production_button)
        layout.addWidget(production_group)

        demo_group = QGroupBox("Demonstracao")
        demo_layout = QVBoxLayout(demo_group)
        demo_layout.setSpacing(10)

        self.demo_hint = QLabel("")
        self.demo_hint.setWordWrap(True)
        demo_layout.addWidget(self.demo_hint)

        self.demo_button = QPushButton("Entrar em Demonstracao")
        self.demo_button.clicked.connect(self._handle_demo_entry)
        demo_layout.addWidget(self.demo_button)
        layout.addWidget(demo_group)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color: #9aa3b2;")
        layout.addWidget(self.status_label)

        footer = QHBoxLayout()
        footer.addStretch(1)
        self.cancel_button = QPushButton("Cancelar")
        self.cancel_button.clicked.connect(self.reject)
        footer.addWidget(self.cancel_button)
        layout.addLayout(footer)

    def _apply_defaults(self) -> None:
        self.email_input.setText(self.settings.last_access_email())
        last_environment = self.settings.last_access_environment()

        if not self.access_service.can_sign_in_production():
            self.production_status.setText("A configuracao de producao ainda nao esta pronta neste app.")
            self.email_input.setEnabled(False)
            self.password_input.setEnabled(False)
            self.production_button.setEnabled(False)
        else:
            self.production_status.setText(
                "Use suas credenciais autorizadas para autenticar e sincronizar um snapshot da base oficial."
            )

        demo_label = self.access_service.demo_entry_label()
        if demo_label == "Demonstracao online":
            self.demo_hint.setText(
                "Entrando no modo demonstracao autenticado e carregando uma base ficticia isolada."
            )
        else:
            self.demo_hint.setText(
                "Abre uma base local ficticia, reiniciada a cada abertura, sem risco para a base oficial."
            )

        if last_environment == "demo":
            self.demo_button.setDefault(True)
            self.demo_button.setFocus()
        elif self.production_button.isEnabled():
            self.production_button.setDefault(True)
            self.email_input.setFocus()
        else:
            self.demo_button.setDefault(True)
            self.demo_button.setFocus()

    def _set_busy(self, busy: bool, message: str = "") -> None:
        widgets = (
            self.email_input,
            self.password_input,
            self.production_button,
            self.demo_button,
            self.cancel_button,
        )
        for widget in widgets:
            widget.setEnabled(not busy if widget is not self.cancel_button else True)
        if busy:
            QApplication.setOverrideCursor(Qt.WaitCursor)
        else:
            QApplication.restoreOverrideCursor()
        self.status_label.setText(message)
        QApplication.processEvents()

    def _handle_production_login(self) -> None:
        self._set_busy(True, "Autenticando e sincronizando a base oficial...")
        try:
            session = self.access_service.sign_in_production(
                email=self.email_input.text(),
                password=self.password_input.text(),
            )
        except AccessAuthError as exc:
            QMessageBox.warning(self, "Acesso negado", str(exc))
            self._set_busy(False, "")
            return
        except Exception as exc:
            QMessageBox.critical(self, "Erro", f"Falha inesperada ao autenticar: {exc}")
            self._set_busy(False, "")
            return

        self.settings.set_last_access_environment(session.environment.value)
        self.settings.set_last_access_email(self.email_input.text())
        self.access_session = session
        self._set_busy(False, "Acesso autorizado.")
        self.accept()

    def _handle_demo_entry(self) -> None:
        self._set_busy(True, "Preparando a base ficticia de demonstracao...")
        try:
            session = self.access_service.enter_demo()
        except AccessAuthError as exc:
            QMessageBox.warning(self, "Demonstracao indisponivel", str(exc))
            self._set_busy(False, "")
            return
        except Exception as exc:
            QMessageBox.critical(self, "Erro", f"Falha ao abrir a demonstracao: {exc}")
            self._set_busy(False, "")
            return

        self.settings.set_last_access_environment(session.environment.value)
        self.access_session = session
        self._set_busy(False, "Demonstracao pronta.")
        self.accept()
