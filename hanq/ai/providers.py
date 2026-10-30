"""AI 호출: Claude / OpenAI / Gemini / OpenRouter API(HTTP 스트리밍)와 Claude Code / Codex CLI(구독 계정).

complete()는 받은 글자가 늘 때마다 on_text(지금까지 받은 전체 글)를 불러, 받는 대로 문서에 반영할 수 있게 한다.
stop(threading.Event)이 켜지면 받기를 멈추고 Cancelled를 낸다.
"""
import base64
import glob
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass

import requests

from ..system import IS_MAC, IS_WIN, cli_env

API_PROVIDERS = ("claude", "openai", "gemini", "openrouter")
CLI_PROVIDERS = ("claude_code", "codex")
CLI_NAMES = {"claude_code": "claude", "codex": "codex"}

IMAGE_NOTE = ("첨부한 이미지는 지금 문서를 한글에서 연 실제 화면(1쪽부터 차례로)입니다. "
              "글자 목록에 없는 쪽 나눔, 표 크기, 빈 공간, 넘친 내용은 이미지를 보고 판단하세요.")

WEB_SEARCH_RULE = """웹 검색을 쓸 수 있습니다 (NotebookLM처럼 자료를 찾아 문서에 반영):
- 최신 제도·지침·통계·사례·행사 정보처럼 사실 확인이 필요하면 웹 검색으로 찾아 반영. 요청과 참고 자료로 충분하면 검색하지 않음
- 정부·교육청·공공기관·학술 자료 같은 믿을 만한 출처를 먼저 씀. 찾은 사실만 쓰고 지어내지 않음
- 이미지·영상·음성·그림은 절대 새로 만들지 않음. 사진·영상·서식 파일·사이트처럼 글이 아닌 자료를 요청받으면
  웹에서 찾아 그 링크만 줌 (파일을 내려받거나 문서에 그림을 넣지 않음)
- 쓴 출처와 찾은 자료 링크는 JSON 최상위의 "sources": [{"title": "자료 제목", "url": "https://…"}]에 넣음
  (최대 8개, 검색 결과에서 실제로 확인한 주소만. 주소를 지어내지 않음)
- 문서 본문에 링크 줄을 넣는 것은 사용자가 원할 때만 (예: '※ 참고: 자료 제목(주소)')
- 검색 과정 설명 없이 최종 JSON만 출력"""


class LLMError(Exception):
    pass


class Cancelled(LLMError):
    def __init__(self):
        super().__init__("사용자가 중단했습니다.")


@dataclass
class AIConfig:
    provider: str
    api_key: str            # CLI 방식이면 실행 파일 경로
    model: str
    max_tokens: int = 32000
    temperature: float = 0.4
    timeout: int = 600
    ref_max_chars: int = 30000
    send_images: bool = True
    max_images: int = 6
    web_search: bool = False   # 웹 검색 허용 (글·링크만 찾음. 그림·영상은 만들지 않음)

    @property
    def is_cli(self) -> bool:
        return self.provider in CLI_PROVIDERS

    @property
    def streams(self) -> bool:
        """받는 대로 글자를 보여줄 수 있는지 (Codex CLI는 다 끝난 뒤에 한 번에 준다)."""
        return self.provider != "codex"


class _Stream:
    """받은 조각을 모으고, on_text·on_progress를 부르고, 중단 여부를 확인한다."""

    def __init__(self, on_text, on_progress, stop, on_note=None):
        self.parts: list[str] = []
        self.size = 0
        self.on_text = on_text
        self.on_progress = on_progress
        self.stop = stop
        self.on_note = on_note

    def note(self, msg: str):
        """받는 글자와 따로 알릴 진행 상황 (예: 웹 검색 중)."""
        if self.on_note:
            self.on_note(msg)

    def check(self):
        if self.stop is not None and self.stop.is_set():
            raise Cancelled()

    def push(self, s: str):
        self.check()
        if not s:
            return
        self.parts.append(s)
        self.size += len(s)
        if self.on_progress:
            self.on_progress(self.size)
        if self.on_text:
            self.on_text(self.text())

    def text(self) -> str:
        return "".join(self.parts)


def _sse(resp, stream: _Stream):
    # 바이트 단위로 줄을 나눈 뒤 UTF-8로 디코딩한다. (서버가 charset을 안 주면
    # requests가 Latin-1로 풀어 한글이 깨지고, 깨진 문자가 줄바꿈으로 오인돼 내용이 잘림)
    try:
        for raw_bytes in resp.iter_lines():
            stream.check()
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
    finally:
        resp.close()


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


def _b64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


# ── 진입점 ──────────────────────────────────────────────────────────────────

