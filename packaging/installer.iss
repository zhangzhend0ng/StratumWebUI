; Stratum WebUI — Inno Setup script.
; Build (after build.ps1 has produced dist\StratumWebUI):
;     ISCC packaging\installer.iss
;
; MyAppVersion is the WebUI's own version, NOT the Stratum SDK engine version
; (that one ships in VERSION.txt next to bin\stratum.exe and is reported by
; /api/status).

#define MyAppName "Stratum WebUI"
; single source of truth: server.py's UI_VERSION, injected by build.ps1 via
; /DMyAppVersion=<x.y.z> (iter 61 — the hardcoded 0.1.0 drifted from the
; app's self-reported ui_version). The fallback keeps manual ISCC runs
; working.
#ifndef MyAppVersion
#define MyAppVersion "0.0.0-dev"
#endif
#define MyAppPublisher "Stratum"
#define MyAppExeName "StratumWebUI.exe"

[Setup]
AppId={{26052C13-2B80-4718-AFA7-A6FC70B0E522}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\Stratum WebUI
DefaultGroupName=Stratum WebUI
DisableProgramGroupPage=yes
OutputDir=..\dist\installer
OutputBaseFilename=StratumWebUI-Setup-{#MyAppVersion}
SetupIconFile=stratum-webui.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Admin install (Program Files) by default, but allow per-user install
; ({LOCALAPPDATA}\Programs) via the wizard dialog or setup.exe /CURRENTUSER.
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog commandline
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
; ChineseSimplified.isl is vendored here because Inno Setup installs don't
; reliably include it (winget's silent install ships no language files at all).
Name: "chinesesimplified"; MessagesFile: "ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; license surface listed explicitly (not just via the wildcard below): if a
; file goes missing, ISCC fails the build instead of shipping an unlicensed
; installer. LICENSE-Stratum-Engine.txt is the engine's MIT, renamed because
; the WebUI's own LICENSE already claims that filename.
Source: "..\dist\StratumWebUI\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\StratumWebUI\LICENSE-Stratum-Engine.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\StratumWebUI\THIRD-PARTY-NOTICES"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\StratumWebUI\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\Stratum WebUI"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Stratum WebUI"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
