"""Claude / OpenAI / Gemini / OpenRouter 공통 호출 (HTTP 스트리밍)."""
import json

import requests


class LLMError(Exception):
    pass


def _sse_lines(resp):
    # 바이트 단위로 줄을 나눈 뒤 UTF-8로 디코딩한다. (서버가 charset을 안 주면
    # requests가 Latin-1로 풀어 한글이 깨지고, 깨진 문자가 줄바꿈으로 오인돼 내용이 잘림)
    for raw_bytes in resp.iter_lines():
        if not raw_bytes:
            continue
        raw = raw_bytes.decode("utf-8", errors="replace")
        if raw.startswith("data:"):
            data = raw[5:].strip()
            if data and data != "[DONE]":
                try:
                    yield json.loads(data)
                except ValueError:
                    continue


def _check(resp):
    if resp.status_code >= 400:
        try:
            body = resp.json()
            msg = body.get("error", body)
            if isinstance(msg, dict):
                msg = msg.get("message", msg)
        except ValueError:
            resp.encoding = "utf-8"
            msg = resp.text[:500]
        raise LLMError(f"[{resp.status_code}] {msg}")


CLI_PROVIDERS = ("claude_code", "codex")
CLI_NAMES = {"claude_code": "claude", "codex": "codex"}


def find_cli(provider: str) -> str | None:
    """Claude Code / Codex 실행 파일을 PATH와 흔한 설치 위치에서 찾는다."""
    import os
    import shutil
    from platform_util import IS_WIN, cli_env
    name = CLI_NAMES[provider]
    found = shutil.which(name, path=cli_env()["PATH"])
    if found:
        return found
    import glob
    if not IS_WIN:
        # nvm으로 깐 node의 전역 패키지 (가장 최근 것)
        hits = glob.glob(os.path.expanduser(f"~/.nvm/versions/node/*/bin/{name}"))
        return max(hits, key=os.path.getmtime) if hits else None
    home = os.path.expanduser("~")
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    # 데스크톱 앱에 포함된 실행 파일 (폴더에 버전이 들어가므로 가장 최근 것을 고름)
    bundled = {
        "claude_code": [os.path.join(local, "Claude-Data", "*", "claude-code", "*", "*", "claude.exe"),
                        os.path.join(local, "Claude-Data", "*", "claude-code", "*", "claude.exe")],
        "codex": [os.path.join(local, "OpenAI", "Codex", "bin", "*", "codex.exe")],
    }[provider]
    hits = [p for pat in bundled for p in glob.glob(pat)]
    if hits:
        return max(hits, key=os.path.getmtime)
    for p in (os.path.join(home, ".local", "bin", f"{name}.exe"),
              os.path.join(appdata, "npm", f"{name}.cmd"),
              os.path.join(local, "Programs", name, f"{name}.exe"),
              os.path.join(local, "Microsoft", "WinGet", "Links", f"{name}.exe")):
        if p and os.path.exists(p):
            return p
    return None


def _run_cli(cmd: list[str], stdin_text: str, timeout: int, on_progress, cwd: str):
    import subprocess
    import threading
    import time
    from platform_util import cli_env
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, cwd=cwd, creationflags=flags, env=cli_env(cmd[0]))
    except OSError as e:
        raise LLMError(f"실행할 수 없습니다: {cmd[0]}\n{e}")
    result = {}

    def talk():
        result["out"], result["err"] = proc.communicate(stdin_text.encode("utf-8"))
    t = threading.Thread(target=talk, daemon=True)
    t.start()
    start = time.time()
    while t.is_alive():
        t.join(1)
        elapsed = int(time.time() - start)
        if on_progress:
            on_progress(-elapsed)
        if elapsed > timeout:
            proc.kill()
            raise LLMError(f"응답 대기 시간({timeout}초)을 넘었습니다.")
    out = result.get("out", b"").decode("utf-8", errors="replace")
    err = result.get("err", b"").decode("utf-8", errors="replace")
    if proc.returncode != 0:
        hint = ""
        low = (out + err).lower()
        if "login" in low or "auth" in low or "credential" in low:
            hint = "\n\n로그인이 필요합니다. 명령 프롬프트(맥은 터미널)에서 한 번 실행해 로그인해 주세요."
        raise LLMError(f"{cmd[0]} 실행 오류 (코드 {proc.returncode})\n{(err or out).strip()[:600]}{hint}")
    return out


IMAGE_NOTE = ("첨부한 이미지는 지금 문서를 한글에서 연 실제 화면(1쪽부터 차례로)입니다. "
              "글자 목록에 없는 쪽 나눔, 표 크기, 빈 공간, 넘친 내용은 이미지를 보고 판단하세요.")


