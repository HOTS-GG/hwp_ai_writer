"""작업 기록: 만든 문서의 모든 버전·수정 대화·작성 요청을 사용자 폴더에 계속 저장해,
창을 닫거나 프로그램이 멈춰도 다음에 이어서 할 수 있게 한다 (UI를 모름).

  sessions/<id>/session.json   제목, 상태, 양식, 요청, 참고 자료, 저장 위치, 대화, 버전 목록
  sessions/<id>/v1.hwpx …      문서 버전 (되돌리기용)
  sessions/<id>/draft.hwpx     AI가 쓰는 도중의 문서 (다 쓰면 v1이 된다)
  sessions/_inputs.json        아직 생성 전인 입력(양식·요청·참고 자료)
"""
import datetime
import json
import shutil
import time
from pathlib import Path

from .config import APP_DIR

SESSIONS_DIR = APP_DIR / "sessions"
INPUTS_FILE = SESSIONS_DIR / "_inputs.json"

# 상태
GENERATING = "generating"   # AI가 쓰는 중 (이 상태로 남아 있으면 중간에 꺼진 것)
DONE = "done"
INTERRUPTED = "interrupted"

STATUS_TEXT = {GENERATING: "작성 도중 멈춤", INTERRUPTED: "작성 도중 멈춤", DONE: ""}


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _write_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


class Session:
    def __init__(self, folder: Path, data: dict):
        self.dir = folder
        self.data = data
        self._last_draft = 0.0

    @property
    def id(self) -> str:
        return self.dir.name

    @property
    def title(self) -> str:
        return self.data.get("title") or "문서"

    @property
    def status(self) -> str:
        st = self.data.get("status", DONE)
        return INTERRUPTED if st == GENERATING else st

    def save(self):
        self.data["updated"] = _now()
        _write_json(self.dir / "session.json", self.data)

    def update(self, **kw):
        self.data.update(kw)
        self.save()

    # ── 문서 버전 ──
    def version_paths(self) -> list[str]:
        return [str(self.dir / name) for name in self.data.get("versions", []) if (self.dir / name).exists()]

    def add_version(self, src: str) -> str:
        """문서 한 버전을 기록 폴더에 복사하고 그 경로를 돌려준다 (임시 폴더가 지워져도 남도록)."""
        names = self.data.setdefault("versions", [])
        name = f"v{len(names) + 1}.hwpx"
        while (self.dir / name).exists():
            name = f"v{len(names) + 1}_{int(time.time())}.hwpx"
        shutil.copyfile(src, self.dir / name)
        names.append(name)
        self.data["status"] = DONE
        (self.dir / "draft.hwpx").unlink(missing_ok=True)
        self.save()
        return str(self.dir / name)

    def pop_version(self):
        names = self.data.get("versions", [])
        if len(names) > 1:
            (self.dir / names.pop()).unlink(missing_ok=True)
            self.save()

    def set_draft(self, data: bytes, min_interval: float = 3.0, force: bool = False):
        """AI가 쓰는 도중의 문서. 너무 자주 쓰지 않도록 몇 초에 한 번만 저장한다."""
        now = time.time()
        if not force and now - self._last_draft < min_interval:
            return
        self._last_draft = now
        tmp = self.dir / "draft.tmp"
        tmp.write_bytes(data)
        tmp.replace(self.dir / "draft.hwpx")

    def draft_path(self) -> str | None:
        p = self.dir / "draft.hwpx"
        return str(p) if p.exists() else None

    # ── 대화 ──
    def add_chat(self, who: str, text: str):
        self.data.setdefault("chat", []).append([who, text])
        self.save()

    def set_history(self, history: list):
        self.data["history"] = [list(h) for h in history]
        self.save()

    def describe(self) -> str:
        when = self.data.get("updated", "")[:16].replace("T", " ")
        parts = [self.title, when]
        n = len(self.data.get("versions", []))
        if n > 1:
            parts.append(f"버전 {n}개")
        if STATUS_TEXT.get(self.status):
            parts.append(STATUS_TEXT[self.status])
        return " · ".join(p for p in parts if p)


class SessionStore:
    def __init__(self, root: Path = SESSIONS_DIR):
        self.root = root

    def new(self, title: str, **meta) -> Session:
        sid = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        folder = self.root / sid
        folder.mkdir(parents=True, exist_ok=True)
        s = Session(folder, {"title": title, "created": _now(), "status": DONE, "versions": [], "chat": [],
                             "history": [], **meta})
        s.save()
        return s

    def list(self) -> list[Session]:
        """쓸 수 있는(문서 버전이나 쓰던 문서가 있는) 기록, 최근 것 먼저."""
        out = []
        if not self.root.exists():
            return out
        for d in self.root.iterdir():
            f = d / "session.json"
            if not d.is_dir() or not f.exists():
                continue
            try:
                s = Session(d, json.loads(f.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
            if s.version_paths() or s.draft_path():
                out.append(s)
        return sorted(out, key=lambda s: s.data.get("updated", ""), reverse=True)

    def load(self, sid: str) -> Session | None:
        return next((s for s in self.list() if s.id == sid), None)

    def delete(self, sid: str):
        if sid and not sid.startswith("_"):
            shutil.rmtree(self.root / sid, ignore_errors=True)

    def cleanup(self, keep_days: int = 7, keep_max: int = 50):
        """오래된 기록과 버전이 하나도 없는 빈 기록을 지운다."""
        if not self.root.exists():
            return
        cutoff = (datetime.datetime.now() - datetime.timedelta(days=keep_days)).isoformat(timespec="seconds")
        usable = {s.id for s in self.list()}
        for d in self.root.iterdir():
            if d.is_dir() and d.name not in usable:
                shutil.rmtree(d, ignore_errors=True)
        for i, s in enumerate(self.list()):
            if s.data.get("updated", "") < cutoff or i >= keep_max:
                self.delete(s.id)

    # ── 생성 전 입력 ──
    def save_inputs(self, data: dict):
        try:
            _write_json(INPUTS_FILE if self.root == SESSIONS_DIR else self.root / "_inputs.json", data)
        except OSError:
            pass

    def load_inputs(self) -> dict:
        f = INPUTS_FILE if self.root == SESSIONS_DIR else self.root / "_inputs.json"
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
