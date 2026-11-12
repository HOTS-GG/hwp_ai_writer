"""GitHub 릴리스로 새 버전 확인·내려받기·설치 (UI를 모름).

윈도우 설치본(exe로 실행 중)은 설치 파일을 받아 조용히(/S) 설치한 뒤 한큐를 다시 띄운다.
맥은 dmg를 받아 열어 주고, 소스로 실행 중이면 릴리스 페이지만 알려 준다.
"""
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .config import APP_VERSION, CACHE_DIR
from .system import IS_MAC, IS_WIN

REPO = "HOTS-GG/hwp_ai_writer"
LATEST_API = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
USER_AGENT = f"HanQ/{APP_VERSION}"


class UpdateError(Exception):
    pass


@dataclass
class Release:
    version: str
    notes: str
    page_url: str
    asset_name: str = ""
    asset_url: str = ""
    asset_size: int = 0
    sha256: str = ""


def parse_version(s: str) -> tuple:
    nums = re.findall(r"\d+", s or "")
    return tuple(int(n) for n in nums[:4]) or (0,)


def is_newer(latest: str, current: str = APP_VERSION) -> bool:
    return parse_version(latest) > parse_version(current)


def asset_name_for(version: str) -> str:
    if IS_MAC:
        arch = "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "x86_64"
        return f"HanQ_{version}_mac_{arch}.dmg"
    return f"HanQ_Setup_{version}.exe"


def is_installed_app() -> bool:
    """설치 파일로 깐 한큐(exe/app)로 실행 중인지. 소스(python main.py)면 False."""
    return bool(getattr(sys, "frozen", False))


def _get_json(url: str, timeout: int) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                               "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def latest_release(timeout: int = 10) -> Release:
    try:
        data = _get_json(LATEST_API, timeout)
    except Exception as e:
        raise UpdateError(f"새 버전을 확인하지 못했습니다 (인터넷 연결 확인): {e}")
    version = str(data.get("tag_name", "")).lstrip("vV")
    rel = Release(version=version, notes=_clean_notes(data.get("body") or ""),
                  page_url=data.get("html_url") or RELEASES_PAGE)
    want = asset_name_for(version)
    for a in data.get("assets", []):
        if a.get("name") == want:
            digest = str(a.get("digest") or "")
            rel.asset_name = want
            rel.asset_url = a.get("browser_download_url", "")
            rel.asset_size = int(a.get("size") or 0)
            rel.sha256 = digest.split(":", 1)[1].lower() if digest.startswith("sha256:") else ""
    return rel


def check(timeout: int = 10) -> Release | None:
    """지금보다 새 버전이 있으면 그 릴리스, 없으면 None."""
    rel = latest_release(timeout)
    return rel if rel.version and is_newer(rel.version) else None


def _clean_notes(body: str) -> str:
    """릴리스 본문의 '바뀐 점'에서 첫 줄(커밋 제목)만 남긴다 — 알림 창에는 한 줄 요약이면 충분하다."""
    text = re.split(r"^##\s*내려받기", body.replace("\r\n", "\n"), flags=re.M)[0]
    for ln in text.splitlines():
        ln = ln.strip()
        if ln and not re.match(r"^(##\s*바뀐 점$|Co-Authored-By:)", ln, re.I):
            return ln[:200]
    return ""


def download(rel: Release, on_progress=None, stop=None, tries: int = 4) -> Path:
    """설치 파일을 받아 크기·SHA-256을 확인한 뒤 경로를 돌려준다.
    받다가 끊기면 처음부터가 아니라 끊긴 곳부터 이어 받는다 (느린 학교망)."""
    if not rel.asset_url:
        raise UpdateError("이 컴퓨터용 설치 파일이 릴리스에 없습니다.")
    dest_dir = CACHE_DIR / "update"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / rel.asset_name
    part = dest.with_suffix(dest.suffix + ".part")
    h = hashlib.sha256()
    done = 0
    last_err = "연결이 중간에 끊겼습니다"
    try:
        with open(part, "wb") as f:
            for _ in range(max(tries, 1)):
                headers = {"User-Agent": USER_AGENT}
                if done:
                    headers["Range"] = f"bytes={done}-"
                try:
                    req = urllib.request.Request(rel.asset_url, headers=headers)
                    with urllib.request.urlopen(req, timeout=30) as r:
                        if done and getattr(r, "status", 200) != 206:
                            # 서버가 이어 받기를 받아 주지 않았다: 처음부터 다시
                            f.seek(0)
                            f.truncate()
                            h, done = hashlib.sha256(), 0
                        total = rel.asset_size or done + int(r.headers.get("Content-Length") or 0)
                        while True:
                            if stop is not None and stop.is_set():
                                raise UpdateError("내려받기를 취소했습니다.")
                            chunk = r.read(256 * 1024)
                            if not chunk:
                                break
                            f.write(chunk)
                            h.update(chunk)
                            done += len(chunk)
                            if on_progress:
                                on_progress(done, total)
                    if not rel.asset_size or done >= rel.asset_size:
                        break
                except UpdateError:
                    raise
                except Exception as e:   # 끊김·시간 초과: 받은 곳부터 다시 시도
                    last_err = e
            else:
                raise UpdateError(f"내려받기 실패: {last_err}")
    except UpdateError:
        part.unlink(missing_ok=True)
        raise
    except OSError as e:
        part.unlink(missing_ok=True)
        raise UpdateError(f"내려받기 실패: {e}")
    if rel.asset_size and done != rel.asset_size:
        part.unlink(missing_ok=True)
        raise UpdateError("받은 파일 크기가 맞지 않습니다. 다시 시도해 주세요.")
    if rel.sha256 and h.hexdigest() != rel.sha256:
        part.unlink(missing_ok=True)
        raise UpdateError("받은 파일이 손상되었습니다(지문 불일치). 다시 시도해 주세요.")
    part.replace(dest)
    return dest


