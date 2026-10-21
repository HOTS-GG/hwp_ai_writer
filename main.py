"""
한큐(HanQ) - 진입점
실행: python main.py
"""
import os
import sys

# working directory를 스크립트 위치로 고정
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def main():
    # .env 파일에서 API 키 로드 (있으면)
    env_file = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_file):
        with open(env_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip())

    # 작업 표시줄에 python 아이콘 대신 한큐 아이콘이 나오도록 앱 ID 지정
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("HanQ.DocumentWriter")
    except Exception:
        pass

    from hanq.ui.app import App

    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
