"""
한큐(HanQ) → exe 빌드
실행: python build_exe.py
결과: dist\\HanQ\\HanQ.exe (폴더째 배포)
"""
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
APP_NAME = "HanQ"


def main():
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"], check=True)

    dist, build = HERE / "dist", HERE / "build"
    shutil.rmtree(dist, ignore_errors=True)
    shutil.rmtree(build, ignore_errors=True)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        f"--name={APP_NAME}", "--onedir", "--windowed", "--noconfirm", "--clean",
        f"--distpath={dist}", f"--workpath={build}", f"--specpath={build}",
        "--add-data", f"{HERE / 'forms'};forms",
        "--add-data", f"{HERE / 'assets' / 'icon.ico'};assets",
        f"--icon={HERE / 'assets' / 'icon.ico'}",
        "--hidden-import", "win32com.client",
        "--hidden-import", "pythoncom",
        "--hidden-import", "PIL.ImageTk",
        # 예전 RAG 버전의 무거운 라이브러리가 끌려 들어가지 않게 제외
        "--exclude-module", "torch",
        "--exclude-module", "sentence_transformers",
        "--exclude-module", "transformers",
        "--exclude-module", "chromadb",
        "--exclude-module", "onnxruntime",
        "--exclude-module", "matplotlib",
        "--exclude-module", "pandas",
        str(HERE / "main.py"),
    ]
    print("빌드 시작…")
    if subprocess.run(cmd, cwd=HERE).returncode != 0:
        print("빌드 실패")
        sys.exit(1)
    print(f"\n빌드 성공: {dist / APP_NAME / (APP_NAME + '.exe')}")


if __name__ == "__main__":
    main()