def complete(cfg: AIConfig, system: str, user: str, images: list | None = None,
             on_text=None, on_progress=None, stop: threading.Event | None = None, on_note=None) -> str:
    """AI 답을 받는다. on_text(전체 글)는 받는 중에 계속, on_progress(n)는 받은 글자 수(CLI는 -경과초)."""
    images = [p for p in (images or []) if os.path.exists(p)]
    stream = _Stream(on_text, on_progress, stop, on_note)
    if cfg.web_search:
        system = f"{system}\n\n{WEB_SEARCH_RULE}"
    if cfg.is_cli:
        return _complete_cli(cfg, system, user, images, stream)
    if not cfg.api_key:
        raise LLMError("API 키가 없습니다. 설정 탭에서 입력해주세요.")
    if images:
        user = f"{IMAGE_NOTE}\n\n{user}"
    try:
        if cfg.provider == "claude":
            _claude(cfg, system, user, images, stream)
        elif cfg.provider in ("openai", "openrouter"):
            _openai(cfg, system, user, images, stream)
        elif cfg.provider == "gemini":
            _gemini(cfg, system, user, images, stream)
        else:
            raise LLMError(f"알 수 없는 제공자: {cfg.provider}")
    except requests.RequestException as e:
        stream.check()
        raise LLMError(f"AI 서버에 연결하지 못했습니다: {e}")
    text = stream.text().strip()
    if not text:
        raise LLMError("AI 응답이 비어 있습니다.")
    return text


def _claude(cfg, system, user, images, stream):
    body = {"model": cfg.model, "max_tokens": cfg.max_tokens, "temperature": cfg.temperature,
            "system": system, "stream": True,
            "messages": [{"role": "user", "content": [
                *({"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": _b64(p)}}
                  for p in images),
                {"type": "text", "text": user}]}]}
    if cfg.web_search:
        body["tools"] = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}]
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": cfg.api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json=body, stream=True, timeout=cfg.timeout)
    _check(resp)
    for ev in _sse(resp, stream):
        if ev.get("type") == "content_block_start" and ev.get("content_block", {}).get("type") == "server_tool_use":
            stream.note("웹 검색 중")
        elif ev.get("type") == "content_block_delta" and ev["delta"].get("type") == "text_delta":
            stream.push(ev["delta"].get("text", ""))
        elif ev.get("type") == "error":
            raise LLMError(ev.get("error", {}).get("message", str(ev)))


def _openai_search(cfg, system, user, images, stream):
    """OpenAI 웹 검색은 Responses API에서만 된다."""
    content = [{"type": "input_text", "text": user}] + [
        {"type": "input_image", "image_url": f"data:image/png;base64,{_b64(p)}"} for p in images]
    body = {"model": cfg.model, "stream": True, "instructions": system, "max_output_tokens": cfg.max_tokens,
            "tools": [{"type": "web_search"}],
            "input": [{"role": "user", "content": content}]}
    resp = requests.post("https://api.openai.com/v1/responses", headers={"Authorization": f"Bearer {cfg.api_key}"},
                         json=body, stream=True, timeout=cfg.timeout)
    _check(resp)
    for ev in _sse(resp, stream):
        t = ev.get("type", "")
        if t == "response.output_text.delta":
            stream.push(ev.get("delta", ""))
        elif t.startswith("response.web_search_call.") and t.endswith("searching"):
            stream.note("웹 검색 중")
        elif t in ("error", "response.failed"):
            err = ev.get("error") or (ev.get("response") or {}).get("error") or ev
            raise LLMError(str(err.get("message", err) if isinstance(err, dict) else err))


def _openai(cfg, system, user, images, stream):
    if cfg.web_search and cfg.provider == "openai":
        return _openai_search(cfg, system, user, images, stream)
    url =("https://api.openai.com/v1/chat/completions" if cfg.provider == "openai"
           else "https://openrouter.ai/api/v1/chat/completions")
    content = [{"type": "text", "text": user}] + [
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{_b64(p)}"}} for p in images]
    body = {"model": cfg.model, "stream": True, "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": content if images else user}]}
    if cfg.provider == "openai":
        body["max_completion_tokens"] = cfg.max_tokens
    else:
        body["max_tokens"] = cfg.max_tokens
        body["temperature"] = cfg.temperature
        if cfg.web_search:
            body["plugins"] = [{"id": "web", "max_results": 5}]
    resp = requests.post(url, headers={"Authorization": f"Bearer {cfg.api_key}"}, json=body,
                         stream=True, timeout=cfg.timeout)
    _check(resp)
    for ev in _sse(resp, stream):
        if "error" in ev:
            raise LLMError(str(ev["error"].get("message", ev["error"])))
        for ch in ev.get("choices", []):
            stream.push((ch.get("delta") or {}).get("content") or "")


