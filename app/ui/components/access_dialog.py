from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFormLayout,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.config import (
    APP_BRAND_TAGLINE,
    APP_NAME,
    DEFAULT_CORPORATE_EMAIL_SUFFIX,
    display_corporate_email_local_part,
    normalize_corporate_email,
)
from app.services.access_service import AccessAuthError, AppAccessSession, SupabaseAccessService
from app.services.app_settings import AppSettings
from app.services.supabase_admin_users_service import AdminUsersError, SupabaseAdminUsersService
from app.ui.components.ui_utils import build_app_icon, resource_path


ACCESS_DIALOG_STYLESHEET = """
QDialog#AccessDialog { background-color: #071a35; }
QFrame#accessShell { background-color: #eef5fb; border: 1px solid rgba(255,255,255,0.08); border-radius: 24px; }
QFrame#accessFormPane {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(247,251,255,0.98), stop:1 rgba(238,246,252,0.98));
    border-top-right-radius: 24px;
    border-bottom-right-radius: 24px;
}
QFrame#accessSection, QFrame#accessStatusPanel {
    background-color: rgba(255,255,255,0.88);
    border: 1px solid rgba(36,82,140,0.12);
}
QFrame#accessSection { border-radius: 18px; }
QFrame#accessStatusPanel { border-radius: 16px; }
QLabel#accessEyebrow { color: #3c6ca8; font-size: 11px; font-weight: 700; letter-spacing: 0.18em; text-transform: uppercase; }
QLabel#accessTitle { color: #0f2748; font-size: 28px; font-weight: 700; }
QLabel#accessSubtitle { color: #5d7391; font-size: 13px; }
QLabel#sectionTitle { color: #163257; font-size: 16px; font-weight: 700; }
QLabel#sectionDescription { color: #647c98; font-size: 12px; }
QLabel#fieldLabel { color: #21456f; font-size: 12px; font-weight: 600; }
QLabel#suffixLabel {
    color: #5f7898;
    background-color: rgba(38,86,150,0.08);
    border: 1px solid rgba(38,86,150,0.14);
    border-radius: 12px;
    padding: 8px 12px;
    font-size: 12px;
    font-weight: 600;
}
QLabel#accessHint { color: #57718f; font-size: 12px; }
QLabel#accessStatusText { color: #20446f; font-size: 12px; font-weight: 600; }
QLineEdit {
    min-height: 42px;
    background-color: #ffffff;
    border: 1px solid rgba(43,83,138,0.16);
    border-radius: 14px;
    color: #14304f;
    padding: 0 14px;
    selection-background-color: #3d78c9;
}
QLineEdit:focus { border: 2px solid #3d78c9; padding: 0 13px; background-color: #ffffff; }
QLineEdit:disabled { color: #8597aa; background-color: #edf2f7; }
QPushButton { min-height: 42px; border-radius: 14px; padding: 0 18px; font-weight: 700; }
QPushButton[role="primary"] { color: white; border: 0; background-color: #2d70c9; }
QPushButton[role="primary"]:hover { background-color: #2466be; }
QPushButton[role="success"] { color: white; border: 0; background-color: #208c6a; }
QPushButton[role="success"]:hover { background-color: #187658; }
QPushButton[role="secondary"] { color: #1b4b78; border: 1px solid rgba(43,83,138,0.18); background-color: rgba(255,255,255,0.85); }
QPushButton[role="secondary"]:hover { background-color: rgba(232,241,250,0.95); }
QPushButton[role="subtle"] { color: #486789; border: 1px solid rgba(43,83,138,0.12); background-color: rgba(244,248,252,0.9); }
QPushButton[role="subtle"]:hover { background-color: rgba(231,239,247,0.98); }
QPushButton:disabled { color: #9fb0c1; background-color: #e6edf5; border-color: rgba(43,83,138,0.08); }
QDialog#AccessAuxDialog { background-color: #eef5fb; }
QDialog#AccessAuxDialog QFrame#accessShell { background-color: rgba(255,255,255,0.92); border-radius: 20px; }
"""


def _dialog_icon() -> QIcon:
    icon = build_app_icon()
    return icon if not icon.isNull() else QIcon()


def _apply_shadow(widget: QWidget, *, blur_radius: float = 32.0, offset_y: float = 10.0) -> None:
    shadow = QGraphicsDropShadowEffect(widget)
    shadow.setBlurRadius(blur_radius)
    shadow.setOffset(0.0, offset_y)
    shadow.setColor(QColor(7, 26, 53, 58))
    widget.setGraphicsEffect(shadow)


