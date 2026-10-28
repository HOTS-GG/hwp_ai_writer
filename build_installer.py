"""
한큐(HanQ) 설치 파일 만들기 — 윈도우에서는 설치 exe, 맥에서는 dmg
실행: python build_installer.py           (프로그램을 새로 빌드한 뒤 설치 파일 생성)
      python build_installer.py --no-build (이미 만든 dist 로 설치 파일만 생성)
결과: 윈도우  installer_output\\HanQ_Setup_<버전>.exe   (필요: NSIS 3 — winget install NSIS.NSIS)
      맥      installer_output/HanQ_<버전>_mac_<arm64|x86_64>.dmg
"""
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from hanq.config import APP_VERSION  # noqa: E402

INFO_TEXT = """한큐(HanQ) {ver}

학교 공문·계획서 양식에 AI가 내용을 채워 한글(HWPX) 문서를 만들어 주는 프로그램입니다.


■ 사용 전에 준비할 것

1. AI 연결 (둘 중 하나)
   - API 키: Claude, GPT, Gemini, OpenRouter 중 하나 (설정 탭에 입력)
   - 구독 계정: Claude 데스크톱 앱(Claude Code) 또는 Codex 앱이 설치·로그인되어 있으면
     API 키 없이 바로 사용됩니다.

2. 한글 프로그램 (권장)
   - 한글이 있으면 미리보기를 한글이 직접 그려 실제 모양과 똑같이 보입니다.
   - 없어도 함께 설치되는 rhwp(오픈소스 HWP 엔진)로 문서 모양을 보여 주고,
     HWP 파일도 HWPX로 바꿔 씁니다.

3. 한글 '접근 허용' 창
   - 한글로 미리볼 때 '접근 허용' 창이 뜨면 [모두 허용]을 누르세요. (프로그램을 켤 때 한 번)
   - 설정 탭 → [한컴에서 받아 자동 등록]을 누르면 한컴 '보안 승인 모듈'을 받아 등록해
     이 창이 뜨지 않습니다. (직접 받기: https://developer.hancom.com/hwpautomation)


■ 개인정보 주의

작성 요청과 첨부한 참고 자료는 선택한 AI 회사(Anthropic, OpenAI, Google 등)의
서버로 전송됩니다. 학생 이름·연락처·성적 같은 개인정보는 넣지 말고,
학교 정보보안 지침을 따라 주세요.

AI가 쓴 내용(날짜·금액·인원 등)은 결재 전에 반드시 확인해 주세요.


■ 설치 위치

관리자 권한 없이 사용자 폴더(AppData\\Local\\Programs\\HanQ)에 설치됩니다.
새 버전을 설치하면 덮어쓰기로 업데이트되며, 설정과 API 키는 유지됩니다.
"""


def find_makensis() -> str | None:
    for p in (Path(os.environ.get("ProgramFiles(x86)", "")) / "NSIS" / "makensis.exe",
              Path(os.environ.get("ProgramFiles", "")) / "NSIS" / "makensis.exe"):
        if p.exists():
            return str(p)
    return shutil.which("makensis")