def _gemini(cfg, system, user, images, stream):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{cfg.model}:streamGenerateContent?alt=sse"
    body = {"systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [
                *({"inline_data": {"mime_type": "image/png", "data": _b64(p)}} for p in images),
                {"text": user}]}],
            "generationConfig": {"maxOutputTokens": cfg.max_tokens, "temperature": cfg.temperature,
                                 "responseMimeType": "application/json"}}
    if cfg.web_search:
        # 구글 검색 연결은 JSON 전용 응답 설정과 함께 쓸 수 없어 뺀다 (JSON은 프롬프트로 요구)
        body["tools"] = [{"google_search": {}}]
        del body["generationConfig"]["responseMimeType"]
    resp = requests.post(url, headers={"x-goog-api-key": cfg.api_key}, json=body, stream=True, timeout=cfg.timeout)
    _check(resp)
    for ev in _sse(resp, stream):
        for cand in ev.get("candidates", []):
            for part in cand.get("content", {}).get("parts", []):
                stream.push(part.get("text", ""))


# ── CLI (구독 계정) ────────────────────────────────────────────────────────────

def find_cli(provider: str) -> str | None:
    """Claude Code / Codex 실행 파일을 PATH와 흔한 설치 위치에서 찾는다."""
    name = CLI_NAMES[provider]
    found = shutil.which(name, path=cli_env()["PATH"])
    if found:
        return found
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


