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
    """릴리스 본문에서 '바뀐 점'만 남긴다 (내려받기 표·맥 안내·공동 작성자 줄은 앱 안에서 필요 없음)."""
    text = re.split(r"^##\s*내려받기", body.replace("\r\n", "\n"), flags=re.M)[0]
    lines = [ln for ln in text.splitlines()
             if not re.match(r"^\s*(##\s*바뀐 점\s*$|Co-Authored-By:)", ln, re.I)]
    return "\n".join(lines).strip()[:1500]


def download(rel: Release, on_progress=None, stop=None) -> Path:
    """설치 파일을 받아 크기·SHA-256을 확인한 뒤 경로를 돌려준다."""
    if not rel.asset_url:
        raise UpdateError("이 컴퓨터용 설치 파일이 릴리스에 없습니다.")
    dest_dir = CACHE_DIR / "update"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / rel.asset_name
    part = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(rel.asset_url, headers={"User-Agent": USER_AGENT})
    h = hashlib.sha256()
    done = 0
    try:
        with urllib.request.urlopen(req, timeout=30) as r, open(part, "wb") as f:
            total = int(r.headers.get("Content-Length") or rel.asset_size or 0)
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
    except UpdateError:
        part.unlink(missing_ok=True)
        raise
    except Exception as e:
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


def launch_installer(setup: Path) -> None:
    """윈도우: 한큐가 닫힌 뒤 설치 파일을 조용히 실행하고 새 한큐를 띄우는 배치를 따로 돌린다.
    맥: dmg를 열어 준다(Applications로 끌어다 놓기)."""
    if IS_MAC:
        subprocess.Popen(["open", str(setup)])
        return
    if not IS_WIN:
        raise UpdateError("이 운영체제에서는 자동 설치를 지원하지 않습니다.")
    target = install_dir()
    exe = target / "HanQ.exe"
    bat = Path(tempfile.gettempdir()) / "hanq_update.cmd"
    # NSIS의 /D=는 맨 끝에 따옴표 없이 써야 한다 (공백이 있어도 됨)
    bat.write_text(
        "@echo off\r\n"
        "chcp 65001 >nul\r\n"
        "timeout /t 2 /nobreak >nul\r\n"
        f"start \"\" /wait \"{setup}\" /S /D={target}\r\n"
        f"if exist \"{exe}\" start \"\" \"{exe}\"\r\n"
        "del \"%~f0\"\r\n",
        encoding="utf-8")
    flags = (getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
             | getattr(subprocess, "CREATE_NO_WINDOW", 0))
    subprocess.Popen(["cmd", "/c", str(bat)], creationflags=flags, close_fds=True,
                     cwd=os.environ.get("TEMP") or None)