def _apply_access_dialog_theme(dialog: QDialog) -> None:
    existing = dialog.styleSheet().strip()
    if ACCESS_DIALOG_STYLESHEET not in existing:
        dialog.setStyleSheet(f"{existing}\n{ACCESS_DIALOG_STYLESHEET}".strip())
    icon = _dialog_icon()
    if not icon.isNull():
        dialog.setWindowIcon(icon)


def _set_button_role(button: QPushButton, role: str) -> None:
    button.setProperty("role", role)
    button.style().unpolish(button)
    button.style().polish(button)


def _load_access_artwork() -> QPixmap:
    return QPixmap(resource_path("assets", "Splash.png"))


def _build_corporate_email_row(input_field: QLineEdit, *, parent: QWidget | None = None) -> QWidget:
    input_field.setPlaceholderText("nome.sobrenome")
    input_field.setClearButtonEnabled(True)
    container = QWidget(parent)
    container_layout = QHBoxLayout(container)
    container_layout.setContentsMargins(0, 0, 0, 0)
    container_layout.setSpacing(10)
    suffix = QLabel(DEFAULT_CORPORATE_EMAIL_SUFFIX, container)
    suffix.setObjectName("suffixLabel")
    container_layout.addWidget(input_field, stretch=1)
    container_layout.addWidget(suffix, stretch=0)
    return container


def _normalize_corporate_email_field(input_field: QLineEdit) -> str:
    return normalize_corporate_email(input_field.text())


def _configure_text_input(
    input_field: QLineEdit,
    *,
    placeholder: str = "",
    tooltip: str = "",
    password: bool = False,
) -> None:
    input_field.setPlaceholderText(placeholder)
    input_field.setToolTip(tooltip)
    input_field.setClearButtonEnabled(True)
    if password:
        input_field.setEchoMode(QLineEdit.Password)