def _b64(path: str) -> str:
    import base64
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def complete_cli(provider: str, exe: str, model: str, system: str, user: str,
                 timeout: int = 600, on_progress=None, images: list | None = None) -> str:
    """Claude Code(claude -p) 또는 Codex(codex exec)로 한 번 답을 받는다. 구독 계정 로그인 사용."""
    import os
    import tempfile
    exe = exe or find_cli(provider)
    if not exe or not os.path.exists(exe):
        raise LLMError(f"{'Claude Code' if provider == 'claude_code' else 'Codex'}를 찾을 수 없습니다.\n"
                       "설정 탭의 안내대로 설치하거나 실행 파일 위치를 지정해 주세요.")
    images = [p for p in (images or []) if os.path.exists(p)]
    work = tempfile.mkdtemp(prefix="hanq_cli_")
    if provider == "claude_code":
        if images:
            look = ("먼저 Read 도구로 다음 이미지 파일들을 열어 보세요(다른 파일은 읽지 말 것):\n"
                    + "\n".join(images) + f"\n{IMAGE_NOTE}\n\n")
            rule = "중요: 위 이미지 외의 파일을 읽거나 쓰거나 명령을 실행하지 말고, 요청한 JSON만 답하세요."
        else:
            look, rule = "", "중요: 파일을 읽거나 쓰거나 명령을 실행하지 말고, 요청한 JSON만 바로 답하세요."
        prompt = f"{system}\n\n---\n\n{look}{user}\n\n{rule}"
        cmd = [exe, "-p", "--output-format", "text"]
        if images:
            cmd += ["--allowedTools", "Read", "--add-dir", os.path.dirname(images[0])]
        if model:
            cmd += ["--model", model]
        text = _run_cli(cmd, prompt, timeout, on_progress, work)
    else:
        note = f"{IMAGE_NOTE}\n\n" if images else ""
        prompt = (f"{system}\n\n---\n\n{note}{user}\n\n"
                  "중요: 파일을 읽거나 쓰거나 명령을 실행하지 말고, 요청한 JSON만 바로 답하세요.")
        out_file = os.path.join(work, "answer.txt")
        cmd = [exe, "exec", "--skip-git-repo-check", "--sandbox", "read-only",
               "--output-last-message", out_file]
        for img in images:
            cmd += ["--image", img]
        if model:
            cmd += ["--model", model]
        cmd.append("-")
        stdout = _run_cli(cmd, prompt, timeout, on_progress, work)
        try:
            with open(out_file, encoding="utf-8") as f:
                text = f.read()
        except OSError:
            text = stdout
    text = text.strip()
    if not text:
        raise LLMError("AI 응답이 비어 있습니다.")
    return text


