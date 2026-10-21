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

MODULE_NAME = "FilePathCheckerModule"
REG_PATH = r"Software\HNC\HwpAutomation\Modules"
SECURITY_DIR = APP_DIR / "security"


def find_dll() -> Path | None:
    for d in (SECURITY_DIR, resource_dir() / "security"):
        if d.exists():
            for p in sorted(d.glob("*.dll")):
                return p
    return None


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
