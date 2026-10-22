; 한큐(HanQ) 설치 프로그램 — NSIS 3 (Unicode)
; 빌드: python build_installer.py  (먼저 build_exe.py로 dist\HanQ 를 만든다)
;
; Inno Setup은 설치 화면 프로그램(.tmp)을 임시 폴더에 풀어 한 번 더 실행하는데, 학교·가정 PC의 백신(V3)이
; 웹에서 받은 설치 파일의 이 두 번째 실행을 막는 일이 있어(ShellExecuteEx 코드 5) 한 단계로 동작하는 NSIS로 바꿨다.

Unicode true
!include "MUI2.nsh"

!ifndef VERSION
  !define VERSION "1.0.0"
!endif
!define APPNAME "한큐 HanQ"
!define APPEXE "HanQ.exe"
!define UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\HanQ"

Name "${APPNAME}"
OutFile "..\installer_output\HanQ_Setup_${VERSION}.exe"
; 학교 PC는 관리자 권한이 없는 경우가 많아 사용자 폴더에 설치 (예전 Inno 설치와 같은 위치라 덮어쓰기 업데이트)
InstallDir "$LOCALAPPDATA\Programs\HanQ"
RequestExecutionLevel user
SetCompressor /SOLID lzma
BrandingText "한큐 HanQ ${VERSION}"

VIProductVersion "${VERSION}.0"
VIAddVersionKey "ProductName" "${APPNAME}"
VIAddVersionKey "FileDescription" "${APPNAME} 설치"
VIAddVersionKey "FileVersion" "${VERSION}"
VIAddVersionKey "ProductVersion" "${VERSION}"
VIAddVersionKey "CompanyName" "HanQ"
VIAddVersionKey "LegalCopyright" "HanQ"

!define MUI_ICON "..\assets\icon.ico"
!define MUI_UNICON "..\assets\icon.ico"
!define MUI_ABORTWARNING

!define MUI_PAGE_HEADER_TEXT "설치 안내"
!define MUI_PAGE_HEADER_SUBTEXT "설치하기 전에 읽어 주세요."
!define MUI_LICENSEPAGE_TEXT_TOP "설치하기 전에 읽어 주세요."
!define MUI_LICENSEPAGE_BUTTON "다음 >"
!insertmacro MUI_PAGE_LICENSE "안내.txt"
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_RUN "$INSTDIR\${APPEXE}"
!define MUI_FINISHPAGE_RUN_TEXT "한큐 실행하기"
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "Korean"

Section "한큐 (필수)" SecMain
  SectionIn RO
  ; 실행 중인 한큐가 있으면 파일을 덮어쓸 수 없으므로 먼저 닫는다
  nsExec::Exec 'taskkill /IM ${APPEXE} /F'
  SetOutPath "$INSTDIR"
  File /r "..\dist\HanQ\*"
  ; 예전 Inno Setup 설치(1.1.0까지)의 제거 정보·제거 프로그램 정리
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\{6E3B1C2A-8F4D-4C7B-9A51-2D7E0B9C4F11}_is1"
  Delete "$INSTDIR\unins000.exe"
  Delete "$INSTDIR\unins000.dat"
  Delete "$SMPROGRAMS\한큐 HanQ\한큐 HanQ.lnk"
  WriteUninstaller "$INSTDIR\uninstall.exe"
  CreateShortcut "$SMPROGRAMS\${APPNAME}.lnk" "$INSTDIR\${APPEXE}"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayName" "${APPNAME}"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNINST_KEY}" "Publisher" "HanQ"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayIcon" "$INSTDIR\${APPEXE}"
  WriteRegStr HKCU "${UNINST_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINST_KEY}" "UninstallString" '"$INSTDIR\uninstall.exe"'
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoRepair" 1
SectionEnd

Section "바탕화면에 바로가기 만들기" SecDesktop
  CreateShortcut "$DESKTOP\${APPNAME}.lnk" "$INSTDIR\${APPEXE}"
SectionEnd

; 제거해도 설정·API 키·내 양식(AppData\Roaming\HWP_AI_Writer)은 남겨 둔다 — 다시 설치하면 그대로 쓰도록
Section "Uninstall"
  nsExec::Exec 'taskkill /IM ${APPEXE} /F'
  Delete "$SMPROGRAMS\${APPNAME}.lnk"
  Delete "$DESKTOP\${APPNAME}.lnk"
  RMDir /r "$INSTDIR"
  DeleteRegKey HKCU "${UNINST_KEY}"
SectionEnd
