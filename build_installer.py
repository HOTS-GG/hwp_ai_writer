"""
한큐(HanQ) 설치 파일 만들기
실행: python build_installer.py           (exe를 새로 빌드한 뒤 설치 파일 생성)
      python build_installer.py --no-build (이미 만든 dist\\HanQ 로 설치 파일만 생성)
결과: installer_output\\HanQ_Setup_<버전>.exe
필요: Inno Setup 6 (winget install JRSoftware.InnoSetup)
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from settings import APP_VERSION  # noqa: E402

INFO_TEXT = """한큐(HanQ) {ver}

학교 공문·계획서 양식에 AI가 내용을 채워 한글(HWPX) 문서를 만들어 주는 프로그램입니다.


■ 사용 전에 준비할 것

1. AI 연결 (둘 중 하나)
   - API 키: Claude, GPT, Gemini, OpenRouter 중 하나 (설정 탭에 입력)
   - 구독 계정: Claude 데스크톱 앱(Claude Code) 또는 Codex 앱이 설치·로그인되어 있으면
     API 키 없이 바로 사용됩니다.

2. 한글 프로그램 (권장)
   - 문서 미리보기와 HWP 파일 변환에 사용합니다.
   - 없어도 문서는 만들어지며, 미리보기는 첫 쪽만 보입니다.

3. '접근 허용' 경고 없애기 (선택)
   - 한컴 디벨로퍼 사이트의 '보안 승인 모듈' DLL을 받아
     설정 탭 → [DLL 선택]으로 등록하면 경고창이 뜨지 않습니다.


■ 개인정보 주의

작성 요청과 첨부한 참고 자료는 선택한 AI 회사(Anthropic, OpenAI, Google 등)의
서버로 전송됩니다. 학생 이름·연락처·성적 같은 개인정보는 넣지 말고,
학교 정보보안 지침을 따라 주세요.

AI가 쓴 내용(날짜·금액·인원 등)은 결재 전에 반드시 확인해 주세요.


■ 설치 위치

관리자 권한 없이 사용자 폴더(AppData\\Local\\Programs\\HanQ)에 설치됩니다.
새 버전을 설치하면 덮어쓰기로 업데이트되며, 설정과 API 키는 유지됩니다.
"""


def find_iscc() -> str | None:
    for p in (Path(os.environ.get("ProgramFiles(x86)", "")) / "Inno Setup 6" / "ISCC.exe",
              Path(os.environ.get("ProgramFiles", "")) / "Inno Setup 6" / "ISCC.exe",
              Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe"):
        if p.exists():
            return str(p)
    return shutil.which("ISCC")


def main():
    iscc = find_iscc()
    if not iscc:
        print("Inno Setup 6이 없습니다. 설치: winget install JRSoftware.InnoSetup")
        sys.exit(1)
    if "--no-build" not in sys.argv:
        if subprocess.run([sys.executable, str(HERE / "build_exe.py")], cwd=HERE).returncode != 0:
            sys.exit(1)
    if not (HERE / "dist" / "HanQ" / "HanQ.exe").exists():
        print("dist\\HanQ\\HanQ.exe 가 없습니다. 먼저 build_exe.py를 실행하세요.")
        sys.exit(1)
    # Inno Setup은 BOM이 있는 UTF-8 안내 파일을 한글로 제대로 읽는다
    (HERE / "installer" / "안내.txt").write_text(INFO_TEXT.format(ver=APP_VERSION), encoding="utf-8-sig")
    iss = HERE / "installer" / "HanQ.iss"
    r = subprocess.run([iscc, f"/DAppVersion={APP_VERSION}", str(iss)], cwd=iss.parent)
    if r.returncode != 0:
        sys.exit(r.returncode)
    out = HERE / "installer_output" / f"HanQ_Setup_{APP_VERSION}.exe"
    print(f"\n설치 파일: {out}  ({out.stat().st_size / 1024 / 1024:.0f}MB)")


if __name__ == "__main__":
    main()