def cli_version(provider: str, exe: str) -> str:
    import subprocess
    from platform_util import cli_env
    exe = exe or find_cli(provider)
    if not exe:
        raise LLMError("실행 파일을 찾을 수 없습니다.")
    r = subprocess.run([exe, "--version"], capture_output=True, timeout=30, env=cli_env(exe),
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return (r.stdout or r.stderr).decode("utf-8", errors="replace").strip()


def complete(provider: str, api_key: str, model: str, system: str, user: str,
             max_tokens: int = 32000, temperature: float = 0.4, timeout: int = 600,
             on_progress=None, images: list | None = None) -> str:
    if provider in CLI_PROVIDERS:
        return complete_cli(provider, api_key, model, system, user, timeout, on_progress, images)
    import os
    images = [p for p in (images or []) if os.path.exists(p)]
    if images:
        user = f"{IMAGE_NOTE}\n\n{user}"
    if not api_key:
        raise LLMError("API 키가 없습니다. 설정 탭에서 입력해주세요.")
    out: list[str] = []

    def push(s):
        if s:
            out.append(s)
            if on_progress:
                on_progress(sum(len(x) for x in out))

    if provider == "claude":
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": model, "max_tokens": max_tokens, "temperature": temperature,
                  "system": system, "stream": True,
                  "messages": [{"role": "user", "content": [
                      *({"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                     "data": _b64(p)}} for p in images),
                      {"type": "text", "text": user}]}]},
            stream=True, timeout=timeout)
        _check(resp)
        for ev in _sse_lines(resp):
            if ev.get("type") == "content_block_delta":
                push(ev["delta"].get("text", ""))
            elif ev.get("type") == "error":
                raise LLMError(ev.get("error", {}).get("message", str(ev)))

    elif provider in ("openai", "openrouter"):
        url = ("https://api.openai.com/v1/chat/completions" if provider == "openai"
               else "https://openrouter.ai/api/v1/chat/completions")
        content = [{"type": "text", "text": user}] + [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{_b64(p)}"}} for p in images]
        body = {"model": model, "stream": True,
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": content if images else user}]}
        body["response_format"] = {"type": "json_object"}
        if provider == "openai":
            body["max_completion_tokens"] = max_tokens
        else:
            body["max_tokens"] = max_tokens
            body["temperature"] = temperature
        resp = requests.post(url, headers={"Authorization": f"Bearer {api_key}"},
                             json=body, stream=True, timeout=timeout)
        _check(resp)
        for ev in _sse_lines(resp):
            if "error" in ev:
                raise LLMError(str(ev["error"].get("message", ev["error"])))
            for ch in ev.get("choices", []):
                push((ch.get("delta") or {}).get("content") or "")

    elif provider == "gemini":
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/{model}"
               f":streamGenerateContent?alt=sse")
        resp = requests.post(
            url, headers={"x-goog-api-key": api_key},
            json={"systemInstruction": {"parts": [{"text": system}]},
                  "contents": [{"role": "user", "parts": [
                      *({"inline_data": {"mime_type": "image/png", "data": _b64(p)}} for p in images),
                      {"text": user}]}],
                  "generationConfig": {"maxOutputTokens": max_tokens,
                                       "temperature": temperature,
                                       "responseMimeType": "application/json"}},
            stream=True, timeout=timeout)
        _check(resp)
        for ev in _sse_lines(resp):
            for cand in ev.get("candidates", []):
                for part in cand.get("content", {}).get("parts", []):
                    push(part.get("text", ""))
    else:
        raise LLMError(f"알 수 없는 제공자: {provider}")

    text = "".join(out).strip()
    if not text:
        raise LLMError("AI 응답이 비어 있습니다.")
    return text


def list_models(provider: str, api_key: str) -> list[str]:
    if not api_key:
        raise LLMError("API 키를 먼저 입력해주세요.")
    if provider == "claude":
        r = requests.get("https://api.anthropic.com/v1/models?limit=100",
                         headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"}, timeout=30)
        _check(r)
        return [m["id"] for m in r.json().get("data", [])]
    if provider == "openai":
        r = requests.get("https://api.openai.com/v1/models",
                         headers={"Authorization": f"Bearer {api_key}"}, timeout=30)
        _check(r)
        ids = [m["id"] for m in r.json().get("data", [])]
        return sorted((i for i in ids if i.startswith(("gpt", "o"))), reverse=True)
    if provider == "gemini":
        r = requests.get("https://generativelanguage.googleapis.com/v1beta/models?pageSize=200",
                         headers={"x-goog-api-key": api_key}, timeout=30)
        _check(r)
        return [m["name"].split("/", 1)[1] for m in r.json().get("models", [])
                if "generateContent" in m.get("supportedGenerationMethods", [])]
    if provider == "openrouter":
        r = requests.get("https://openrouter.ai/api/v1/models",
                         headers={"Authorization": f"Bearer {api_key}"}, timeout=30)
        _check(r)
        return sorted(m["id"] for m in r.json().get("data", []))
    raise LLMError(f"알 수 없는 제공자: {provider}")


def _repair_json(s: str) -> str:
    """문자열 안의 따옴표·줄바꿈 같은 흔한 AI 실수를 고친다.

    문자열 안에서 만난 '"' 다음(공백 제외)에 , : } ] 가 오지 않으면
    문장 속 따옴표로 보고 이스케이프한다.
    """
    out = []
    in_str = False
    i, n = 0, len(s)
    while i < n:
        ch = s[i]
        if not in_str:
            out.append(ch)
            if ch == '"':
                in_str = True
        elif ch == "\\" and i + 1 < n:
            out.append(s[i:i + 2])
            i += 1
        elif ch == '"':
            j = i + 1
            while j < n and s[j] in " \t\r\n":
                j += 1
            if j >= n or s[j] in ",:}]":
                out.append(ch)
                in_str = False
            else:
                out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            pass
        elif ch == "\t":
            out.append("\\t")
        else:
            out.append(ch)
        i += 1
    fixed = "".join(out)
    # 끝 쉼표 제거:  ,}  ,]
    import re
    return re.sub(r",(\s*[}\]])", r"\1", fixed)


def _extract(text: str) -> str:
    s = text.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s
        s = s.rsplit("```", 1)[0]
    start, end = s.find("{"), s.rfind("}")
    if start < 0 or end < 0:
        raise LLMError("AI 응답에서 JSON을 찾지 못했습니다.")
    return s[start:end + 1]


def parse_json(text: str) -> dict:
    s = _extract(text)
    try:
        return json.loads(s)
    except ValueError:
        pass
    try:
        return json.loads(_repair_json(s))
    except ValueError as e:
        raise LLMError(f"AI 응답 JSON 해석 실패: {e}")
