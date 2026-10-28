"""Claude Code / Codex 설치·로그인 자동화 (UI를 모름).

명령 프롬프트를 몰라도 되도록 한큐가 공식 설치 명령을 대신 실행하고, 로그인 창을 띄운 뒤
로그인이 끝났는지 스스로 확인한다.
"""
import json
import os
import shutil
import subprocess
import time

from ..system import IS_MAC, IS_WIN, cli_env
from .providers import find_cli

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
NEW_CONSOLE = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)


class SetupError(Exception):
    pass


# 사용자가 직접 하고 싶을 때 복사해 갈 명령 (화면에 그대로 보여 준다)
if IS_MAC:
    COPY_COMMANDS = {
        "claude_code": "curl -fsSL https://claude.ai/install.sh | bash\nclaude auth login",
        "codex": "brew install codex\ncodex login",
    }
else:
    COPY_COMMANDS = {
        "claude_code": 'powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://claude.ai/install.ps1 | iex"\n'
                       "claude auth login",
        "codex": "npm install -g @openai/codex\ncodex login",
    }


def _find_npm() -> str | None:
    found = shutil.which("npm", path=cli_env()["PATH"])
    if found:
        return found
    if IS_WIN:
        for base in (os.environ.get("ProgramFiles", ""), os.environ.get("ProgramFiles(x86)", ""),
                     os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")):
            p = os.path.join(base, "nodejs", "npm.cmd")
            if base and os.path.exists(p):
                return p
    return None


def install_steps(provider: str) -> list[tuple[str, list[str]]]:
    """(설명, 명령) 목록. 명령은 순서대로 실행한다."""
    if provider == "claude_code":
        if IS_WIN:
            return [("Claude Code 설치 (공식 설치 스크립트)",
                     ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                      "irm https://claude.ai/install.ps1 | iex"])]
        return [("Claude Code 설치 (공식 설치 스크립트)",
                 ["/bin/bash", "-c", "curl -fsSL https://claude.ai/install.sh | bash"])]
    steps = []
    if IS_MAC and shutil.which("brew", path=cli_env()["PATH"]):
        return [("Codex 설치 (Homebrew)", ["brew", "install", "codex"])]
    npm = _find_npm()
    if npm is None:
        if not IS_WIN:
            raise SetupError("Codex를 설치하려면 Node.js가 필요합니다. https://nodejs.org 에서 설치한 뒤 다시 눌러 주세요.")
        steps.append(("Node.js 설치 (Codex에 필요, 권한 확인 창이 뜨면 '예')",
                      ["winget", "install", "-e", "--id", "OpenJS.NodeJS.LTS", "--silent",
                       "--accept-source-agreements", "--accept-package-agreements"]))
        npm = "npm"   # Node 설치 뒤에 다시 찾는다
    steps.append(("Codex 설치 (npm)", [npm, "install", "-g", "@openai/codex"]))
    return steps


def install(provider: str, on_line=None, stop=None) -> str:
    """설치하고 실행 파일 경로를 돌려준다. on_line(글)으로 진행 상황을 알린다."""
    say = on_line or (lambda s: None)
    for title, cmd in install_steps(provider):
        if stop is not None and stop.is_set():
            raise SetupError("취소했습니다.")
        if cmd[0] == "npm":
            found = _find_npm()
            if not found:
                raise SetupError("Node.js를 설치했지만 npm을 찾지 못했습니다. 한큐를 다시 켠 뒤 다시 눌러 주세요.")
            cmd = [found, *cmd[1:]]
        say(f"▶ {title}")
        _run(cmd, say, stop)
    exe = find_cli(provider)
    if not exe:
        raise SetupError("설치는 끝났지만 실행 파일을 찾지 못했습니다. 한큐를 다시 켠 뒤 [한 번에 설정]을 다시 눌러 주세요.")
    say("✓ 설치 완료")
    return exe


def _run(cmd: list[str], say, stop, timeout: int = 900):
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                env=cli_env(), creationflags=NO_WINDOW)
    except OSError as e:
        raise SetupError(f"실행할 수 없습니다: {cmd[0]}\n{e}")
    start = time.time()
    last = ""
    for raw in iter(proc.stdout.readline, b""):
        line = raw.decode("utf-8", errors="replace").strip()
        if line:
            last = line
            say("  " + line[:150])
        if stop is not None and stop.is_set():
            proc.kill()
            raise SetupError("취소했습니다.")
        if time.time() - start > timeout:
            proc.kill()
            raise SetupError("설치가 너무 오래 걸려 멈췄습니다. 인터넷 연결을 확인해 주세요.")
    if proc.wait() != 0:
        raise SetupError(f"설치 중 오류가 났습니다 (코드 {proc.returncode}).\n{last[:300]}")


def login_status(provider: str, exe: str) -> tuple[bool, str]:
    """(로그인 여부, 설명). 확인할 수 없으면 (False, 이유)."""
    if not exe:
        return False, "설치되지 않음"
    cmd = [exe, "auth", "status", "--json"] if provider == "claude_code" else [exe, "login", "status"]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=30, env=cli_env(exe), creationflags=NO_WINDOW,
                           stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as e:
        return False, f"확인 실패: {e}"
    out = (r.stdout or b"").decode("utf-8", errors="replace")
    err = (r.stderr or b"").decode("utf-8", errors="replace")
    if provider == "claude_code":
        try:
            info = json.loads(out[out.find("{"):out.rfind("}") + 1])
        except ValueError:
            return False, "로그인 필요"
        if not info.get("loggedIn"):
            return False, "로그인 필요"
        plan = info.get("subscriptionType") or info.get("authMethod") or ""
        return True, f"로그인됨 ({plan} 구독)" if plan else "로그인됨"
    text = (out + err).strip().lower()
    # "Not logged in"에도 'logged in'이 들어 있으므로 부정형을 먼저 거른다
    if r.returncode == 0 and "logged in" in text and "not logged in" not in text:
        return True, "로그인됨 (ChatGPT)" if "chatgpt" in text else "로그인됨"
    return False, "로그인 필요"


def start_login(provider: str, exe: str):
    """로그인 창(콘솔)을 띄운다. 브라우저에서 로그인을 마치면 창은 저절로 닫히거나 닫아도 된다."""
    args = [exe, "auth", "login"] if provider == "claude_code" else [exe, "login"]
    if IS_WIN:
        return subprocess.Popen(args, creationflags=NEW_CONSOLE, env=cli_env(exe))
    if IS_MAC:
        cmd = " ".join(f"'{a}'" for a in args)
        script = f'tell application "Terminal" to do script "{cmd}"\ntell application "Terminal" to activate'
        return subprocess.Popen(["osascript", "-e", script])
    return subprocess.Popen(args, env=cli_env(exe))


def wait_login(provider: str, exe: str, proc=None, stop=None, timeout: int = 600) -> bool:
    """로그인이 끝날 때까지 몇 초마다 확인한다. 로그인 창을 닫았는데도 안 됐으면 False."""
    start = time.time()
    closed_at = None
    while time.time() - start < timeout:
        if stop is not None and stop.is_set():
            return False
        ok, _ = login_status(provider, exe)
        if ok:
            return True
        if proc is not None and IS_WIN and proc.poll() is not None:
            # 창이 닫힌 직후 로그인 정보가 저장될 수 있어 몇 번 더 확인한다
            closed_at = closed_at or time.time()
            if time.time() - closed_at > 8:
                return False
        time.sleep(3)
    return False
