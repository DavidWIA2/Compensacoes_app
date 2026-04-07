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

from app.config import (
    DEFAULT_CORPORATE_EMAIL_SUFFIX,
    display_corporate_email_local_part,
    normalize_corporate_email,
)
from app.services.access_service import AccessAuthError, AppAccessSession, SupabaseAccessService
from app.services.app_settings import AppSettings
from app.services.supabase_admin_users_service import AdminUsersError, SupabaseAdminUsersService


def _build_corporate_email_row(input_field: QLineEdit, parent: QWidget | None = None) -> QWidget:
    input_field.setPlaceholderText("nome.sobrenome")
    row = QWidget(parent)
    row_layout = QHBoxLayout(row)
    row_layout.setContentsMargins(0, 0, 0, 0)
    row_layout.setSpacing(8)
    suffix_label = QLabel(DEFAULT_CORPORATE_EMAIL_SUFFIX, row)
    suffix_label.setObjectName("FormStateLabel")
    row_layout.addWidget(input_field, 1)
    row_layout.addWidget(suffix_label, 0, Qt.AlignVCenter)
    return row


def _normalize_corporate_email_field(input_field: QLineEdit) -> None:
    local_part = display_corporate_email_local_part(input_field.text())
    if local_part != input_field.text():
        input_field.setText(local_part)


