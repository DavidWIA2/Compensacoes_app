from pathlib import Path, PureWindowsPath

from app import __version__ as APP_VERSION
from app.config import (
    APP_COMPANY_NAME,
    APP_EXECUTABLE_NAME,
    APP_INSTALLER_BASENAME,
    APP_INSTALLER_ID,
    APP_NAME,
    APP_PRODUCT_DESCRIPTION,
)
from app.services.release_metadata import build_release_version_label


def _win_path(path: str) -> str:
    return str(PureWindowsPath(Path(path).resolve()))


def _escape_inno(value: str) -> str:
    return str(value or "").replace('"', '""')


def build_installer_base_filename(version: str = APP_VERSION, arch_suffix: str = "win64") -> str:
    clean_version = str(version or "").strip()
    return f"{APP_INSTALLER_BASENAME}-v{clean_version}-{arch_suffix}"


def build_inno_setup_script(
    *,
    source_dir: str,
    output_dir: str,
    version: str = APP_VERSION,
    app_name: str = APP_NAME,
    app_publisher: str = APP_COMPANY_NAME,
    app_description: str = APP_PRODUCT_DESCRIPTION,
    main_executable: str = APP_EXECUTABLE_NAME,
    app_id: str = APP_INSTALLER_ID,
    base_filename: str = "",
    app_version_label: str = "",
    setup_icon_file: str = "",
    publisher_url: str = "",
    support_url: str = "",
    updates_url: str = "",
) -> str:
    source_dir_text = _escape_inno(_win_path(source_dir))
    output_dir_text = _escape_inno(_win_path(output_dir))
    icon_path_text = _escape_inno(_win_path(setup_icon_file)) if setup_icon_file else ""
    shortcut_icon_name = "PlataformaGestaoAmbiental.ico"
    output_base = _escape_inno(base_filename or build_installer_base_filename(version))
    version_label = _escape_inno(app_version_label or build_release_version_label(version))
    setup_icon_line = f"SetupIconFile={{#MySetupIconFile}}\n" if icon_path_text else ""
    uninstall_display_icon_line = (
        f"UninstallDisplayIcon={{app}}\\{shortcut_icon_name}\n"
        if icon_path_text
        else "UninstallDisplayIcon={app}\\{#MyAppExeName}\n"
    )
    shortcut_icon_copy_line = (
        'Source: "{#MySetupIconFile}"; DestDir: "{app}"; DestName: "%s"; Flags: ignoreversion\n'
        % shortcut_icon_name
        if icon_path_text
        else ""
    )
    shortcut_icon_attribute = (
        '; IconFilename: "{app}\\%s"' % shortcut_icon_name
        if icon_path_text
        else ""
    )

    return r"""; Script gerado automaticamente. Ajuste somente por geracao controlada.
#define MyAppName "%(app_name)s"
#define MyAppVersion "%(version)s"
#define MyAppVersionLabel "%(version_label)s"
#define MyAppPublisher "%(app_publisher)s"
#define MyAppExeName "%(main_executable)s"
#define MyAppDescription "%(app_description)s"
#define MyAppId "%(app_id)s"
#define MyAppSourceDir "%(source_dir)s"
#define MyAppOutputDir "%(output_dir)s"
#define MyAppOutputBaseFilename "%(output_base)s"
#define MyAppPublisherURL "%(publisher_url)s"
#define MyAppSupportURL "%(support_url)s"
#define MyAppUpdatesURL "%(updates_url)s"
#define MySetupIconFile "%(icon_path)s"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersionLabel}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppPublisherURL}
AppSupportURL={#MyAppSupportURL}
AppUpdatesURL={#MyAppUpdatesURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#MyAppOutputDir}
OutputBaseFilename={#MyAppOutputBaseFilename}
%(setup_icon_line)s%(uninstall_display_icon_line)sCompression=lzma
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na area de trabalho"; GroupDescription: "Atalhos adicionais:"; Flags: unchecked

[Files]
Source: "{#MyAppSourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
%(shortcut_icon_copy_line)s
[InstallDelete]
Type: files; Name: "{app}\_internal\assets\Logo_mono_512.png"
Type: files; Name: "{app}\Logo_mono_512.png"

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"%(shortcut_icon_attribute)s
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Check: ShouldInstallDesktopShortcut%(shortcut_icon_attribute)s

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Executar {#MyAppName}"; Flags: nowait postinstall skipifsilent

[Code]
function ShouldInstallDesktopShortcut(): Boolean;
begin
  Result := WizardIsTaskSelected('desktopicon') or FileExists(ExpandConstant('{autodesktop}\{#MyAppName}.lnk'));
end;
""" % {
        "app_name": _escape_inno(app_name),
        "version": _escape_inno(version),
        "version_label": version_label,
        "app_publisher": _escape_inno(app_publisher),
        "main_executable": _escape_inno(main_executable),
        "app_description": _escape_inno(app_description),
        "app_id": _escape_inno(app_id),
        "source_dir": source_dir_text,
        "output_dir": output_dir_text,
        "output_base": output_base,
        "publisher_url": _escape_inno(publisher_url),
        "support_url": _escape_inno(support_url),
        "updates_url": _escape_inno(updates_url),
        "icon_path": icon_path_text,
        "setup_icon_line": setup_icon_line,
        "uninstall_display_icon_line": uninstall_display_icon_line,
        "shortcut_icon_copy_line": shortcut_icon_copy_line,
        "shortcut_icon_attribute": shortcut_icon_attribute,
    }
