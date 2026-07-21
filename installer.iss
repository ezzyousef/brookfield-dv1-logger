; Inno Setup script for Brookfield DV1 Viscosity Logger
;
; Wraps the standalone PyInstaller build (dist\DV1Logger\, an onedir build --
; DV1Logger.exe plus every bundled dependency as loose files in that folder;
; no Python needs to be installed on the target PC) into a normal Windows
; installer: Start Menu shortcut, optional Desktop shortcut, Add/Remove
; Programs entry, and a proper uninstaller.
;
; Requires dist\DV1Logger\ to already exist -- run
; `pyinstaller DV1Logger.spec` from this folder first.

#define MyAppName "DV1 Logger"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Ezzeldien Yousef"
#define MyAppURL "mailto:ezzyousef2@aucegypt.edu"
#define MyAppExeName "DV1Logger.exe"
#define MyAppCopyright "Copyright (C) 2026 Ezzeldien Yousef"

[Setup]
AppId={{B3F2C7B0-6B7A-4E9B-9C1E-2C6C5B8D9A11}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppCopyright={#MyAppCopyright}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=installer_output
OutputBaseFilename=DV1Logger-Setup
SetupIconFile=assets\app_icon.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; The whole onedir build folder (DV1Logger.exe + every bundled DLL/data
; file it needs at runtime), recursively -- NOT just the exe.
Source: "dist\DV1Logger\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "assets\app_icon.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; IconFilename is set explicitly so the Start Menu and Desktop shortcuts
; show the app icon reliably even if Windows' shortcut-icon cache is stale.
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\app_icon.ico"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\app_icon.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
