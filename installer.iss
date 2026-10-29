; Inno Setup script for Anon Brain (build_exe.bat compiles this for you)
; Installs for the current user only, so no admin prompt is needed.

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{8C1E2A54-6B1D-4C8E-9F7A-AB12CD34EF56}
AppName=Anon Brain
AppVersion={#AppVersion}
AppVerName=Anon Brain {#AppVersion}
AppPublisher=Anon Brain
DefaultDirName={localappdata}\Programs\Anon Brain
DefaultGroupName=Anon Brain
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=dist
OutputBaseFilename=Anon-Brain-Setup-{#AppVersion}
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\Anon Brain.exe
UninstallDisplayName=Anon Brain
Compression=lzma2/normal
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=force
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Put a shortcut on the desktop"; GroupDescription: "Shortcuts:"

[InstallDelete]
; clear out the previous version's files when updating (your settings are kept)
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "dist\Anon Brain\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Anon Brain"; Filename: "{app}\Anon Brain.exe"
Name: "{autodesktop}\Anon Brain"; Filename: "{app}\Anon Brain.exe"; Tasks: desktopicon

[Registry]
; remove "Start with Windows" when uninstalling (it's only added if you turn it on in the app)
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "Anon Brain"; Flags: uninsdeletevalue dontcreatekey

[Run]
Filename: "{app}\Anon Brain.exe"; Description: "Open Anon Brain"; Flags: nowait postinstall skipifsilent
; updating from inside the app runs this setup silently: reopen the app when it's done
Filename: "{app}\Anon Brain.exe"; Flags: nowait skipifnotsilent

[Messages]
FinishedLabel=Anon Brain is installed. Your settings, history and voices live in %APPDATA%\AnonBrain and are kept if you uninstall or update.