MAC_INFO_TEXT = """한큐(HanQ) {ver} — 맥에서 처음 실행하기

1. HanQ 아이콘을 옆의 Applications(응용 프로그램) 폴더로 끌어다 놓으세요.

2. 처음 열 때 "확인되지 않은 개발자" / "악성 코드가 없음을 확인할 수 없음" 경고가 뜨면
   - 시스템 설정 → 개인정보 보호 및 보안 → 아래쪽 '그래도 열기'를 누르거나
   - 터미널에서 한 번 실행:  xattr -cr /Applications/HanQ.app
   (Apple 개발자 인증서로 서명하지 않은 앱이라 뜨는 경고입니다.)


■ 맥에서 달라지는 점

- 문서 미리보기는 HWPX 안에 들어 있는 첫 쪽 이미지만 보입니다.
  (쪽 전체 미리보기·HWP→HWPX 변환은 윈도우용 한글의 자동화 기능이 필요합니다.)
- [한글로 열기]는 맥용 한컴오피스 한글(또는 한글 뷰어)로 문서를 엽니다.
- 기존 .hwp 양식은 맥용 한글에서 HWPX로 저장한 뒤 추가해 주세요.
- 설정·API 키·내 양식은 ~/Library/Application Support/HWP_AI_Writer 에 저장됩니다.


■ API 키 없이 쓰기 (구독 계정)

- Claude Code: 터미널에서  curl -fsSL https://claude.ai/install.sh | bash  후  claude  로그인
- Codex:       터미널에서  brew install codex  후  codex  로그인


■ 개인정보 주의

작성 요청과 첨부한 참고 자료는 선택한 AI 회사의 서버로 전송됩니다.
학생 이름·연락처·성적 같은 개인정보는 넣지 마세요.
"""


def build_dmg():
    """dist/HanQ.app + Applications 바로가기 + 안내문을 묶어 dmg를 만든다."""
    from build_exe import output_path
    app = output_path()
    if not app.exists():
        print(f"{app} 가 없습니다. 먼저 build_exe.py를 실행하세요.")
        sys.exit(1)
    stage = HERE / "build" / "dmg"
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True)
    # cp 대신 ditto: 번들 안의 심볼릭 링크·서명을 그대로 보존
    subprocess.run(["ditto", str(app), str(stage / app.name)], check=True)
    (stage / "Applications").symlink_to("/Applications")
    (stage / "처음 실행 안내.txt").write_text(MAC_INFO_TEXT.format(ver=APP_VERSION), encoding="utf-8")

    out_dir = HERE / "installer_output"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"HanQ_{APP_VERSION}_mac_{platform.machine()}.dmg"
    out.unlink(missing_ok=True)
    subprocess.run(["hdiutil", "create", "-volname", f"HanQ {APP_VERSION}", "-srcfolder", str(stage),
                    "-ov", "-format", "UDZO", str(out)], check=True)
    print(f"\n설치 파일: {out}  ({out.stat().st_size / 1024 / 1024:.0f}MB)")


def main():
    if sys.platform == "darwin":
        if "--no-build" not in sys.argv:
            if subprocess.run([sys.executable, str(HERE / "build_exe.py")], cwd=HERE).returncode != 0:
                sys.exit(1)
        build_dmg()
        return
    makensis = find_makensis()
    if not makensis:
        print("NSIS가 없습니다. 설치: winget install NSIS.NSIS")
        sys.exit(1)
    if "--no-build" not in sys.argv:
        if subprocess.run([sys.executable, str(HERE / "build_exe.py")], cwd=HERE).returncode != 0:
            sys.exit(1)
    if not (HERE / "dist" / "HanQ" / "HanQ.exe").exists():
        print("dist\\HanQ\\HanQ.exe 가 없습니다. 먼저 build_exe.py를 실행하세요.")
        sys.exit(1)
    # NSIS(Unicode)는 BOM이 있는 UTF-8 안내 파일을 한글로 제대로 읽는다
    (HERE / "installer" / "안내.txt").write_text(INFO_TEXT.format(ver=APP_VERSION), encoding="utf-8-sig")
    (HERE / "installer_output").mkdir(exist_ok=True)
    nsi = HERE / "installer" / "HanQ.nsi"
    r = subprocess.run([makensis, "-V2", f"-DVERSION={APP_VERSION}", str(nsi)], cwd=nsi.parent)
    if r.returncode != 0:
        sys.exit(r.returncode)
    out = HERE / "installer_output" / f"HanQ_Setup_{APP_VERSION}.exe"
    print(f"\n설치 파일: {out}  ({out.stat().st_size / 1024 / 1024:.0f}MB)")


if __name__ == "__main__":
    main()
