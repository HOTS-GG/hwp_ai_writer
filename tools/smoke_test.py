"""빌드한 프로그램을 띄워 몇 초 동안 죽지 않고 창이 떠 있는지 확인한다 (CI용).
실행: python tools/smoke_test.py <실행 파일> [기다릴 초]
"""
import subprocess
import sys
import time


def main():
    exe = sys.argv[1]
    wait = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    proc = subprocess.Popen([exe])
    time.sleep(wait)
    code = proc.poll()
    if code is not None:
        print(f"실패: {exe} 가 {wait}초 안에 종료됨 (코드 {code})")
        sys.exit(1)
    proc.kill()
    print(f"성공: {exe} 가 {wait}초 동안 실행됨")


if __name__ == "__main__":
    main()
