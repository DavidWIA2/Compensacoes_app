from __future__ import annotations

from PySide6.QtCore import QEvent, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QBoxLayout,
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
from app.services.password_policy import PASSWORD_POLICY_SUMMARY, password_validation_error
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
QFrame#accessStatusPanel[state="error"] {
    background-color: rgba(255,241,241,0.96);
    border: 1px solid rgba(194,63,63,0.28);
}
QFrame#accessStatusPanel[state="error"] QLabel#sectionTitle { color: #8f2f2f; }
QFrame#accessStatusPanel[state="error"] QLabel#accessHint { color: #7d3838; font-weight: 600; }
QFrame#accessStatusPanel[state="error"] QLabel#accessBadge {
    color: #7d3838;
    background-color: rgba(194,63,63,0.08);
    border: 1px solid rgba(194,63,63,0.18);
}
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
QLabel#accessBadge {
    color: #20446f;
    background-color: rgba(255,255,255,0.16);
    border: 1px solid rgba(255,255,255,0.18);
    border-radius: 11px;
    padding: 5px 10px;
    font-size: 11px;
    font-weight: 700;
}
QFrame#accessBadgeRow {
    background: transparent;
    border: none;
}
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


def _build_password_row(
    input_field: QLineEdit,
    *,
    parent: QWidget | None = None,
    show_label: str = "Mostrar",
    hide_label: str = "Ocultar",
) -> tuple[QWidget, QPushButton]:
    container = QWidget(parent)
    container_layout = QHBoxLayout(container)
    container_layout.setContentsMargins(0, 0, 0, 0)
    container_layout.setSpacing(8)

    toggle_button = QPushButton(show_label, container)
    toggle_button.setCheckable(True)
    toggle_button.setAutoDefault(False)
    toggle_button.setDefault(False)
    toggle_button.setMinimumWidth(88)
    toggle_button.setToolTip("Alterna a visibilidade da senha digitada.")
    _set_button_role(toggle_button, "subtle")

    def _sync_visibility(checked: bool) -> None:
        input_field.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)
        toggle_button.setText(hide_label if checked else show_label)

    toggle_button.toggled.connect(_sync_visibility)
    _sync_visibility(False)

    container_layout.addWidget(input_field, stretch=1)
    container_layout.addWidget(toggle_button, stretch=0)
    return container, toggle_button


def _normalize_corporate_email_field(input_field: QLineEdit) -> str:
    return normalize_corporate_email(input_field.text())


