"""rhwp(https://github.com/edwardkim/rhwp, MIT) 공식 릴리스 실행 파일을 tools/rhwp/에 받는다.

빌드 때(build_exe.py, GitHub Actions) 쓰며, 배포처의 SHA256SUMS로 파일이 맞는지 확인한다.
실행: python tools/fetch_rhwp.py
"""
import hashlib
import io
import platform
import shutil
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from hanq.hwp.rhwp import RHWP_VERSION  # noqa: E402

DEST = HERE / "rhwp"
BASE = f"https://github.com/edwardkim/rhwp/releases/download/v{RHWP_VERSION}"


def asset_name() -> str:
    machine = platform.machine().lower()
    if sys.platform == "win32":
        return f"rhwp-v{RHWP_VERSION}-windows-x86_64.zip"
    arch = "aarch64" if machine in ("arm64", "aarch64") else "x86_64"
    osname = "macos" if sys.platform == "darwin" else "linux"
    return f"rhwp-v{RHWP_VERSION}-{osname}-{arch}.tar.gz"


def download(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as r:
        return r.read()


def main():
    name = asset_name()
    exe = DEST / ("rhwp.exe" if sys.platform == "win32" else "rhwp")
    version_file = DEST / "VERSION"
    if exe.exists() and version_file.exists() and version_file.read_text(encoding="utf-8").strip() == RHWP_VERSION:
        print(f"이미 있음: {exe}")
        return
    sums = download(f"{BASE}/SHA256SUMS.txt").decode("utf-8")
    want = next((line.split()[0] for line in sums.splitlines() if line.strip().endswith(name)), None)
    if not want:
        sys.exit(f"체크섬 목록에 {name}이(가) 없습니다.")
    data = download(f"{BASE}/{name}")
    got = hashlib.sha256(data).hexdigest()
    if got != want:
        sys.exit(f"체크섬이 다릅니다: {got} != {want}")
    shutil.rmtree(DEST, ignore_errors=True)
    DEST.mkdir(parents=True)
    if name.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            members = {Path(n).name: n for n in z.namelist() if not n.endswith("/")}
            for want_name in (exe.name, "LICENSE", "README.md"):
                if want_name in members:
                    (DEST / want_name).write_bytes(z.read(members[want_name]))
    else:
        with tarfile.open(fileobj=io.BytesIO(data)) as t:
            for m in t.getmembers():
                if m.isfile() and Path(m.name).name in (exe.name, "LICENSE", "README.md"):
                    (DEST / Path(m.name).name).write_bytes(t.extractfile(m).read())
        exe.chmod(0o755)
    (DEST / "VERSION").write_text(RHWP_VERSION, encoding="utf-8")
    print(f"받음: {exe} (v{RHWP_VERSION}, sha256 확인)")


if __name__ == "__main__":
    main()
