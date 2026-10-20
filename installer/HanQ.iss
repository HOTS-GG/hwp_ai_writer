; 한큐(HanQ) 설치 프로그램 — Inno Setup 6
; 빌드: python build_installer.py  (먼저 build_exe.py로 dist\HanQ 를 만든다)

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#define AppName "한큐 HanQ"
#define AppExe "HanQ.exe"

[Setup]
; 업데이트 때 같은 프로그램으로 인식하는 고유 번호 (바꾸지 말 것)
AppId={{6E3B1C2A-8F4D-4C7B-9A51-2D7E0B9C4F11}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=HanQ
VersionInfoVersion={#AppVersion}
; 학교 PC는 관리자 권한이 없는 경우가 많아 사용자 폴더에 설치
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={localappdata}\Programs\HanQ
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\installer_output
OutputBaseFilename=HanQ_Setup_{#AppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
InfoBeforeFile=안내.txt
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Tasks]
Name: "desktopicon"; Description: "바탕화면에 바로가기 만들기"; GroupDescription: "바로가기:"

[Files]
Source: "..\dist\HanQ\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "한큐 실행하기"; Flags: nowait postinstall skipifsilent

; 제거해도 설정·API 키·내 양식(AppData\Roaming\HWP_AI_Writer)은 남겨 둔다 — 다시 설치하면 그대로 쓰도록