def cli_version(provider: str, exe: str) -> str:
    exe = exe or find_cli(provider)
    if not exe:
        raise LLMError("실행 파일을 찾을 수 없습니다.")
    r = subprocess.run([exe, "--version"], capture_output=True, timeout=30, env=cli_env(exe),
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return (r.stdout or r.stderr).decode("utf-8", errors="replace").strip()


def _login_hint(exe: str, text: str) -> str:
    low = text.lower()
    if not ("login" in low or "auth" in low or "credential" in low):
        return ""
    name = "claude" if "claude" in os.path.basename(exe).lower() else "codex"
    if IS_MAC:
        return (f"\n\n로그인이 필요합니다. 터미널을 열고  {name}  를 실행해 로그인한 뒤 다시 시도해 주세요."
                "\n(Claude·ChatGPT 데스크톱 앱의 로그인과는 따로입니다.)")
    return "\n\n로그인이 필요합니다. 명령 프롬프트에서 한 번 실행해 로그인해 주세요."


def _run_cli(cmd: list[str], stdin_text: str, timeout: int, cwd: str, stream: _Stream, on_line=None) -> str:
    """CLI를 실행해 표준 출력을 줄 단위로 읽는다(on_line). 경과 초를 on_progress(-초)로 알린다."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                cwd=cwd, creationflags=flags, env=cli_env(cmd[0]))
    except OSError as e:
        raise LLMError(f"실행할 수 없습니다: {cmd[0]}\n{e}")
    out_lines: list[bytes] = []
    err: list[bytes] = []

    def feed():
        try:
            proc.stdin.write(stdin_text.encode("utf-8"))
            proc.stdin.close()
        except OSError:
            pass

    def read_out():
        for line in iter(proc.stdout.readline, b""):
            out_lines.append(line)
            if on_line:
                try:
                    on_line(line.decode("utf-8", errors="replace"))
                except Cancelled:
                    pass

    threads = [threading.Thread(target=f, daemon=True) for f in
               (feed, read_out, lambda: err.append(proc.stderr.read()))]
    for t in threads:
        t.start()
    start = time.time()
    try:
        while proc.poll() is None:
            time.sleep(0.3)
            stream.check()
            elapsed = int(time.time() - start)
            if stream.on_progress and not stream.size:
                stream.on_progress(-elapsed)
            if elapsed > timeout:
                raise LLMError(f"응답 대기 시간({timeout}초)을 넘었습니다.")
    except BaseException:
        proc.kill()
        raise
    for t in threads[1:]:
        t.join(5)
    stream.check()
    out = b"".join(out_lines).decode("utf-8", errors="replace")
    errs = b"".join(err).decode("utf-8", errors="replace")
    if proc.returncode != 0:
        raise LLMError(f"{cmd[0]} 실행 오류 (코드 {proc.returncode})\n{(errs or out).strip()[:600]}"
                       + _login_hint(cmd[0], out + errs))
    return out


def _complete_cli(cfg: AIConfig, system: str, user: str, images: list, stream: _Stream) -> str:
    exe = cfg.api_key or find_cli(cfg.provider)
    if not exe or not os.path.exists(exe):
        raise LLMError(f"{'Claude Code' if cfg.provider == 'claude_code' else 'Codex'}를 찾을 수 없습니다.\n"
                       "설정 탭의 안내대로 설치하거나 실행 파일 위치를 지정해 주세요.")
    work = tempfile.mkdtemp(prefix="hanq_cli_")
    try:
        text = _run_cli_provider(cfg, system, user, images, stream, exe, work)
    finally:   # 오류·중단 때도 임시 폴더를 남기지 않는다
        shutil.rmtree(work, ignore_errors=True)
    text = text.strip()
    if not text:
        raise LLMError("AI 응답이 비어 있습니다.")
    return text


def _run_cli_provider(cfg: AIConfig, system: str, user: str, images: list, stream: _Stream, exe: str,
                      work: str) -> str:
    if cfg.provider == "claude_code":
        web = " 필요하면 WebSearch·WebFetch로 웹 자료를 찾아도 됩니다." if cfg.web_search else ""
        if images:
            look = ("먼저 Read 도구로 다음 이미지 파일들을 열어 보세요(다른 파일은 읽지 말 것):\n"
                    + "\n".join(images) + f"\n{IMAGE_NOTE}\n\n")
            rule = f"중요: 위 이미지 외의 파일을 읽거나 쓰거나 명령을 실행하지 말고, 요청한 JSON만 답하세요.{web}"
        else:
            look, rule = "", f"중요: 파일을 읽거나 쓰거나 명령을 실행하지 말고, 요청한 JSON만 답하세요.{web}"
        prompt = f"{system}\n\n---\n\n{look}{user}\n\n{rule}"
        cmd = [exe, "-p", "--output-format", "stream-json", "--include-partial-messages", "--verbose"]
        # 허락한 도구만 쓴다 (그 밖의 도구는 -p 모드에서 거절됨): 화면 이미지 읽기, 웹 검색
        tools = (["Read"] if images else []) + (["WebSearch", "WebFetch"] if cfg.web_search else [])
        if tools:
            cmd += ["--allowedTools", *tools]
        if images:
            cmd += ["--add-dir", os.path.dirname(images[0])]
        if cfg.model:
            cmd += ["--model", cfg.model]
        final = {}

        def on_line(line: str):
            try:
                ev = json.loads(line)
            except ValueError:
                return
            t = ev.get("type")
            if t == "stream_event":
                e = ev.get("event", {})
                if e.get("type") == "content_block_start" and e.get("content_block", {}).get("type") == "tool_use":
                    name = e["content_block"].get("name", "")
                    if name.startswith("Web"):
                        stream.note("웹 검색 중" if name == "WebSearch" else "웹 페이지 읽는 중")
                elif e.get("type") == "content_block_delta" and e.get("delta", {}).get("type") == "text_delta":
                    stream.push(e["delta"].get("text", ""))
                elif e.get("type") == "message_start" and stream.size:
                    stream.push("\n")   # 이미지 읽기 뒤 새 답 (앞 답과 섞이지 않게)
            elif t == "result":
                final["text"] = ev.get("result") or ""
                if ev.get("is_error"):
                    final["error"] = ev.get("result") or "오류"

        _run_cli(cmd, prompt, cfg.timeout, work, stream, on_line)
        if final.get("error"):
            raise LLMError(f"Claude Code 오류: {final['error'][:600]}" + _login_hint(exe, final["error"]))
        # 최종 답(result)이 가장 정확하다. 스트리밍 조각은 화면용.
        return final.get("text") or stream.text()
    else:
        note = f"{IMAGE_NOTE}\n\n" if images else ""
        prompt = (f"{system}\n\n---\n\n{note}{user}\n\n"
                  "중요: 파일을 읽거나 쓰거나 명령을 실행하지 말고, 요청한 JSON만 바로 답하세요.")
        out_file = os.path.join(work, "answer.txt")
        cmd = [exe, "exec", "--skip-git-repo-check", "--sandbox", "read-only", "--output-last-message", out_file]
        if cfg.web_search:
            # 버전에 따라 설정 이름이 달라 둘 다 준다 (모르는 설정은 무시됨)
            cmd += ["-c", 'web_search="live"', "-c", "tools.web_search=true"]
        for img in images:
            cmd += ["--image", img]
        if cfg.model:
            cmd += ["--model", cfg.model]
        cmd.append("-")
        stdout = _run_cli(cmd, prompt, cfg.timeout, work, stream)
        try:
            with open(out_file, encoding="utf-8") as f:
                return f.read()
        except OSError:
            return stdout


# ── 모델 목록 ──────────────────────────────────────────────────────────────────

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