def _build_access_badge_row(*texts: str, parent: QWidget | None = None) -> QWidget:
    container = QFrame(parent)
    container.setObjectName("accessBadgeRow")
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    for text in texts:
        if not str(text).strip():
            continue
        label = QLabel(str(text), container)
        label.setObjectName("accessBadge")
        layout.addWidget(label, 0)
    layout.addStretch(1)
    return container


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
            "Compensações, TCRAs e monitoramento ambiental no mesmo ambiente institucional.",
            "Acesso de produção com autenticação corporativa, demonstração isolada e base sincronizada.",
            "Experiência alinhada à rotina operacional da Prefeitura, com leitura clara e ações guiadas.",
        ):
            label = QLabel(text, feature_block)
            label.setWordWrap(True)
            label.setStyleSheet("color: rgba(255,255,255,0.86); font-size: 12px;")
            feature_layout.addWidget(label)

        badges = _build_access_badge_row(
            "Base oficial protegida",
            "Conta corporativa",
            "Operação assistida",
            parent=self,
        )

        footer = QLabel(
            "Uso institucional com identidade corporativa, base oficial protegida e suporte operacional.",
            self,
        )
        footer.setWordWrap(True)
        footer.setStyleSheet("color: rgba(255,255,255,0.8); font-size: 12px; font-weight: 600;")

        layout.addWidget(eyebrow, stretch=0, alignment=Qt.AlignTop)
        layout.addSpacing(6)
        layout.addWidget(title, stretch=0)
        layout.addWidget(subtitle, stretch=0)
        layout.addWidget(accent, stretch=0)
        layout.addWidget(badges, stretch=0)
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
        self.header_subtitle = QLabel(
            "Use este fluxo apenas na primeira configuração do ambiente oficial da Prefeitura.",
            shell,
        )
        self.header_subtitle.setObjectName("accessSubtitle")
        self.header_subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(self.header_subtitle)
        layout.addWidget(
            _build_access_badge_row("Primeiro acesso", "Perfil administrador", parent=shell)
        )

        form_host = QFrame(shell)
        form_host.setObjectName("accessSection")
        form_layout = QFormLayout(form_host)
        form_layout.setContentsMargins(18, 18, 18, 18)
        form_layout.setSpacing(12)

        self.display_name_input = QLineEdit(form_host)
        self.email_input = QLineEdit(form_host)
        self.password_input = QLineEdit(form_host)
        self.confirm_password_input = QLineEdit(form_host)
        password_row, self.password_toggle_button = _build_password_row(self.password_input, parent=form_host)
        confirm_password_row, self.confirm_password_toggle_button = _build_password_row(
            self.confirm_password_input,
            parent=form_host,
        )

        _configure_text_input(self.display_name_input, placeholder="Nome para exibição")
        _configure_text_input(self.email_input, placeholder="nome.sobrenome")
        _configure_text_input(self.password_input, placeholder="Senha inicial", password=True)
        _configure_text_input(self.confirm_password_input, placeholder="Repita a senha", password=True)

        rows = {
            "Nome": self.display_name_input,
            "Email": _build_corporate_email_row(self.email_input, parent=form_host),
            "Senha": password_row,
            "Confirmar": confirm_password_row,
        }
        for label_text, field in rows.items():
            label = QLabel(label_text, form_host)
            label.setObjectName("fieldLabel")
            form_layout.addRow(label, field)

        layout.addWidget(form_host)

        helper = QLabel(
            (
                "Use o nome corporativo do servidor e defina uma senha inicial forte "
                f"({PASSWORD_POLICY_SUMMARY}) antes de liberar o primeiro acesso."
            ),
            shell,
        )
        helper.setObjectName("accessHint")
        helper.setWordWrap(True)
        layout.addWidget(helper)

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
        password_error = password_validation_error(payload["password"])
        if password_error:
            QMessageBox.warning(self, "Criar administrador", password_error)
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
            "Informe seu email corporativo para solicitar um código ou link de recuperação diretamente no ambiente oficial.",
            shell,
        )
        subtitle.setObjectName("accessSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(
            _build_access_badge_row("Conta corporativa", "Fluxo oficial", parent=shell)
        )

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

        helper = QLabel(
            "Se preferir, um administrador também pode redefinir sua senha pela tela de Administração do sistema.",
            shell,
        )
        helper.setObjectName("accessHint")
        helper.setWordWrap(True)
        layout.addWidget(helper)

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
            "Cole o link ou código recebido por email e defina a nova senha para concluir a recuperação no próprio desktop.",
            shell,
        )
        subtitle.setObjectName("accessSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(
            _build_access_badge_row("Link ou código", "Redefinição segura", parent=shell)
        )

        form_host = QFrame(shell)
        form_host.setObjectName("accessSection")
        form_layout = QFormLayout(form_host)
        form_layout.setContentsMargins(18, 18, 18, 18)
        form_layout.setSpacing(12)

        self.email_input = QLineEdit(form_host)
        self.recovery_input = QLineEdit(form_host)
        self.password_input = QLineEdit(form_host)
        self.confirm_password_input = QLineEdit(form_host)
        password_row, self.password_toggle_button = _build_password_row(self.password_input, parent=form_host)
        confirm_password_row, self.confirm_password_toggle_button = _build_password_row(
            self.confirm_password_input,
            parent=form_host,
        )

        _configure_text_input(self.email_input, placeholder="nome.sobrenome")
        _configure_text_input(
            self.recovery_input,
            placeholder="Cole o link ou código recebido",
            tooltip="Aceita link completo ou código recebido por email.",
        )
        _configure_text_input(
            self.password_input,
            placeholder=f"Nova senha ({PASSWORD_POLICY_SUMMARY})",
            password=True,
        )
        _configure_text_input(self.confirm_password_input, placeholder="Repita a nova senha", password=True)

        rows = (
            ("Email", _build_corporate_email_row(self.email_input, parent=form_host)),
            ("Link ou código", self.recovery_input),
            ("Nova senha", password_row),
            ("Confirmar", confirm_password_row),
        )
        for label_text, field in rows:
            label = QLabel(label_text, form_host)
            label.setObjectName("fieldLabel")
            form_layout.addRow(label, field)

        layout.addWidget(form_host)

        helper = QLabel(
            (
                "Voce pode colar o link completo recebido no email ou somente o codigo de recuperacao, "
                f"sem sair do aplicativo. A nova senha deve seguir: {PASSWORD_POLICY_SUMMARY}."
            ),
            shell,
        )
        helper.setObjectName("accessHint")
        helper.setWordWrap(True)
        layout.addWidget(helper)

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
        password_error = password_validation_error(payload["new_password"])
        if password_error:
            QMessageBox.warning(self, "Recuperar senha", password_error)
            return
        if payload["new_password"] != confirmation:
            QMessageBox.warning(self, "Recuperar senha", "A confirmação da nova senha não confere.")
            return
        self.accept()


