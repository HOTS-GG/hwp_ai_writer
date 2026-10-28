"""
한큐(HanQ) → 실행 파일 빌드 (윈도우 exe / 맥 app)
실행: python build_exe.py
결과: 윈도우  dist\\HanQ\\HanQ.exe (폴더째 배포)
      맥      dist/HanQ.app
PyInstaller는 교차 빌드가 안 되므로 exe는 윈도우에서, app은 맥에서 빌드한다.
"""
import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from hanq.config import APP_VERSION  # noqa: E402

APP_NAME = "HanQ"
IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
BUNDLE_ID = "kr.hanq.writer"


def output_path() -> Path:
    dist = HERE / "dist"
    return dist / f"{APP_NAME}.app" if IS_MAC else dist / APP_NAME / f"{APP_NAME}.exe"


def main():
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"], check=True)

    dist, build = HERE / "dist", HERE / "build"
    shutil.rmtree(dist, ignore_errors=True)
    shutil.rmtree(build, ignore_errors=True)

    # rhwp(한글 없이 미리보기·HWP 변환, MIT) 실행 파일을 받아 함께 묶는다. 실패해도 빌드는 계속 (간이 미리보기로 동작)
    rhwp_ok = subprocess.run([sys.executable, str(HERE / "tools" / "fetch_rhwp.py")], cwd=HERE).returncode == 0
    if not rhwp_ok:
        print("경고: rhwp를 받지 못해 빼고 빌드합니다.")

    # --add-data의 구분자는 윈도우 ';', 맥 ':'
    sep = os.pathsep
    # 맥은 png를 주면 PyInstaller가 Pillow로 icns를 만든다
    icon = HERE / "assets" / ("icon.ico" if IS_WIN else "icon.png")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        f"--name={APP_NAME}", "--onedir", "--windowed", "--noconfirm", "--clean",
        f"--distpath={dist}", f"--workpath={build}", f"--specpath={build}",
        "--add-data", f"{HERE / 'forms'}{sep}forms",
        "--add-data", f"{HERE / 'assets' / 'icon.ico'}{sep}assets",
        "--add-data", f"{HERE / 'THIRD_PARTY_NOTICES.md'}{sep}.",
        *(["--add-data", f"{HERE / 'tools' / 'rhwp'}{sep}tools/rhwp"] if rhwp_ok else []),
        # 한글 보안 승인 모듈(assets/security/*.dll)이 있으면 함께 넣어, 설치 후 '접근 허용' 창 없이 쓰게 한다
        *(["--add-data", f"{HERE / 'assets' / 'security'}{sep}security"]
          if IS_WIN and list((HERE / "assets" / "security").glob("*.dll")) else []),
        f"--icon={icon}",
        "--hidden-import", "PIL.ImageTk",
        # 예전 RAG 버전의 무거운 라이브러리가 끌려 들어가지 않게 제외
        "--exclude-module", "torch",
        "--exclude-module", "sentence_transformers",
        "--exclude-module", "transformers",
        "--exclude-module", "chromadb",
        "--exclude-module", "onnxruntime",
        "--exclude-module", "matplotlib",
        "--exclude-module", "pandas",
    ]
    if IS_WIN:
        cmd += ["--hidden-import", "win32com.client", "--hidden-import", "pythoncom"]
    if IS_MAC:
        cmd += [f"--osx-bundle-identifier={BUNDLE_ID}"]
    cmd.append(str(HERE / "main.py"))

    print("빌드 시작…")
    if subprocess.run(cmd, cwd=HERE).returncode != 0:
        print("빌드 실패")
        sys.exit(1)
    if IS_MAC:
        _finish_mac_app(output_path())
    print(f"\n빌드 성공: {output_path()}")


def _finish_mac_app(app: Path):
    """Info.plist에 버전·한글 이름을 넣고, 바뀐 번들을 다시 서명(ad-hoc)한다."""
    plist = app / "Contents" / "Info.plist"
    with open(plist, "rb") as f:
        info = plistlib.load(f)
    info.update({
        "CFBundleDisplayName": "한큐",
        "CFBundleShortVersionString": APP_VERSION,
        "CFBundleVersion": APP_VERSION,
        "CFBundleDevelopmentRegion": "ko",
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "11.0",
    })
    with open(plist, "wb") as f:
        plistlib.dump(info, f)
    # Apple Silicon은 서명이 없는 실행 파일을 아예 실행하지 않는다 (개발자 인증서 없이 ad-hoc 서명)
    subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(app)], check=True)


if __name__ == "__main__":
    main()