class BootstrapFirstAdminDialog(QDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Criar primeiro administrador")
        self.setModal(True)
        self.setMinimumWidth(460)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        hint = QLabel(
            "Este cadastro só fica disponível enquanto não existir nenhum usuário configurado em Produção."
        )
        hint.setWordWrap(True)
        hint.setObjectName("FormStateLabel")
        layout.addWidget(hint)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

        self.display_name_input = QLineEdit(self)
        self.display_name_input.setPlaceholderText("Nome exibido no app")
        self.email_input = QLineEdit(self)
        self.email_input.editingFinished.connect(lambda: _normalize_corporate_email_field(self.email_input))
        self.password_input = QLineEdit(self)
        self.password_input.setPlaceholderText("Senha com 8+ caracteres")
        self.password_input.setEchoMode(QLineEdit.Password)
        self.confirm_password_input = QLineEdit(self)
        self.confirm_password_input.setPlaceholderText("Repita a senha")
        self.confirm_password_input.setEchoMode(QLineEdit.Password)
        self.confirm_password_input.returnPressed.connect(self._submit)

        form.addRow("Nome:", self.display_name_input)
        form.addRow("Email:", _build_corporate_email_row(self.email_input, self))
        form.addRow("Senha:", self.password_input)
        form.addRow("Confirmar senha:", self.confirm_password_input)
        layout.addLayout(form)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setObjectName("FormStateLabel")
        layout.addWidget(self.status_label)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.cancel_button = QPushButton("Cancelar")
        self.cancel_button.clicked.connect(self.reject)
        self.submit_button = QPushButton("Criar administrador")
        self.submit_button.clicked.connect(self._submit)
        actions.addWidget(self.cancel_button)
        actions.addWidget(self.submit_button)
        layout.addLayout(actions)

    def payload(self) -> dict[str, str]:
        return {
            "display_name": self.display_name_input.text().strip(),
            "email": normalize_corporate_email(self.email_input.text()),
            "password": self.password_input.text(),
        }

    def _submit(self) -> None:
        raw_email = self.email_input.text().strip()
        email = normalize_corporate_email(raw_email)
        password = self.password_input.text()
        confirm_password = self.confirm_password_input.text()
        if not raw_email or "@" not in email or email.startswith("@") or email.endswith("@"):
            self.status_label.setText(
                "Informe o email corporativo do administrador. O domínio padrão será "
                f"{DEFAULT_CORPORATE_EMAIL_SUFFIX}."
            )
            self.email_input.setFocus()
            return
        if len(password) < 8:
            self.status_label.setText("A senha precisa ter pelo menos 8 caracteres.")
            self.password_input.setFocus()
            return
        if password != confirm_password:
            self.status_label.setText("A confirmação da senha não confere.")
            self.confirm_password_input.setFocus()
            return
        self.accept()


class RequestPasswordResetDialog(QDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Recuperar senha")
        self.setModal(True)
        self.setMinimumWidth(430)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        hint = QLabel(
            "Informe seu email corporativo. Se a recuperação por email estiver habilitada, "
            "o sistema enviará as instruções para redefinir sua senha."
        )
        hint.setWordWrap(True)
        hint.setObjectName("FormStateLabel")
        layout.addWidget(hint)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

        self.email_input = QLineEdit(self)
        self.email_input.editingFinished.connect(lambda: _normalize_corporate_email_field(self.email_input))
        self.email_input.returnPressed.connect(self._submit)
        form.addRow("Email:", _build_corporate_email_row(self.email_input, self))
        layout.addLayout(form)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setObjectName("FormStateLabel")
        layout.addWidget(self.status_label)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.cancel_button = QPushButton("Cancelar")
        self.cancel_button.clicked.connect(self.reject)
        self.submit_button = QPushButton("Enviar instruções")
        self.submit_button.clicked.connect(self._submit)
        actions.addWidget(self.cancel_button)
        actions.addWidget(self.submit_button)
        layout.addLayout(actions)

    def payload(self) -> dict[str, str]:
        return {
            "email": normalize_corporate_email(self.email_input.text()),
        }

    def _submit(self) -> None:
        raw_email = self.email_input.text().strip()
        email = normalize_corporate_email(raw_email)
        if not raw_email or "@" not in email or email.startswith("@") or email.endswith("@"):
            self.status_label.setText(
                "Informe seu email corporativo. O domínio padrão será "
                f"{DEFAULT_CORPORATE_EMAIL_SUFFIX}."
            )
            self.email_input.setFocus()
            return
        self.accept()


class CompletePasswordResetDialog(QDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Concluir recuperação de senha")
        self.setModal(True)
        self.setMinimumWidth(470)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        hint = QLabel(
            "Abra o email corporativo, copie o link completo de acesso ou o código recebido e cole abaixo. "
            "Depois, defina a nova senha."
        )
        hint.setWordWrap(True)
        hint.setObjectName("FormStateLabel")
        layout.addWidget(hint)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

        self.email_input = QLineEdit(self)
        self.email_input.editingFinished.connect(lambda: _normalize_corporate_email_field(self.email_input))
        self.recovery_input = QLineEdit(self)
        self.recovery_input.setPlaceholderText("Cole aqui o link completo ou o código recebido")
        self.password_input = QLineEdit(self)
        self.password_input.setPlaceholderText("Nova senha com 8+ caracteres")
        self.password_input.setEchoMode(QLineEdit.Password)
        self.confirm_password_input = QLineEdit(self)
        self.confirm_password_input.setPlaceholderText("Repita a nova senha")
        self.confirm_password_input.setEchoMode(QLineEdit.Password)
        self.confirm_password_input.returnPressed.connect(self._submit)

        form.addRow("Email:", _build_corporate_email_row(self.email_input, self))
        form.addRow("Link ou código:", self.recovery_input)
        form.addRow("Nova senha:", self.password_input)
        form.addRow("Confirmar:", self.confirm_password_input)
        layout.addLayout(form)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setObjectName("FormStateLabel")
        layout.addWidget(self.status_label)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.cancel_button = QPushButton("Cancelar")
        self.cancel_button.clicked.connect(self.reject)
        self.submit_button = QPushButton("Atualizar senha")
        self.submit_button.clicked.connect(self._submit)
        actions.addWidget(self.cancel_button)
        actions.addWidget(self.submit_button)
        layout.addLayout(actions)

    def payload(self) -> dict[str, str]:
        return {
            "email": normalize_corporate_email(self.email_input.text()),
            "recovery_value": self.recovery_input.text().strip(),
            "new_password": self.password_input.text(),
        }

    def _submit(self) -> None:
        payload = self.payload()
        confirm_password = self.confirm_password_input.text()
        if not payload["email"] or "@" not in payload["email"]:
            self.status_label.setText(
                "Informe seu email corporativo. O domínio padrão será "
                f"{DEFAULT_CORPORATE_EMAIL_SUFFIX}."
            )
            self.email_input.setFocus()
            return
        if not payload["recovery_value"]:
            self.status_label.setText("Cole o link completo ou o código recebido no email.")
            self.recovery_input.setFocus()
            return
        if len(payload["new_password"]) < 8:
            self.status_label.setText("A nova senha precisa ter pelo menos 8 caracteres.")
            self.password_input.setFocus()
            return
        if payload["new_password"] != confirm_password:
            self.status_label.setText("A confirmação da senha não confere.")
            self.confirm_password_input.setFocus()
            return
        self.accept()


class AccessDialog(QDialog):
    def __init__(
        self,
        *,
        settings: AppSettings,
        access_service: SupabaseAccessService,
        admin_users_service: SupabaseAdminUsersService | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.settings = settings
        self.access_service = access_service
        self.admin_users_service = admin_users_service or SupabaseAdminUsersService(
            production_profile=access_service.production_profile,
        )
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
            "Produção usa acesso autenticado ao ambiente oficial. Demonstração abre uma base fictícia isolada para testes."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color: #9aa3b2;")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        production_group = QGroupBox("Produção")
        production_layout = QVBoxLayout(production_group)
        production_layout.setSpacing(10)

        production_hint = QLabel("Acesso restrito para usuários autorizados.")
        production_hint.setWordWrap(True)
        production_layout.addWidget(production_hint)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

        self.email_input = QLineEdit()
        self.email_input.editingFinished.connect(lambda: _normalize_corporate_email_field(self.email_input))
        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Senha")
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.returnPressed.connect(self._handle_production_login)

        form.addRow("Email:", _build_corporate_email_row(self.email_input, self))
        form.addRow("Senha:", self.password_input)
        production_layout.addLayout(form)

        self.production_status = QLabel("")
        self.production_status.setWordWrap(True)
        production_layout.addWidget(self.production_status)

        self.production_button = QPushButton("Entrar em Produção")
        self.production_button.clicked.connect(self._handle_production_login)
        production_layout.addWidget(self.production_button)

        self.forgot_password_button = QPushButton("Esqueci minha senha")
        self.forgot_password_button.setProperty("kind", "secondary")
        self.forgot_password_button.clicked.connect(self._handle_password_reset_request)
        production_layout.addWidget(self.forgot_password_button)

        self.bootstrap_button = QPushButton("Criar primeiro administrador")
        self.bootstrap_button.setProperty("kind", "secondary")
        self.bootstrap_button.clicked.connect(self._handle_bootstrap_admin)
        self.bootstrap_button.setVisible(False)
        production_layout.addWidget(self.bootstrap_button)
        layout.addWidget(production_group)

        demo_group = QGroupBox("Demonstração")
        demo_layout = QVBoxLayout(demo_group)
        demo_layout.setSpacing(10)

        self.demo_hint = QLabel("")
        self.demo_hint.setWordWrap(True)
        demo_layout.addWidget(self.demo_hint)

        self.demo_button = QPushButton("Entrar em Demonstração")
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
        self.email_input.setText(display_corporate_email_local_part(self.settings.last_access_email()))
        last_environment = self.settings.last_access_environment()

        if not self.access_service.can_sign_in_production():
            self.production_status.setText("A configuração de produção ainda não está pronta neste app.")
            self.email_input.setEnabled(False)
            self.password_input.setEnabled(False)
            self.production_button.setEnabled(False)
            self.forgot_password_button.setEnabled(False)
            self.bootstrap_button.setVisible(False)
        else:
            self.production_status.setText(
                "Use seu email corporativo e sua senha para autenticar e sincronizar um snapshot da base oficial."
            )
            self._apply_bootstrap_availability()

        demo_label = self.access_service.demo_entry_label()
        if demo_label == "Demonstração online":
            self.demo_hint.setText(
                "Entrando no modo demonstração autenticado e carregando uma base fictícia isolada."
            )
        else:
            self.demo_hint.setText(
                "Abre uma base local fictícia, reiniciada a cada abertura, sem risco para a base oficial."
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
            self.forgot_password_button,
            self.bootstrap_button,
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

    def _apply_bootstrap_availability(self) -> None:
        self.bootstrap_button.setVisible(False)
        try:
            bootstrap_status = self.admin_users_service.bootstrap_status()
        except AdminUsersError:
            return
        except Exception:
            return

        if bootstrap_status.allowed:
            self.bootstrap_button.setVisible(True)
            self.production_status.setText(
                "Nenhum usuário foi configurado ainda em Produção. Crie o primeiro administrador para liberar o login."
            )

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
        self.settings.set_last_access_email(session.user_email or normalize_corporate_email(self.email_input.text()))
        self.access_session = session
        self._set_busy(False, "Acesso autorizado.")
        self.accept()

    def _handle_password_reset_request(self) -> None:
        request_dialog = RequestPasswordResetDialog(self)
        request_dialog.email_input.setText(display_corporate_email_local_part(self.email_input.text()))
        if not request_dialog.exec():
            return

        payload = request_dialog.payload()
        self._set_busy(True, "Solicitando a recuperação de senha...")
        try:
            message = self.access_service.request_password_reset(email=payload["email"])
        except AccessAuthError as exc:
            QMessageBox.information(self, "Recuperar senha", str(exc))
            self._set_busy(False, "")
            return
        except Exception as exc:
            QMessageBox.critical(self, "Erro", f"Falha inesperada ao solicitar a recuperação: {exc}")
            self._set_busy(False, "")
            return

        self.email_input.setText(display_corporate_email_local_part(payload["email"]))
        self.settings.set_last_access_email(payload["email"])
        QMessageBox.information(self, "Recuperar senha", message)
        self._set_busy(False, "")

        complete_dialog = CompletePasswordResetDialog(self)
        complete_dialog.email_input.setText(display_corporate_email_local_part(payload["email"]))
        if not complete_dialog.exec():
            return

        completion_payload = complete_dialog.payload()
        self._set_busy(True, "Atualizando a senha...")
        try:
            completion_message = self.access_service.complete_password_reset(
                email=completion_payload["email"],
                recovery_value=completion_payload["recovery_value"],
                new_password=completion_payload["new_password"],
            )
        except AccessAuthError as exc:
            QMessageBox.warning(self, "Recuperar senha", str(exc))
            self._set_busy(False, "")
            return
        except Exception as exc:
            QMessageBox.critical(self, "Erro", f"Falha inesperada ao concluir a recuperação: {exc}")
            self._set_busy(False, "")
            return

        QMessageBox.information(self, "Recuperar senha", completion_message)
        self._set_busy(False, "")

    def _handle_bootstrap_admin(self) -> None:
        dialog = BootstrapFirstAdminDialog(self)
        dialog.email_input.setText(display_corporate_email_local_part(self.email_input.text()))
        if not dialog.exec():
            return

        payload = dialog.payload()
        self._set_busy(True, "Criando o primeiro administrador e preparando o acesso...")
        try:
            self.admin_users_service.bootstrap_first_admin(
                email=payload["email"],
                password=payload["password"],
                display_name=payload["display_name"],
            )
            session = self.access_service.sign_in_production(
                email=payload["email"],
                password=payload["password"],
            )
        except (AdminUsersError, AccessAuthError) as exc:
            QMessageBox.warning(self, "Bootstrap administrativo", str(exc))
            self._set_busy(False, "")
            self._apply_bootstrap_availability()
            return
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Erro",
                f"Falha inesperada ao criar o primeiro administrador: {exc}",
            )
            self._set_busy(False, "")
            self._apply_bootstrap_availability()
            return

        self.email_input.setText(display_corporate_email_local_part(payload["email"]))
        self.settings.set_last_access_environment(session.environment.value)
        self.settings.set_last_access_email(session.user_email or payload["email"])
        self.access_session = session
        self._set_busy(False, "Primeiro administrador criado e autenticado.")
        self.accept()

    def _handle_demo_entry(self) -> None:
        self._set_busy(True, "Preparando a base fictícia de demonstração...")
        try:
            session = self.access_service.enter_demo()
        except AccessAuthError as exc:
            QMessageBox.warning(self, "Demonstração indisponível", str(exc))
            self._set_busy(False, "")
            return
        except Exception as exc:
            QMessageBox.critical(self, "Erro", f"Falha ao abrir a demonstração: {exc}")
            self._set_busy(False, "")
            return

        self.settings.set_last_access_environment(session.environment.value)
        self.access_session = session
        self._set_busy(False, "Demonstração pronta.")
        self.accept()
