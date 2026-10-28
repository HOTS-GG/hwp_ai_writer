"""한글 자동화 보안 승인 모듈 등록.

한글은 외부 프로그램이 파일을 열고 저장할 때마다 '접근 허용' 경고를 띄운다.
한컴이 배포하는 보안 승인 모듈 DLL을 레지스트리
HKCU\\Software\\HNC\\HwpAutomation\\Modules 에 등록하고 RegisterModule로 불러오면 경고가 사라진다.
"""
import shutil
try:
    import winreg
except ImportError:  # 맥: 레지스트리도 한글 COM도 없다
    winreg = None
from pathlib import Path

from ..config import APP_DIR, resource_dir

# 한컴 공식 안내 페이지와, 그 페이지의 '보안모듈(Automation).zip' 내려받기 주소 (한컴 공식 GitHub 저장소)
OFFICIAL_PAGE = "https://developer.hancom.com/hwpautomation"
OFFICIAL_ZIP = ("https://github.com/hancom-io/devcenter-archive/raw/main/hwp-automation/"
                "%EB%B3%B4%EC%95%88%EB%AA%A8%EB%93%88(Automation).zip")

MODULE_NAME = "FilePathCheckerModule"
REG_PATH = r"Software\HNC\HwpAutomation\Modules"
SECURITY_DIR = APP_DIR / "security"


def find_dll() -> Path | None:
    for d in (SECURITY_DIR, resource_dir() / "security"):
        if d.exists():
            for p in sorted(d.glob("*.dll")):
                return p
    return None


SEARCH_DIRS = ("Desktop", "Downloads", "Documents", "바탕 화면", "다운로드", "문서")
DLL_GLOB = "FilePathChecker*.dll"
ZIP_HINTS = ("filepathchecker", "hwpautomation", "보안", "automation")


def search_candidates(max_depth: int = 3) -> list[Path]:
    """바탕화면·다운로드·문서에서 보안 모듈 DLL 또는 그것이 든 zip을 찾는다 (가까운 것·최근 것 먼저)."""
    home = Path.home()
    roots = [home / d for d in SEARCH_DIRS if (home / d).is_dir()]
    found: list[Path] = []
    for root in roots:
        stack = [(root, 0)]
        while stack:
            d, depth = stack.pop()
            try:
                entries = list(d.iterdir())
            except OSError:
                continue
            for e in entries:
                name = e.name.lower()
                if e.is_dir():
                    if depth < max_depth and not name.startswith((".", "$")) and name != "node_modules":
                        stack.append((e, depth + 1))
                elif e.match(DLL_GLOB):
                    found.append(e)
                elif name.endswith(".zip") and any(h in name for h in ZIP_HINTS):
                    found.append(e)
    return sorted(found, key=lambda p: (p.suffix.lower() != ".dll", -_mtime(p)))


def _mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


def _extract_from_zip(zip_path: Path) -> Path | None:
    import zipfile
    try:
        with zipfile.ZipFile(zip_path) as z:
            names = [n for n in z.namelist() if Path(n).name.lower().startswith("filepathchecker")
                     and n.lower().endswith(".dll")]
            if not names:
                return None
            SECURITY_DIR.mkdir(parents=True, exist_ok=True)
            dst = SECURITY_DIR / Path(names[0]).name
            dst.write_bytes(z.read(names[0]))
            return dst
    except (OSError, zipfile.BadZipFile):
        return None


def auto_install() -> Path | None:
    """아직 등록 전이면 흔한 위치에서 찾아 자동으로 등록한다. 등록한 DLL 경로(이미 등록돼 있으면 None)."""
    if winreg is None:
        return None
    reg = registered_path()
    if reg and Path(reg).exists():
        return None
    bundled = find_dll()
    if bundled:
        _write_registry(bundled)
        return bundled
    for cand in search_candidates():
        if cand.suffix.lower() == ".dll":
            try:
                return install(str(cand))
            except OSError:
                continue
        dll = _extract_from_zip(cand)
        if dll:
            _write_registry(dll)
            return dll
    return None


def download_and_install(timeout: int = 30) -> Path:
    """한컴 공식 주소에서 보안 모듈 zip을 받아 DLL을 꺼내 등록한다. 실패하면 OSError."""
    import urllib.request
    from ..config import CACHE_DIR
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    dest = CACHE_DIR / "hwp_security_module.zip"
    req = urllib.request.Request(OFFICIAL_ZIP, headers={"User-Agent": "HanQ"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            dest.write_bytes(r.read())
    except Exception as e:
        raise OSError(f"한컴 사이트에서 보안 모듈을 받지 못했습니다 (인터넷 연결 확인): {e}")
    dll = _extract_from_zip(dest)
    dest.unlink(missing_ok=True)
    if dll is None:
        raise OSError("받은 파일 안에서 보안 모듈 DLL을 찾지 못했습니다. [받는 곳 열기]로 직접 받아 주세요.")
    _write_registry(dll)
    return dll


def registered_path() -> str | None:
    if winreg is None:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH) as k:
            return winreg.QueryValueEx(k, MODULE_NAME)[0]
    except OSError:
        return None


def install(dll_path: str) -> Path:
    """선택한 DLL을 앱 폴더로 복사하고 레지스트리에 등록한다."""
    SECURITY_DIR.mkdir(parents=True, exist_ok=True)
    dst = SECURITY_DIR / Path(dll_path).name
    if Path(dll_path).resolve() != dst.resolve():
        for old in SECURITY_DIR.glob("*.dll"):
            old.unlink(missing_ok=True)
        shutil.copyfile(dll_path, dst)
    _write_registry(dst)
    return dst


def _write_registry(dll: Path):
    if winreg is None:
        raise OSError("보안 승인 모듈은 윈도우용 한글에서만 쓸 수 있습니다.")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REG_PATH) as k:
        winreg.SetValueEx(k, MODULE_NAME, 0, winreg.REG_SZ, str(dll))


def status() -> tuple[bool, str]:
    dll = find_dll()
    reg = registered_path()
    if dll and reg and Path(reg).exists():
        return True, f"설치됨: {Path(reg).name}"
    if reg and Path(reg).exists():
        return True, f"등록됨: {reg}"
    return False, "미설치 — 한글이 파일을 열 때마다 '접근 허용' 경고가 뜹니다"


def register(hwp) -> bool:
    """한글 COM 객체에 보안 모듈을 불러온다. 성공하면 True."""
    reg = registered_path()
    dll = find_dll()
    if dll and (not reg or not Path(reg).exists()):
        try:
            _write_registry(dll)
        except OSError:
            pass
    try:
        return bool(hwp.RegisterModule("FilePathCheckDLL", MODULE_NAME))
    except Exception:
        return False
