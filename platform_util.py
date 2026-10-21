"""윈도우·맥 차이를 한곳에 모은다.

한글 COM 자동화(미리보기, HWP→HWPX 변환, 보안 모듈)는 윈도우용 한글에만 있으므로
맥에서는 hwpx 안의 첫 쪽 미리보기 이미지로 대신하고, 문서는 기본 앱(맥용 한글 등)으로 연다.
"""
import os
import subprocess
import sys

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

# 맥 Tk는 포인트를 72dpi로 그려 같은 숫자면 글씨가 작게 보이므로 크기를 키운다
if IS_MAC:
    UI_FAMILY, EN_FAMILY, MONO_FAMILY, FONT_PLUS = "Apple SD Gothic Neo", "Helvetica Neue", "Menlo", 3
else:
    UI_FAMILY, EN_FAMILY, MONO_FAMILY, FONT_PLUS = "Malgun Gothic", "Segoe UI", "Consolas", 0

# Finder에서 띄운 맥 앱은 PATH가 /usr/bin:/bin 정도뿐이라 Homebrew·npm으로 깐 CLI를 못 찾는다
EXTRA_BIN_DIRS = ([os.path.expanduser("~/.local/bin"), os.path.expanduser("~/.claude/local"),
                   "/opt/homebrew/bin", "/usr/local/bin", os.path.expanduser("~/.npm-global/bin")]
                  if not IS_WIN else [])


def font(size: int, *style) -> tuple:
    return (UI_FAMILY, size + FONT_PLUS, *style)


def open_path(path) -> None:
    """파일이나 폴더를 기본 프로그램(한글, 탐색기/Finder)으로 연다."""
    path = str(path)
    if IS_WIN:
        os.startfile(path)
    elif IS_MAC:
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def wheel_units(e) -> int:
    """마우스 휠 이벤트를 스크롤 줄 수로. 윈도우는 한 칸에 120, 맥은 1 단위로 온다."""
    if IS_MAC:
        return -e.delta
    return int(-e.delta / 120) * 3


def zoom_modifier(e) -> bool:
    """Ctrl(맥은 Command도) + 휠이면 확대/축소."""
    return bool(e.state & (0x4 | (0x8 if IS_MAC else 0)))


def cli_env(exe: str = "") -> dict:
    """CLI 실행용 환경변수. 실행 파일 폴더도 PATH에 넣어 같은 곳의 node(nvm 등)를 찾게 한다."""
    env = dict(os.environ)
    dirs = ([os.path.dirname(exe)] if exe and not IS_WIN else []) + EXTRA_BIN_DIRS
    if dirs:
        env["PATH"] = os.pathsep.join([*dirs, env.get("PATH", "")])
    return env