class ChangePasswordDialog(QDialog):
    def __init__(
        self,
        *,
        title_text: str = "Alterar senha",
        subtitle_text: str = "",
        account_email: str = "",
        require_current_password: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("AccessAuxDialog")
        self.setWindowTitle(title_text)
        self.setModal(True)
        self.setMinimumWidth(500)
        self.require_current_password = bool(require_current_password)
        self._title_text = str(title_text or "Alterar senha")
        self._subtitle_text = str(subtitle_text or "").strip()
        self._account_email = str(account_email or "").strip()
        _apply_access_dialog_theme(self)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)

        shell = QFrame(self)
        shell.setObjectName("accessShell")
        _apply_shadow(shell, blur_radius=26.0, offset_y=8.0)
        root.addWidget(shell)

        layout = QVBoxLayout(shell)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(16)

        title = QLabel(self._title_text, shell)
        title.setObjectName("accessTitle")
        title.setStyleSheet("font-size: 22px;")
        subtitle = QLabel(
            self._subtitle_text
            or (
                "Confirme sua senha atual e defina uma nova senha pessoal para continuar."
                if self.require_current_password
                else "Este é o primeiro acesso com senha provisória. Defina agora sua senha pessoal."
            ),
            shell,
        )
        subtitle.setObjectName("accessSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(
            _build_access_badge_row(
                "Conta corporativa",
                "Senha pessoal",
                "Confirmação segura",
                parent=shell,
            )
        )

        form_host = QFrame(shell)
        form_host.setObjectName("accessSection")
        form_layout = QFormLayout(form_host)
        form_layout.setContentsMargins(18, 18, 18, 18)
        form_layout.setSpacing(12)

        self.current_password_input = QLineEdit(form_host)
        self.new_password_input = QLineEdit(form_host)
        self.confirm_password_input = QLineEdit(form_host)
        current_password_row = None
        self.current_password_toggle_button = None
        if self.require_current_password:
            current_password_row, self.current_password_toggle_button = _build_password_row(
                self.current_password_input,
                parent=form_host,
            )
        else:
            self.current_password_input.hide()
        new_password_row, self.new_password_toggle_button = _build_password_row(
            self.new_password_input,
            parent=form_host,
        )
        confirm_password_row, self.confirm_password_toggle_button = _build_password_row(
            self.confirm_password_input,
            parent=form_host,
        )

        _configure_text_input(
            self.current_password_input,
            placeholder="Senha atual",
            tooltip="Informe a senha atual da sua conta para confirmar a troca.",
            password=True,
        )
        _configure_text_input(
            self.new_password_input,
            placeholder=f"Nova senha ({PASSWORD_POLICY_SUMMARY})",
            tooltip=f"A nova senha deve seguir: {PASSWORD_POLICY_SUMMARY}.",
            password=True,
        )
        _configure_text_input(
            self.confirm_password_input,
            placeholder="Repita a nova senha",
            tooltip="Repita a nova senha exatamente como foi definida acima.",
            password=True,
        )
        self.confirm_password_input.returnPressed.connect(self._submit)

        if self._account_email:
            account_caption = QLabel("Conta", form_host)
            account_caption.setObjectName("fieldLabel")
            account_value = QLabel(self._account_email, form_host)
            account_value.setObjectName("accessHint")
            account_value.setWordWrap(True)
            account_value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            form_layout.addRow(account_caption, account_value)

        if self.require_current_password and current_password_row is not None:
            current_label = QLabel("Senha atual", form_host)
            current_label.setObjectName("fieldLabel")
            form_layout.addRow(current_label, current_password_row)

        new_label = QLabel("Nova senha", form_host)
        new_label.setObjectName("fieldLabel")
        confirm_label = QLabel("Confirmar", form_host)
        confirm_label.setObjectName("fieldLabel")
        form_layout.addRow(new_label, new_password_row)
        form_layout.addRow(confirm_label, confirm_password_row)

        layout.addWidget(form_host)

        helper = QLabel(
            (
                "A senha anterior deixa de ser necessaria assim que a atualizacao e concluida no ambiente oficial. "
                f"Use uma senha forte: {PASSWORD_POLICY_SUMMARY}."
            ),
            shell,
        )
        helper.setObjectName("accessHint")
        helper.setWordWrap(True)
        layout.addWidget(helper)

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
            "current_password": self.current_password_input.text(),
            "new_password": self.new_password_input.text(),
        }

    def _submit(self) -> None:
        payload = self.payload()
        confirmation = self.confirm_password_input.text()
        if self.require_current_password and not payload["current_password"]:
            QMessageBox.warning(self, self._title_text, "Informe sua senha atual para continuar.")
            return
        password_error = password_validation_error(payload["new_password"])
        if password_error:
            QMessageBox.warning(self, self._title_text, password_error)
            return
        if self.require_current_password and payload["current_password"] == payload["new_password"]:
            QMessageBox.warning(self, self._title_text, "A nova senha precisa ser diferente da senha atual.")
            return
        if payload["new_password"] != confirmation:
            QMessageBox.warning(self, self._title_text, "A confirmação da nova senha não confere.")
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
        self._status_panel_error = False
        self._saved_normal_geometry: QRect | None = None
        self._restore_normal_geometry_pending = False

        self.setObjectName("AccessDialog")
        self.setWindowTitle(f"Acesso - {APP_NAME}")
        self.setModal(True)
        self.setMinimumSize(920, 580)
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
        self.shell_layout = shell_layout
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)

        self.visual_panel = SplashVisualPanel(self.shell)
        shell_layout.addWidget(self.visual_panel, stretch=12)

        self.form_pane = QFrame(self.shell)
        self.form_pane.setObjectName("accessFormPane")
        shell_layout.addWidget(self.form_pane, stretch=11)

        form_layout = QVBoxLayout(self.form_pane)
        self.form_layout = form_layout
        form_layout.setContentsMargins(40, 34, 40, 34)
        form_layout.setSpacing(18)

        header_row = QHBoxLayout()
        self.header_row = header_row
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
        self.header_subtitle = QLabel(
            "Acesse a base oficial com autenticação corporativa, use a demonstração isolada para treinamento ou recupere sua senha mantendo o mesmo padrão institucional do sistema.",
            self.form_pane,
        )
        self.header_subtitle.setObjectName("accessSubtitle")
        self.header_subtitle.setWordWrap(True)
        title_stack.addWidget(eyebrow)
        title_stack.addWidget(title)
        self.header_badges = _build_access_badge_row(
            "Produção oficial",
            "Demonstração isolada",
            "Email corporativo",
            "Perfis controlados",
            parent=self.form_pane,
        )
        title_stack.addWidget(self.header_subtitle)
        title_stack.addWidget(self.header_badges)

        header_row.addWidget(logo_label, stretch=0, alignment=Qt.AlignTop)
        header_row.addLayout(title_stack, stretch=1)
        form_layout.addLayout(header_row)

        self.production_group, production_layout, self.production_hint = _build_section_shell(
            "Produção",
            "Use sua conta institucional da Prefeitura para acessar a base oficial compartilhada e auditável.",
            parent=self.form_pane,
        )
        production_layout.addWidget(
            _build_access_badge_row(
                "Base oficial protegida",
                "Sincronia ativa",
                "Uso corporativo",
                "Perfis com controle",
                parent=self.production_group,
            )
        )
        production_form = QFormLayout()
        production_form.setContentsMargins(0, 0, 0, 0)
        production_form.setSpacing(10)

        self.email_input = QLineEdit(self.production_group)
        self.password_input = QLineEdit(self.production_group)
        self.password_row, self.password_toggle_button = _build_password_row(
            self.password_input,
            parent=self.production_group,
        )
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

        self.production_button = QPushButton("Entrar na Produção", self.production_group)
        self.forgot_password_button = QPushButton("Esqueci minha senha", self.production_group)
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
        production_form.addRow(password_label, self.password_row)
        production_layout.addLayout(production_form)
        self.production_domain_hint = QLabel(
            "Digite apenas a parte antes de @saocarlos.sp.gov.br. O domínio corporativo é completado automaticamente.",
            self.production_group,
        )
        self.production_domain_hint.setObjectName("accessHint")
        self.production_domain_hint.setWordWrap(True)
        self.production_security_note = QLabel(
            "Somente contas autorizadas podem acessar a base oficial, sincronizar o cache local e abrir a administração de usuários.",
            self.production_group,
        )
        self.production_security_note.setObjectName("accessHint")
        self.production_security_note.setWordWrap(True)
        production_layout.addWidget(self.production_domain_hint)
        production_layout.addWidget(self.production_security_note)
        production_layout.addWidget(self.production_status)

        production_actions = QHBoxLayout()
        self.production_actions = production_actions
        production_actions.setSpacing(10)
        production_actions.addWidget(self.production_button, stretch=1)
        production_layout.addLayout(production_actions)

        self.production_secondary = QBoxLayout(QBoxLayout.LeftToRight)
        self.production_secondary.setContentsMargins(0, 0, 0, 0)
        self.production_secondary.setSpacing(10)
        self.production_secondary.addWidget(self.forgot_password_button, stretch=1)
        self.production_secondary.addWidget(self.bootstrap_button, stretch=1)
        production_layout.addLayout(self.production_secondary)

        self.demo_group, demo_layout, self.demo_hint = _build_section_shell(
            "Demonstração",
            "Abra uma base fictícia isolada para conhecer a experiência do produto sem qualquer escrita na produção.",
            parent=self.form_pane,
        )
        demo_layout.addWidget(
            _build_access_badge_row(
                "Treinamento",
                "Base separada",
                "Sem impacto na produção",
                parent=self.demo_group,
            )
        )
        self.demo_button = QPushButton("Abrir demonstração", self.demo_group)
        self.demo_button.setToolTip("Abre a base de demonstração com dados fictícios e independentes da produção.")
        _set_button_role(self.demo_button, "success")
        self.demo_note = QLabel(
            "Ideal para treinamento, testes e validação visual sem qualquer risco para a base oficial.",
            self.demo_group,
        )
        self.demo_note.setObjectName("accessHint")
        self.demo_note.setWordWrap(True)
        demo_layout.addWidget(self.demo_button)
        demo_layout.addWidget(self.demo_note)

        self.status_panel = QFrame(self.form_pane)
        self.status_panel.setObjectName("accessStatusPanel")
        status_layout = QVBoxLayout(self.status_panel)
        status_layout.setContentsMargins(18, 16, 18, 16)
        status_layout.setSpacing(6)
        status_title = QLabel("Orientação do acesso", self.status_panel)
        status_title.setObjectName("sectionTitle")
        status_title.setStyleSheet("font-size: 14px;")
        self.status_title = status_title
        self.status_label = QLabel(
            "Selecione como deseja entrar. Produção usa autenticação institucional e a base oficial sincronizada; Demonstração abre uma base isolada e segura para treinamento.",
            self.status_panel,
        )
        self.status_label.setObjectName("accessHint")
        self.status_label.setWordWrap(True)
        self.status_badges = _build_access_badge_row(
            "Produção: base oficial protegida",
            "Demonstração: ambiente isolado",
            "Administração: só em produção",
            parent=self.status_panel,
        )
        status_layout.addWidget(self.status_title)
        status_layout.addWidget(self.status_label)
        status_layout.addWidget(self.status_badges)

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
        self.email_input.editingFinished.connect(
            lambda: self.email_input.setText(display_corporate_email_local_part(self.email_input.text()))
        )
        self.password_input.returnPressed.connect(self._handle_production_login)

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self._capture_normal_geometry()
        self._apply_responsive_layout()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._capture_normal_geometry()
        self._apply_responsive_layout()

    def changeEvent(self, event) -> None:  # type: ignore[override]
        super().changeEvent(event)
        if event.type() != QEvent.WindowStateChange:
            return

        old_state = event.oldState() if hasattr(event, "oldState") else Qt.WindowState.WindowNoState
        was_expanded = self._is_expanded_window_state(old_state)
        is_expanded = self._is_expanded_window_state()

        if not was_expanded and is_expanded:
            self._capture_normal_geometry(force=True, prefer_normal_geometry=True)
        elif was_expanded and not is_expanded:
            self._schedule_restore_normal_geometry()

        QTimer.singleShot(0, self._apply_responsive_layout)

    def _is_expanded_window_state(self, state: Qt.WindowStates | None = None) -> bool:
        window_state = state if state is not None else self.windowState()
        expanded_states = Qt.WindowState.WindowMaximized | Qt.WindowState.WindowFullScreen
        return bool(window_state & expanded_states)

    def _capture_normal_geometry(
        self,
        *,
        force: bool = False,
        prefer_normal_geometry: bool = False,
    ) -> None:
        if not self.isVisible():
            return
        if not force and self._is_expanded_window_state():
            return

        geometry = QRect()
        if prefer_normal_geometry:
            geometry = QRect(self.normalGeometry())
        if not geometry.isValid() or geometry.width() <= 0 or geometry.height() <= 0:
            geometry = self.geometry()
        if geometry.isValid() and geometry.width() > 0 and geometry.height() > 0:
            self._saved_normal_geometry = QRect(geometry)

    def _schedule_restore_normal_geometry(self) -> None:
        if self._restore_normal_geometry_pending or self._saved_normal_geometry is None:
            return
        self._restore_normal_geometry_pending = True
        QTimer.singleShot(0, self._restore_saved_normal_geometry)

    def _restore_saved_normal_geometry(self) -> None:
        self._restore_normal_geometry_pending = False
        if self._saved_normal_geometry is None or self._is_expanded_window_state():
            return

        target_geometry = QRect(self._saved_normal_geometry)
        target_geometry.setWidth(max(target_geometry.width(), self.minimumWidth()))
        target_geometry.setHeight(max(target_geometry.height(), self.minimumHeight()))
        self.setGeometry(target_geometry)

    def _is_compact_layout(self) -> bool:
        if self._is_expanded_window_state():
            return True
        current_width = self.width()
        current_height = self.height()
        if current_width < 820 and not self.isVisible():
            current_width = 1280
        if current_height < 560 and not self.isVisible():
            current_height = 800
        return current_width <= 1220 or current_height <= 760

    def _is_tight_layout(self) -> bool:
        if self._is_expanded_window_state():
            return True
        current_width = self.width()
        current_height = self.height()
        if current_width < 820 and not self.isVisible():
            current_width = 1280
        if current_height < 560 and not self.isVisible():
            current_height = 800
        return current_width <= 1080 or current_height <= 700

    def _apply_responsive_layout(self) -> None:
        compact_mode = self._is_compact_layout()
        tight_mode = self._is_tight_layout()
        self.visual_panel.setVisible(not tight_mode)
        if hasattr(self, "header_subtitle"):
            self.header_subtitle.setVisible(not compact_mode)
        if hasattr(self, "header_badges"):
            self.header_badges.setVisible(not compact_mode)
        if hasattr(self, "production_domain_hint"):
            self.production_domain_hint.setVisible(not tight_mode)
        if hasattr(self, "production_security_note"):
            self.production_security_note.setVisible(not compact_mode)
        if hasattr(self, "demo_note"):
            self.demo_note.setVisible(not compact_mode)
        if hasattr(self, "status_badges"):
            self.status_badges.setVisible(not compact_mode)

        self.form_layout.setContentsMargins(
            24 if compact_mode else 40,
            22 if compact_mode else 34,
            24 if compact_mode else 40,
            22 if compact_mode else 34,
        )
        self.form_layout.setSpacing(14 if compact_mode else 18)
        self.header_row.setSpacing(10 if compact_mode else 14)
        self.production_secondary.setDirection(QBoxLayout.TopToBottom if tight_mode else QBoxLayout.LeftToRight)
        self.production_secondary.setSpacing(8 if compact_mode else 10)
        self.production_button.setText("Entrar" if tight_mode else "Entrar na Produção")
        self.forgot_password_button.setText("Recuperar senha" if compact_mode else "Esqueci minha senha")
        self.bootstrap_button.setText("Primeiro admin" if compact_mode else "Criar primeiro administrador")
        self.demo_button.setText("Abrir demo" if compact_mode else "Abrir demonstração")
        self.cancel_button.setText("Fechar" if compact_mode else "Cancelar")
        self.password_toggle_button.setText(
            "Ocultar" if self.password_toggle_button.isChecked() else ("Ver" if compact_mode else "Mostrar")
        )
        if hasattr(self, "status_badges"):
            self.status_badges.setVisible((not compact_mode) and not self._status_panel_error)

    def _default_access_status_message(self) -> str:
        return (
            "Selecione como deseja entrar. A produção usa autenticação institucional e a base oficial "
            "sincronizada; a demonstração abre uma base isolada e segura para treinamento."
        )

    def _apply_status_panel_state(self, state: str) -> None:
        self.status_panel.setProperty("state", state)
        self.status_panel.style().unpolish(self.status_panel)
        self.status_panel.style().polish(self.status_panel)
        self.status_panel.update()

    def _set_production_context_message(self, message: str) -> None:
        normalized_message = str(message or "").strip()
        self.production_status.setText(normalized_message)
        self.production_status.setVisible(bool(normalized_message))

    def _set_access_status_message(self, message: str, *, is_error: bool = False) -> None:
        normalized_message = str(message or "").strip() or self._default_access_status_message()
        self._status_panel_error = bool(is_error)
        self.status_title.setText("Erro de acesso" if is_error else "Orientação do acesso")
        self.status_label.setText(normalized_message)
        self._apply_status_panel_state("error" if is_error else "default")
        self._apply_responsive_layout()

    def _apply_defaults(self) -> None:
        last_access_email = self.settings.last_access_email()
        if last_access_email:
            self.email_input.setText(display_corporate_email_local_part(last_access_email))

        production_reason_resolver = getattr(
            self.access_service,
            "production_sign_in_unavailability_reason",
            None,
        )
        production_unavailability_reason = (
            production_reason_resolver()
            if callable(production_reason_resolver)
            else "A autenticação da produção oficial ainda não está configurada nesta instalação."
        )

        production_available_resolver = getattr(
            self.access_service,
            "production_sign_in_available",
            self.access_service.can_sign_in_production,
        )

        if production_available_resolver():
            self._set_production_context_message(
                "Produção oficial pronta para autenticação com email corporativo e sincronização da base protegida."
            )
            self.email_input.setEnabled(True)
            self.password_input.setEnabled(True)
            self.production_button.setEnabled(True)
            self.forgot_password_button.setEnabled(True)
            self.password_toggle_button.setEnabled(True)
        else:
            self._set_production_context_message(
                "A autenticação da produção oficial ainda não está configurada nesta instalação."
            )
            self.email_input.setEnabled(False)
            self.password_input.setEnabled(False)
            self.production_button.setEnabled(False)
            self.forgot_password_button.setEnabled(False)
            self.password_toggle_button.setEnabled(False)

        if not production_available_resolver():
            self._set_production_context_message(production_unavailability_reason)

        demo_label_resolver = getattr(self.access_service, "demo_entry_label", None)
        demo_hint = demo_label_resolver() if callable(demo_label_resolver) else "Demonstração"
        self.demo_hint.setText(
            f"Abra o ambiente de {demo_hint.lower()} para navegar pelo sistema com dados fictícios e independentes."
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

        self._set_access_status_message(self._default_access_status_message(), is_error=False)
        self._apply_responsive_layout()

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
                self.password_toggle_button,
            ):
                widget.setEnabled(False)
            if message:
                self._set_access_status_message(message, is_error=False)
            return

        while QApplication.overrideCursor() is not None:
            QApplication.restoreOverrideCursor()

        production_reason_resolver = getattr(
            self.access_service,
            "production_sign_in_unavailability_reason",
            None,
        )
        production_unavailability_reason = (
            production_reason_resolver()
            if callable(production_reason_resolver)
            else "A autenticação da produção oficial ainda não está configurada nesta instalação."
        )

        self.cancel_button.setEnabled(True)
        production_available_resolver = getattr(
            self.access_service,
            "production_sign_in_available",
            self.access_service.can_sign_in_production,
        )
        production_available = production_available_resolver()
        self.email_input.setEnabled(production_available)
        self.password_input.setEnabled(production_available)
        self.production_button.setEnabled(production_available)
        self.forgot_password_button.setEnabled(production_available)
        self.password_toggle_button.setEnabled(production_available)
        if not production_available:
            self._set_production_context_message(production_unavailability_reason)

        can_open_demo = getattr(self.access_service, "can_open_demo", lambda: True)
        self.demo_button.setEnabled(bool(can_open_demo()))
        self._apply_bootstrap_availability()

        if message:
            self._set_production_context_message("")
            self._set_access_status_message(message, is_error=True)
        elif not self.status_label.text().strip() or self._status_panel_error:
            self._set_access_status_message(self._default_access_status_message(), is_error=False)
        self._apply_responsive_layout()

    def _apply_bootstrap_availability(self) -> None:
        production_available_resolver = getattr(
            self.access_service,
            "production_sign_in_available",
            self.access_service.can_sign_in_production,
        )
        if not production_available_resolver() or self.admin_users_service is None:
            self.bootstrap_button.hide()
            return

        try:
            status = self.admin_users_service.bootstrap_status()
        except AdminUsersError as exc:
            self.bootstrap_button.hide()
            self._set_production_context_message(str(exc))
            return

        should_show = bool(getattr(status, "allowed", False))
        self.bootstrap_button.setVisible(should_show)
        self.bootstrap_button.setEnabled(should_show and not self._busy)
        status_message = str(getattr(status, "message", "") or "").strip()
        if status_message:
            self._set_production_context_message(status_message)

    def _handle_production_login(self) -> None:
        email = _normalize_corporate_email_field(self.email_input)
        password = self.password_input.text()
        if not email or not password:
            self._set_production_context_message("")
            self._set_access_status_message("Informe email e senha para entrar em produção.", is_error=True)
            QMessageBox.warning(self, "Produção", "Informe email e senha para entrar em produção.")
            return

        self._set_busy(True, "Autenticando na Produção e sincronizando a base oficial...")
        try:
            session = self.access_service.sign_in_production(email=email, password=password)
        except AccessAuthError as exc:
            self.password_input.clear()
            self._set_production_context_message("")
            self._set_busy(False, str(exc))
            QMessageBox.warning(self, "Produção", str(exc))
            return

        self._set_busy(False, "")
        self._complete_production_access(
            session=session,
            email=email,
            current_password=password,
        )

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
        self._set_busy(True, "Criando o primeiro administrador e autenticando na produção...")
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

        self._set_busy(False, "")
        self._complete_production_access(
            session=session,
            email=payload["email"],
            current_password=payload["password"],
        )

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

    def _complete_production_access(
        self,
        *,
        session: AppAccessSession,
        email: str,
        current_password: str,
    ) -> None:
        finalized_session = session
        if bool(getattr(session, "must_change_password", False)):
            password_dialog = ChangePasswordDialog(
                title_text="Definir senha pessoal",
                subtitle_text=(
                    "Este é o primeiro acesso com a senha provisória informada pelo administrador. "
                    "Defina agora sua senha pessoal para concluir a entrada."
                ),
                account_email=session.user_email or email,
                require_current_password=False,
                parent=self,
            )
            if not password_dialog.exec():
                self.access_service.sign_out_session(session)
                self.password_input.clear()
                message = "Defina sua senha pessoal para concluir o primeiro acesso."
                self._set_production_context_message("")
                self._set_access_status_message(message, is_error=False)
                return

            try:
                finalized_session = self.access_service.change_password(
                    access_session=session,
                    current_password=current_password,
                    new_password=password_dialog.payload()["new_password"],
                )
            except AccessAuthError as exc:
                self.access_service.sign_out_session(session)
                self.password_input.clear()
                self._set_production_context_message("")
                self._set_access_status_message(str(exc), is_error=True)
                QMessageBox.warning(self, "Primeiro acesso", str(exc))
                return

            QMessageBox.information(
                self,
                "Primeiro acesso",
                "Senha pessoal definida com sucesso. O acesso à produção foi concluído.",
            )

        self.settings.set_last_access_environment("production")
        self.settings.set_last_access_email(finalized_session.user_email or email)
        self.access_session = finalized_session
        self.accept()