class SplashVisualPanel(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("accessVisualPanel")
        self.setMinimumWidth(430)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._artwork = _load_access_artwork()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(34, 34, 34, 34)
        layout.setSpacing(14)

        eyebrow = QLabel("PLATAFORMA INSTITUCIONAL", self)
        eyebrow.setObjectName("accessEyebrow")
        eyebrow.setStyleSheet("color: rgba(255,255,255,0.82); font-weight: 700; letter-spacing: 0.18em;")

        title = QLabel(APP_NAME, self)
        title.setWordWrap(True)
        title.setStyleSheet("color: white; font-size: 30px; font-weight: 800;")

        subtitle = QLabel(APP_BRAND_TAGLINE, self)
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color: rgba(255,255,255,0.88); font-size: 15px;")

        accent = QFrame(self)
        accent.setFixedHeight(2)
        accent.setStyleSheet("background-color: rgba(255,255,255,0.5); border: none;")

        feature_block = QFrame(self)
        feature_block.setStyleSheet(
            "background-color: rgba(6, 24, 48, 0.24);"
            "border: 1px solid rgba(255,255,255,0.14);"
            "border-radius: 18px;"
        )
        feature_layout = QVBoxLayout(feature_block)
        feature_layout.setContentsMargins(18, 18, 18, 18)
        feature_layout.setSpacing(8)

        feature_title = QLabel("Operação integrada", feature_block)
        feature_title.setStyleSheet("color: white; font-size: 15px; font-weight: 700;")
        feature_layout.addWidget(feature_title)

        for text in (
            "Compensações, TCRAs e monitoramento ambiental em um único fluxo.",
            "Autenticação de produção, ambiente de demonstração e base sincronizada.",
            "Experiência institucional alinhada ao painel principal do sistema.",
        ):
            label = QLabel(text, feature_block)
            label.setWordWrap(True)
            label.setStyleSheet("color: rgba(255,255,255,0.86); font-size: 12px;")
            feature_layout.addWidget(label)

        footer = QLabel("Base oficial protegida • cache sincronizado • operação assistida", self)
        footer.setWordWrap(True)
        footer.setStyleSheet("color: rgba(255,255,255,0.8); font-size: 12px; font-weight: 600;")

        layout.addWidget(eyebrow, stretch=0, alignment=Qt.AlignTop)
        layout.addSpacing(6)
        layout.addWidget(title, stretch=0)
        layout.addWidget(subtitle, stretch=0)
        layout.addWidget(accent, stretch=0)
        layout.addStretch(1)
        layout.addWidget(feature_block, stretch=0)
        layout.addStretch(1)
        layout.addWidget(footer, stretch=0)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.setRenderHint(QPainter.Antialiasing, True)

        rect = self.rect()
        clip_path = QPainterPath()
        clip_path.addRoundedRect(rect.adjusted(0, 0, 1, 1), 24, 24)
        painter.setClipPath(clip_path)

        background = QLinearGradient(0, 0, 0, rect.height())
        background.setColorAt(0.0, QColor(58, 126, 226))
        background.setColorAt(0.42, QColor(28, 91, 190))
        background.setColorAt(1.0, QColor(7, 34, 83))
        painter.fillRect(rect, background)

        if not self._artwork.isNull():
            image_width = self._artwork.width()
            image_height = self._artwork.height()
            source_rect = QRect(0, 0, int(image_width * 0.44), image_height)
            scenic = self._artwork.copy(source_rect)
            target_rect = rect.adjusted(18, 22, -18, -22)
            scaled = scenic.scaled(
                target_rect.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            x = target_rect.x() + (target_rect.width() - scaled.width()) // 2
            y = target_rect.y() + (target_rect.height() - scaled.height()) // 2 + 28
            painter.drawPixmap(x, y, scaled)
        else:
            painter.fillRect(rect, QColor("#15386A"))

        overlay = QLinearGradient(0, 0, rect.width(), rect.height())
        overlay.setColorAt(0.0, QColor(7, 27, 53, 58))
        overlay.setColorAt(0.45, QColor(17, 69, 130, 94))
        overlay.setColorAt(1.0, QColor(7, 27, 53, 154))
        painter.fillRect(rect, overlay)

        border_rect = QRect(rect)
        border_rect.adjust(0, 0, -1, -1)
        border_path = QPainterPath()
        border_path.addRoundedRect(border_rect, 24, 24)
        painter.setPen(QPen(QColor(255, 255, 255, 36), 1))
        painter.drawPath(border_path)

        super().paintEvent(event)


def _build_section_shell(
    title: str,
    description: str,
    *,
    parent: QWidget | None = None,
) -> tuple[QFrame, QVBoxLayout, QLabel]:
    section = QFrame(parent)
    section.setObjectName("accessSection")
    layout = QVBoxLayout(section)
    layout.setContentsMargins(20, 18, 20, 18)
    layout.setSpacing(12)

    title_label = QLabel(title, section)
    title_label.setObjectName("sectionTitle")
    description_label = QLabel(description, section)
    description_label.setObjectName("sectionDescription")
    description_label.setWordWrap(True)

    layout.addWidget(title_label)
    layout.addWidget(description_label)
    return section, layout, description_label


class BootstrapFirstAdminDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("AccessAuxDialog")
        self.setWindowTitle("Criar primeiro administrador")
        self.setModal(True)
        self.setMinimumWidth(460)
        _apply_access_dialog_theme(self)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)

        shell = QFrame(self)
        shell.setObjectName("accessShell")
        _apply_shadow(shell, blur_radius=26.0, offset_y=8.0)
        root.addWidget(shell)

        layout = QVBoxLayout(shell)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(16)

        title = QLabel("Criar primeiro administrador", shell)
        title.setObjectName("accessTitle")
        title.setStyleSheet("font-size: 22px;")
        subtitle = QLabel(
            "Use este fluxo apenas na primeira configuração do ambiente de produção.",
            shell,
        )
        subtitle.setObjectName("accessSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)

        form_host = QFrame(shell)
        form_host.setObjectName("accessSection")
        form_layout = QFormLayout(form_host)
        form_layout.setContentsMargins(18, 18, 18, 18)
        form_layout.setSpacing(12)

        self.display_name_input = QLineEdit(form_host)
        self.email_input = QLineEdit(form_host)
        self.password_input = QLineEdit(form_host)
        self.confirm_password_input = QLineEdit(form_host)

        _configure_text_input(self.display_name_input, placeholder="Nome para exibição")
        _configure_text_input(self.email_input, placeholder="nome.sobrenome")
        _configure_text_input(self.password_input, placeholder="Senha inicial", password=True)
        _configure_text_input(self.confirm_password_input, placeholder="Repita a senha", password=True)

        rows = {
            "Nome": self.display_name_input,
            "Email": _build_corporate_email_row(self.email_input, parent=form_host),
            "Senha": self.password_input,
            "Confirmar": self.confirm_password_input,
        }
        for label_text, field in rows.items():
            label = QLabel(label_text, form_host)
            label.setObjectName("fieldLabel")
            form_layout.addRow(label, field)

        layout.addWidget(form_host)

        actions = QHBoxLayout()
        self.cancel_button = QPushButton("Cancelar", shell)
        self.submit_button = QPushButton("Criar administrador", shell)
        _set_button_role(self.cancel_button, "subtle")
        _set_button_role(self.submit_button, "primary")
        self.cancel_button.clicked.connect(self.reject)
        self.submit_button.clicked.connect(self._submit)
        actions.addWidget(self.cancel_button)
        actions.addStretch(1)
        actions.addWidget(self.submit_button)
        layout.addLayout(actions)

    def payload(self) -> dict[str, str]:
        return {
            "display_name": self.display_name_input.text().strip(),
            "email": _normalize_corporate_email_field(self.email_input),
            "password": self.password_input.text(),
        }

    def _submit(self) -> None:
        payload = self.payload()
        confirmation = self.confirm_password_input.text()
        if not payload["display_name"]:
            QMessageBox.warning(self, "Criar administrador", "Informe o nome do administrador.")
            return
        if not payload["email"]:
            QMessageBox.warning(self, "Criar administrador", "Informe o email corporativo do administrador.")
            return
        if len(payload["password"]) < 8:
            QMessageBox.warning(self, "Criar administrador", "A senha precisa ter pelo menos 8 caracteres.")
            return
        if payload["password"] != confirmation:
            QMessageBox.warning(self, "Criar administrador", "A confirmação da senha não confere.")
            return
        self.accept()


class RequestPasswordResetDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("AccessAuxDialog")
        self.setWindowTitle("Recuperar senha")
        self.setModal(True)
        self.setMinimumWidth(420)
        _apply_access_dialog_theme(self)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)

        shell = QFrame(self)
        shell.setObjectName("accessShell")
        _apply_shadow(shell, blur_radius=26.0, offset_y=8.0)
        root.addWidget(shell)

        layout = QVBoxLayout(shell)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(16)

        title = QLabel("Recuperar senha", shell)
        title.setObjectName("accessTitle")
        title.setStyleSheet("font-size: 22px;")
        subtitle = QLabel(
            "Informe seu email corporativo para solicitar o código ou link de recuperação.",
            shell,
        )
        subtitle.setObjectName("accessSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)

        form_host = QFrame(shell)
        form_host.setObjectName("accessSection")
        form_layout = QFormLayout(form_host)
        form_layout.setContentsMargins(18, 18, 18, 18)
        form_layout.setSpacing(12)

        self.email_input = QLineEdit(form_host)
        _configure_text_input(
            self.email_input,
            placeholder="nome.sobrenome",
            tooltip="Digite apenas a parte antes do domínio corporativo.",
        )
        email_label = QLabel("Email", form_host)
        email_label.setObjectName("fieldLabel")
        form_layout.addRow(email_label, _build_corporate_email_row(self.email_input, parent=form_host))
        layout.addWidget(form_host)

        actions = QHBoxLayout()
        self.cancel_button = QPushButton("Cancelar", shell)
        self.submit_button = QPushButton("Enviar recuperação", shell)
        _set_button_role(self.cancel_button, "subtle")
        _set_button_role(self.submit_button, "primary")
        self.cancel_button.clicked.connect(self.reject)
        self.submit_button.clicked.connect(self._submit)
        actions.addWidget(self.cancel_button)
        actions.addStretch(1)
        actions.addWidget(self.submit_button)
        layout.addLayout(actions)

    def payload(self) -> dict[str, str]:
        return {"email": _normalize_corporate_email_field(self.email_input)}

    def _submit(self) -> None:
        payload = self.payload()
        if not payload["email"]:
            QMessageBox.warning(self, "Recuperar senha", "Informe seu email corporativo para continuar.")
            return
        self.accept()


class CompletePasswordResetDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("AccessAuxDialog")
        self.setWindowTitle("Concluir recuperação de senha")
        self.setModal(True)
        self.setMinimumWidth(500)
        _apply_access_dialog_theme(self)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)

        shell = QFrame(self)
        shell.setObjectName("accessShell")
        _apply_shadow(shell, blur_radius=26.0, offset_y=8.0)
        root.addWidget(shell)

        layout = QVBoxLayout(shell)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(16)

        title = QLabel("Concluir recuperação", shell)
        title.setObjectName("accessTitle")
        title.setStyleSheet("font-size: 22px;")
        subtitle = QLabel(
            "Cole o link ou código recebido e defina a nova senha para concluir a recuperação.",
            shell,
        )
        subtitle.setObjectName("accessSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)

        form_host = QFrame(shell)
        form_host.setObjectName("accessSection")
        form_layout = QFormLayout(form_host)
        form_layout.setContentsMargins(18, 18, 18, 18)
        form_layout.setSpacing(12)

        self.email_input = QLineEdit(form_host)
        self.recovery_input = QLineEdit(form_host)
        self.password_input = QLineEdit(form_host)
        self.confirm_password_input = QLineEdit(form_host)

        _configure_text_input(self.email_input, placeholder="nome.sobrenome")
        _configure_text_input(
            self.recovery_input,
            placeholder="Cole o link ou código recebido",
            tooltip="Aceita link completo ou código recebido por email.",
        )
        _configure_text_input(self.password_input, placeholder="Nova senha", password=True)
        _configure_text_input(self.confirm_password_input, placeholder="Repita a nova senha", password=True)

        rows = (
            ("Email", _build_corporate_email_row(self.email_input, parent=form_host)),
            ("Link ou código", self.recovery_input),
            ("Nova senha", self.password_input),
            ("Confirmar", self.confirm_password_input),
        )
        for label_text, field in rows:
            label = QLabel(label_text, form_host)
            label.setObjectName("fieldLabel")
            form_layout.addRow(label, field)

        layout.addWidget(form_host)

        actions = QHBoxLayout()
        self.cancel_button = QPushButton("Cancelar", shell)
        self.submit_button = QPushButton("Atualizar senha", shell)
        _set_button_role(self.cancel_button, "subtle")
        _set_button_role(self.submit_button, "primary")
        self.cancel_button.clicked.connect(self.reject)
        self.submit_button.clicked.connect(self._submit)
        actions.addWidget(self.cancel_button)
        actions.addStretch(1)
        actions.addWidget(self.submit_button)
        layout.addLayout(actions)

    def payload(self) -> dict[str, str]:
        return {
            "email": _normalize_corporate_email_field(self.email_input),
            "recovery_value": self.recovery_input.text().strip(),
            "new_password": self.password_input.text(),
        }

    def _submit(self) -> None:
        payload = self.payload()
        confirmation = self.confirm_password_input.text()
        if not payload["email"]:
            QMessageBox.warning(self, "Recuperar senha", "Informe seu email corporativo.")
            return
        if not payload["recovery_value"]:
            QMessageBox.warning(self, "Recuperar senha", "Cole o link ou código de recuperação recebido.")
            return
        if len(payload["new_password"]) < 8:
            QMessageBox.warning(self, "Recuperar senha", "A nova senha precisa ter pelo menos 8 caracteres.")
            return
        if payload["new_password"] != confirmation:
            QMessageBox.warning(self, "Recuperar senha", "A confirmação da nova senha não confere.")
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
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.access_service = access_service
        self.admin_users_service = admin_users_service or SupabaseAdminUsersService()
        self.access_session: AppAccessSession | None = None
        self._busy = False

        self.setObjectName("AccessDialog")
        self.setWindowTitle(f"Acesso - {APP_NAME}")
        self.setModal(True)
        self.setMinimumSize(1040, 640)
        self.setSizeGripEnabled(False)
        _apply_access_dialog_theme(self)

        self._build_ui()
        self._apply_defaults()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 22, 22, 22)

        self.shell = QFrame(self)
        self.shell.setObjectName("accessShell")
        _apply_shadow(self.shell, blur_radius=36.0, offset_y=12.0)
        root.addWidget(self.shell)

        shell_layout = QHBoxLayout(self.shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)

        self.visual_panel = SplashVisualPanel(self.shell)
        shell_layout.addWidget(self.visual_panel, stretch=12)

        self.form_pane = QFrame(self.shell)
        self.form_pane.setObjectName("accessFormPane")
        shell_layout.addWidget(self.form_pane, stretch=11)

        form_layout = QVBoxLayout(self.form_pane)
        form_layout.setContentsMargins(40, 34, 40, 34)
        form_layout.setSpacing(18)

        header_row = QHBoxLayout()
        header_row.setSpacing(14)

        logo_label = QLabel(self.form_pane)
        logo_icon = _dialog_icon()
        if not logo_icon.isNull():
            logo_label.setPixmap(logo_icon.pixmap(54, 54))
        logo_label.setFixedSize(56, 56)
        logo_label.setAlignment(Qt.AlignCenter)
        logo_label.setStyleSheet(
            "background-color: rgba(40, 109, 196, 0.10);"
            "border: 1px solid rgba(40, 109, 196, 0.12);"
            "border-radius: 18px;"
        )

        title_stack = QVBoxLayout()
        title_stack.setContentsMargins(0, 0, 0, 0)
        title_stack.setSpacing(4)
        eyebrow = QLabel("ACESSO AO AMBIENTE", self.form_pane)
        eyebrow.setObjectName("accessEyebrow")
        title = QLabel(APP_NAME, self.form_pane)
        title.setObjectName("accessTitle")
        subtitle = QLabel(
            "Entre no ambiente de produção, explore a demonstração ou recupere o acesso com a mesma identidade visual do sistema.",
            self.form_pane,
        )
        subtitle.setObjectName("accessSubtitle")
        subtitle.setWordWrap(True)
        title_stack.addWidget(eyebrow)
        title_stack.addWidget(title)
        title_stack.addWidget(subtitle)

        header_row.addWidget(logo_label, stretch=0, alignment=Qt.AlignTop)
        header_row.addLayout(title_stack, stretch=1)
        form_layout.addLayout(header_row)

        self.production_group, production_layout, self.production_hint = _build_section_shell(
            "Produção",
            "Use sua conta institucional para acessar a base oficial compartilhada.",
            parent=self.form_pane,
        )
        production_form = QFormLayout()
        production_form.setContentsMargins(0, 0, 0, 0)
        production_form.setSpacing(10)

        self.email_input = QLineEdit(self.production_group)
        self.password_input = QLineEdit(self.production_group)
        _configure_text_input(
            self.email_input,
            placeholder="nome.sobrenome",
            tooltip="Digite apenas a parte antes do domínio corporativo.",
        )
        _configure_text_input(
            self.password_input,
            placeholder="Senha",
            tooltip="Use a mesma senha cadastrada no ambiente de produção.",
            password=True,
        )

        self.production_button = QPushButton("Entrar em Produção", self.production_group)
        self.forgot_password_button = QPushButton("Recuperar senha", self.production_group)
        self.bootstrap_button = QPushButton("Criar primeiro administrador", self.production_group)
        self.production_status = QLabel("", self.production_group)
        self.production_status.setObjectName("accessStatusText")
        self.production_status.setWordWrap(True)

        self.production_button.setToolTip("Autentica na base oficial do Supabase e sincroniza o cache local.")
        self.forgot_password_button.setToolTip("Solicita um link ou código de recuperação para sua conta institucional.")
        self.bootstrap_button.setToolTip("Use apenas na primeira configuração do ambiente de produção.")
        _set_button_role(self.production_button, "primary")
        _set_button_role(self.forgot_password_button, "secondary")
        _set_button_role(self.bootstrap_button, "subtle")

        email_label = QLabel("Email", self.production_group)
        email_label.setObjectName("fieldLabel")
        password_label = QLabel("Senha", self.production_group)
        password_label.setObjectName("fieldLabel")
        production_form.addRow(email_label, _build_corporate_email_row(self.email_input, parent=self.production_group))
        production_form.addRow(password_label, self.password_input)
        production_layout.addLayout(production_form)
        production_layout.addWidget(self.production_status)

        production_actions = QHBoxLayout()
        production_actions.setSpacing(10)
        production_actions.addWidget(self.production_button, stretch=1)
        production_layout.addLayout(production_actions)

        production_secondary = QHBoxLayout()
        production_secondary.setSpacing(10)
        production_secondary.addWidget(self.forgot_password_button, stretch=1)
        production_secondary.addWidget(self.bootstrap_button, stretch=1)
        production_layout.addLayout(production_secondary)

        self.demo_group, demo_layout, self.demo_hint = _build_section_shell(
            "Demonstração",
            "Abra uma base fictícia isolada para conhecer a experiência do produto sem impactar a produção.",
            parent=self.form_pane,
        )
        self.demo_button = QPushButton("Entrar em Demonstração", self.demo_group)
        self.demo_button.setToolTip("Abre a base de demonstração com dados fictícios e independentes da produção.")
        _set_button_role(self.demo_button, "success")
        demo_layout.addWidget(self.demo_button)

        self.status_panel = QFrame(self.form_pane)
        self.status_panel.setObjectName("accessStatusPanel")
        status_layout = QVBoxLayout(self.status_panel)
        status_layout.setContentsMargins(18, 16, 18, 16)
        status_layout.setSpacing(6)
        status_title = QLabel("Estado do acesso", self.status_panel)
        status_title.setObjectName("sectionTitle")
        status_title.setStyleSheet("font-size: 14px;")
        self.status_label = QLabel(
            "Selecione como deseja entrar. O ambiente de produção usa autenticação institucional e cache sincronizado.",
            self.status_panel,
        )
        self.status_label.setObjectName("accessHint")
        self.status_label.setWordWrap(True)
        status_layout.addWidget(status_title)
        status_layout.addWidget(self.status_label)

        footer_row = QHBoxLayout()
        footer_row.setSpacing(10)
        footer_row.addStretch(1)
        self.cancel_button = QPushButton("Cancelar", self.form_pane)
        self.cancel_button.setToolTip("Fecha a tela de acesso sem abrir o aplicativo.")
        _set_button_role(self.cancel_button, "subtle")
        footer_row.addWidget(self.cancel_button, stretch=0)

        form_layout.addWidget(self.production_group)
        form_layout.addWidget(self.demo_group)
        form_layout.addWidget(self.status_panel)
        form_layout.addStretch(1)
        form_layout.addLayout(footer_row)

        self.production_button.clicked.connect(self._handle_production_login)
        self.forgot_password_button.clicked.connect(self._handle_password_reset_request)
        self.bootstrap_button.clicked.connect(self._handle_bootstrap_admin)
        self.demo_button.clicked.connect(self._handle_demo_entry)
        self.cancel_button.clicked.connect(self.reject)

    def _apply_defaults(self) -> None:
        last_access_email = self.settings.last_access_email()
        if last_access_email:
            self.email_input.setText(display_corporate_email_local_part(last_access_email))

        if self.access_service.can_sign_in_production():
            self.production_status.setText("Use seu email corporativo para autenticar no ambiente oficial.")
            self.email_input.setEnabled(True)
            self.password_input.setEnabled(True)
            self.production_button.setEnabled(True)
            self.forgot_password_button.setEnabled(True)
        else:
            self.production_status.setText("A autenticação de produção ainda não está configurada nesta instalação.")
            self.email_input.setEnabled(False)
            self.password_input.setEnabled(False)
            self.production_button.setEnabled(False)
            self.forgot_password_button.setEnabled(False)

        demo_label_resolver = getattr(self.access_service, "demo_entry_label", None)
        demo_hint = demo_label_resolver() if callable(demo_label_resolver) else "Demonstração"
        self.demo_hint.setText(
            f"Abra o ambiente de {demo_hint.lower()} para navegar pelo sistema com dados fictícios."
        )
        can_open_demo = getattr(self.access_service, "can_open_demo", lambda: True)
        self.demo_button.setEnabled(bool(can_open_demo()))

        self._apply_bootstrap_availability()

        if self.settings.last_access_environment().strip().lower() == "demo":
            self.demo_button.setFocus()
        elif self.email_input.isEnabled() and not self.email_input.text().strip():
            self.email_input.setFocus()
        elif self.password_input.isEnabled():
            self.password_input.setFocus()

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self._busy = bool(busy)
        if busy:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            for widget in (
                self.email_input,
                self.password_input,
                self.production_button,
                self.forgot_password_button,
                self.bootstrap_button,
                self.demo_button,
                self.cancel_button,
            ):
                widget.setEnabled(False)
            if message:
                self.status_label.setText(message)
            return

        while QApplication.overrideCursor() is not None:
            QApplication.restoreOverrideCursor()

        self.cancel_button.setEnabled(True)
        production_available = self.access_service.can_sign_in_production()
        self.email_input.setEnabled(production_available)
        self.password_input.setEnabled(production_available)
        self.production_button.setEnabled(production_available)
        self.forgot_password_button.setEnabled(production_available)
        can_open_demo = getattr(self.access_service, "can_open_demo", lambda: True)
        self.demo_button.setEnabled(bool(can_open_demo()))
        self._apply_bootstrap_availability()
        if message:
            self.status_label.setText(message)
        elif not self.status_label.text().strip():
            self.status_label.setText(
                "Selecione como deseja entrar. O ambiente de produção usa autenticação institucional e cache sincronizado."
            )

    def _apply_bootstrap_availability(self) -> None:
        if not self.access_service.can_sign_in_production() or self.admin_users_service is None:
            self.bootstrap_button.hide()
            return

        try:
            status = self.admin_users_service.bootstrap_status()
        except AdminUsersError as exc:
            self.bootstrap_button.hide()
            self.production_status.setText(str(exc))
            return

        should_show = bool(getattr(status, "allowed", False))
        self.bootstrap_button.setVisible(should_show)
        self.bootstrap_button.setEnabled(should_show and not self._busy)
        status_message = str(getattr(status, "message", "") or "").strip()
        if status_message:
            self.production_status.setText(status_message)

    def _handle_production_login(self) -> None:
        email = _normalize_corporate_email_field(self.email_input)
        password = self.password_input.text()
        if not email or not password:
            QMessageBox.warning(self, "Produção", "Informe email e senha para entrar em produção.")
            return

        self._set_busy(True, "Autenticando em Produção e sincronizando a base oficial...")
        try:
            session = self.access_service.sign_in_production(email=email, password=password)
        except AccessAuthError as exc:
            self.password_input.clear()
            self.production_status.setText(str(exc))
            self._set_busy(False, str(exc))
            QMessageBox.warning(self, "Produção", str(exc))
            return

        self.settings.set_last_access_environment("production")
        self.settings.set_last_access_email(session.user_email or email)
        self.access_session = session
        self._set_busy(False, "")
        self.accept()

    def _handle_password_reset_request(self) -> None:
        request_dialog = RequestPasswordResetDialog(self)
        request_dialog.email_input.setText(self.email_input.text().strip())
        if not request_dialog.exec():
            return

        payload = request_dialog.payload()
        self._set_busy(True, "Solicitando o fluxo de recuperação no ambiente de produção...")
        try:
            request_message = self.access_service.request_password_reset(email=payload["email"])
        except AccessAuthError as exc:
            self._set_busy(False, str(exc))
            QMessageBox.warning(self, "Recuperar senha", str(exc))
            return
        self._set_busy(False, "")
        QMessageBox.information(self, "Recuperar senha", request_message)

        completion_dialog = CompletePasswordResetDialog(self)
        completion_dialog.email_input.setText(display_corporate_email_local_part(payload["email"]))
        if not completion_dialog.exec():
            return

        completion_payload = completion_dialog.payload()
        self._set_busy(True, "Concluindo a redefinição de senha...")
        try:
            completion_message = self.access_service.complete_password_reset(
                email=completion_payload["email"],
                recovery_value=completion_payload["recovery_value"],
                new_password=completion_payload["new_password"],
            )
        except AccessAuthError as exc:
            self._set_busy(False, str(exc))
            QMessageBox.warning(self, "Recuperar senha", str(exc))
            return

        self.email_input.setText(display_corporate_email_local_part(completion_payload["email"]))
        self.password_input.clear()
        self._set_busy(False, "")
        QMessageBox.information(self, "Recuperar senha", completion_message)

    def _handle_bootstrap_admin(self) -> None:
        bootstrap_dialog = BootstrapFirstAdminDialog(self)
        bootstrap_dialog.email_input.setText(self.email_input.text().strip())
        if not bootstrap_dialog.exec():
            return

        payload = bootstrap_dialog.payload()
        self._set_busy(True, "Criando o primeiro administrador e autenticando em produção...")
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
            self._set_busy(False, str(exc))
            QMessageBox.warning(self, "Criar administrador", str(exc))
            return

        self.settings.set_last_access_environment("production")
        self.settings.set_last_access_email(session.user_email or payload["email"])
        self.access_session = session
        self._set_busy(False, "")
        self.accept()

    def _handle_demo_entry(self) -> None:
        self._set_busy(True, "Preparando o ambiente de demonstração...")
        try:
            session = self.access_service.enter_demo()
        except AccessAuthError as exc:
            self._set_busy(False, str(exc))
            QMessageBox.warning(self, "Demonstração", str(exc))
            return

        self.settings.set_last_access_environment("demo")
        self.access_session = session
        self._set_busy(False, "")
        self.accept()