def install_dir() -> Path:
    return Path(sys.executable).resolve().parent


UPDATE_LOG = Path(tempfile.gettempdir()) / "hanq_update.log"

# 배치 파일에는 영문만 쓰고 경로는 환경 변수로 넘긴다. 창 없이 도는 cmd는 배치 파일 속 한글 경로를 깨뜨려 읽어,
# 윈도우 사용자 이름이 한글인 컴퓨터에서는 설치가 시작되지도 않고 한큐만 꺼졌다.
# 한큐가 완전히 꺼질 때까지 기다린 뒤(최대 20초쯤) 설치하고, 조용한 설치 뒤에 한큐가 없으면 설치 창을 띄운다.
_UPDATE_BAT = (
    "@echo off",
    "set n=0",
    ":wait",
    "ping -n 2 127.0.0.1 >nul",
    # 실행 중인 exe는 쓰기로 열 수 없다 (빈 글을 덧붙여 보는 것이라 파일은 바뀌지 않음).
    # 창 없는 cmd에서는 '|'로 잇는 명령이 멈춰 버려서 tasklist | find 는 쓰지 않는다
    'if not exist "%HANQ_EXE%" goto run',
    '(type nul >> "%HANQ_EXE%") 2>nul && goto run',
    "set /a n+=1",
    "if %n% lss 20 goto wait",
    ":run",
    'echo start %date% %time% > "%HANQ_LOG%"',
    'start "" /wait "%HANQ_SETUP%" /S /D=%HANQ_DIR%',
    'echo installer exit %errorlevel% >> "%HANQ_LOG%"',
    'if exist "%HANQ_EXE%" goto ok',
    'echo failed: exe missing >> "%HANQ_LOG%"',
    'start "" "%HANQ_SETUP%"',
    "goto end",
    ":ok",
    'echo ok >> "%HANQ_LOG%"',
    'start "" "%HANQ_EXE%"',
    ":end",
    'del "%~f0"',
)


def launch_installer(setup: Path, target: Path | None = None) -> None:
    """윈도우: 한큐가 닫힌 뒤 설치 파일을 조용히 실행하고 새 한큐를 띄우는 배치를 따로 돌린다.
    맥: dmg를 열어 준다(Applications로 끌어다 놓기)."""
    if IS_MAC:
        subprocess.Popen(["open", str(setup)])
        return
    if not IS_WIN:
        raise UpdateError("이 운영체제에서는 자동 설치를 지원하지 않습니다.")
    target = target or install_dir()
    bat = Path(tempfile.gettempdir()) / "hanq_update.cmd"
    bat.write_bytes(("\r\n".join(_UPDATE_BAT) + "\r\n").encode("ascii"))
    UPDATE_LOG.unlink(missing_ok=True)
    # NSIS의 /D=는 맨 끝에 따옴표 없이 써야 한다 (공백이 있어도 됨)
    env = {**os.environ, "HANQ_SETUP": str(setup), "HANQ_DIR": str(target), "HANQ_EXE": str(target / "HanQ.exe"),
           "HANQ_LOG": str(UPDATE_LOG)}
    flags = (getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
             | getattr(subprocess, "CREATE_NO_WINDOW", 0))
    subprocess.Popen(["cmd", "/c", str(bat)], creationflags=flags, close_fds=True, env=env,
                     cwd=os.environ.get("TEMP") or None)


def read_update_log() -> str:
    """지난 자동 업데이트의 기록 (실패 안내용)."""
    try:
        return UPDATE_LOG.read_text(encoding="utf-8", errors="replace").strip()[:400]
    except OSError:
        return ""
