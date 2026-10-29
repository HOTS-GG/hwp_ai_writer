"""사용자 설정 (%APPDATA%\\HWP_AI_Writer\\settings.json, 맥은 ~/Library/Application Support/HWP_AI_Writer)에
저장되어 재시작 후에도 유지된다."""
import copy
import json
import os
import sys
import tempfile
from pathlib import Path

APP_VERSION = "1.2.4"

if sys.platform == "darwin":
    APP_DIR = Path.home() / "Library" / "Application Support" / "HWP_AI_Writer"
else:
    APP_DIR = Path(os.environ.get("APPDATA", Path.home())) / "HWP_AI_Writer"
SETTINGS_FILE = APP_DIR / "settings.json"
# 한글은 AppData\Roaming 아래로는 쪽 이미지를 쓰지 못하므로 Temp를 사용
CACHE_DIR = Path(tempfile.gettempdir()) / "HWP_AI_Writer"


def resource_dir() -> Path:
    """exe로 묶였을 때와 소스 실행 모두에서 forms·assets 폴더가 있는 위치."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


BUILTIN_FORMS_DIR = resource_dir() / "forms"

PROVIDERS = {
    "claude": "Claude",
    "openai": "GPT (OpenAI)",
    "gemini": "Gemini",
    "openrouter": "OpenRouter",
}

# API 키 없이 구독 계정으로 쓰는 방식 (컴퓨터에 설치된 CLI 프로그램 호출)
CLI_PROVIDERS = {
    "claude_code": "Claude Code (Claude 구독)",
    "codex": "Codex (ChatGPT 구독)",
}
ALL_PROVIDERS = {**PROVIDERS, **CLI_PROVIDERS}

DEFAULT_MODELS = {
    "claude": ["claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-5-5"],
    "openai": ["gpt-5", "gpt-5-mini", "gpt-4.1"],
    "gemini": ["gemini-2.5-pro", "gemini-2.5-flash"],
    "openrouter": ["anthropic/claude-sonnet-5.5", "openai/gpt-5", "google/gemini-2.5-pro"],
}

DEFAULTS = {
    "provider": "claude",
    "api_keys": {k: "" for k in PROVIDERS},
    "models": {**{k: v[0] for k, v in DEFAULT_MODELS.items()}, "claude_code": "", "codex": ""},
    "cli_paths": {"claude_code": "", "codex": ""},
    "model_lists": {},
    "school_name": "춘천고등학교",
    "department": "",
    "author": "",
    "output_dir": str(Path.home() / "Documents"),
    "user_forms_dir": str(APP_DIR / "forms"),
    "base_style_form": "01_행사·사업 운영 계획서.hwpx",
    "filename_pattern": "{title}_{date}",
    "auto_save": True,
    "open_after_save": False,
    "auto_preview": True,
    "live_preview": True,
    "preview_dpi": 96,
    "preview_zoom": 100,
    "ref_max_chars": 30000,
    "max_tokens": 32000,
    "temperature": 0.4,
    "request_timeout": 600,
    "ai_sees_screen": True,
    "max_screen_pages": 6,
    "window_geometry": "1480x880",
    "window_zoomed": False,
    "auto_update_check": True,
    "skip_version": "",
    "last_update_check": "",
    "auto_security_module": True,
    "session_keep_days": 7,
}


def load() -> dict:
    data = copy.deepcopy(DEFAULTS)
    try:
        saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        for k, v in saved.items():
            if isinstance(v, dict) and isinstance(data.get(k), dict):
                data[k].update(v)
            else:
                data[k] = v
    except (OSError, ValueError):
        pass
    # 예전 버전처럼 환경변수/.env에만 있던 키를 가져온다
    env = {"claude": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY",
           "gemini": "GEMINI_API_KEY", "openrouter": "OPENROUTER_API_KEY"}
    for p, var in env.items():
        if not data["api_keys"].get(p) and os.environ.get(var):
            data["api_keys"][p] = os.environ[var]
    return data


def save(data: dict):
    APP_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SETTINGS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(SETTINGS_FILE)
