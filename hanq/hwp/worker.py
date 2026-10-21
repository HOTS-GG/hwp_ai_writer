"""윈도우용 한글(HWP) COM을 전용 스레드 하나에서 쓴다: 쪽 이미지, 줄별 쪽 위치, HWP→HWPX 변환.

한글 인스턴스를 숨긴 채 유지해 반복 작업을 빠르게 한다. 보안 승인 모듈이 없으면 한글이 '접근 허용'
창에서 기다리며 멈출 수 있으므로, 작업마다 제한 시간을 두고 넘으면 callback에 오류를 먼저 알린다
(멈춘 한글은 다음 작업 때 새로 띄운다). 한글이 없으면(맥 등) 간이 렌더러로 대신한다.
"""
import hashlib
import json
import os
import queue
import threading
from pathlib import Path

from ..config import CACHE_DIR
from ..system import IS_WIN

STUCK_HINT = ("한글이 응답하지 않습니다. 한글 '접근 허용' 창이 떠 있으면 [모두 허용]을 눌러 주세요. "
              "(이번 실행 동안 다시 묻지 않습니다)")
PROMPT_HINT = "한글이 파일 접근 허용을 묻고 있습니다 — 앞에 뜬 창에서 [모두 허용]을 누르면 이번 실행 동안 다시 묻지 않습니다."


class HwpWorker:
    def __init__(self, timeout: int = 60):
        self.timeout = timeout
        self.available: bool | None = None if IS_WIN else False
        self._q: queue.Queue = queue.Queue()
        self.stuck = False   # 한글이 응답하지 않는 중 (그동안 미리보기는 간이 렌더러로)
        self.ready = False   # 이번 실행에서 한글로 쪽 이미지를 한 번이라도 만들었음 (접근 허용됨)
        self.on_prompt = None   # 한글이 '접근 허용' 창을 띄웠을 때 부를 함수 (안내용)
        self._pid = None
        self._frame_no = 0
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    # ── 공개 작업 ───────────────────────────────────────────────────────
    def render_frame(self, data: bytes, dpi: int, focus_key=None, timeout: float = 20.0):
        """실시간 화면 한 장: 메모리의 hwpx를 한글로 그려 (쪽 이미지 경로 목록, 강조 줄의 쪽 번호 0부터)를
        기다려서 돌려준다. 한글을 쓸 수 없거나 실패·시간 초과면 None."""
        if not self.ready or self.stuck:
            return None
        done = threading.Event()
        box = {}

        def cb(result, err):
            box["result"], box["err"] = result, err
            done.set()
        self._q.put(("frame", (data, dpi, focus_key), cb))
        if not done.wait(timeout) or box.get("err"):
            return None
        return box["result"]
    def render(self, path: str, dpi: int, callback):
        """callback(list[str] png 경로, error 또는 None) — 작업 스레드에서 불린다."""
        if self.stuck:
            threading.Thread(target=lambda: callback(self._fallback(path, dpi), STUCK_HINT), daemon=True).start()
            return
        self._q.put(("render", (path, dpi), callback))

    def convert(self, src: str, out: str, fmt: str, callback):
        """HWP ↔ HWPX 변환. callback(out 경로 또는 None, error 또는 None)."""
        self._q.put(("convert", (src, out, fmt), callback))

    def page_info(self, path: str, dpi: int = 96, timeout: int = 120):
        """(쪽 이미지 목록, {"paras": 본문 줄별 시작 쪽, "pages": 전체 쪽 수})를 기다려서 돌려준다.
        한글이 없거나 실패하면 ([], None)."""
        if not IS_WIN or self.available is False or self.stuck:
            return [], None
        done = threading.Event()
        box = {}

        def cb(pages, err):
            box["pages"], box["err"] = pages, err
            done.set()
        self.render(path, dpi, cb)
        if not done.wait(timeout) or box.get("err"):
            return [], None
        try:
            pagemap = json.loads((CACHE_DIR / _key(path, dpi) / "pagemap.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pagemap = None
        return box["pages"], pagemap

    def shutdown(self):
        self._q.put(None)

    # ── 작업 스레드 ─────────────────────────────────────────────────────
    def _loop(self):
        try:
            import pythoncom
            pythoncom.CoInitialize()
        except ImportError:  # 맥
            pythoncom = None
        self._hwp = None
        try:
            while True:
                job = self._q.get()
                if job is None:
                    break
                # 쌓인 미리보기·실시간 화면 요청은 종류별로 마지막 것만 (변환은 모두 처리)
                if job[0] in ("render", "frame"):
                    pending = []
                    while not self._q.empty():
                        nxt = self._q.get()
                        if nxt is None:
                            self._q.put(None)
                            break
                        if nxt[0] == job[0]:
                            if job[0] == "frame":   # 기다리는 쪽이 멈추지 않게 바로 답한다
                                job[2](None, "더 새 요청으로 건너뜀")
                            job = nxt
                        else:
                            pending.append(nxt)
                    for p in pending:
                        self._q.put(p)
                self._run(job)
        finally:
            self._quit()
            if pythoncom is not None:
                pythoncom.CoUninitialize()

    def _run(self, job):
        kind, args, cb = job
        fired = threading.Event()

        def answer(result, err):
            if not fired.is_set():
                fired.set()
                cb(result, err)

        def on_timeout():
            self.stuck = True
            self.ready = False
            answer(self._fallback(*args[:2]) if kind == "render" else None, STUCK_HINT)

        # 제한 시간이 지나면 먼저 알린다 (COM 호출 자체는 끊을 수 없다)
        timer = threading.Timer(self.timeout, on_timeout)
        timer.daemon = True
        timer.start()
        finished = threading.Event()
        if IS_WIN:
            threading.Thread(target=self._watch_prompt, args=(finished,), daemon=True).start()
        try:
            if kind == "render":
                path, dpi = args
                cached = _cached(path, dpi)
                if cached:
                    answer(cached, None)
                    return
                if not IS_WIN:
                    answer(self._fallback(path, dpi), None)
                    return
                pages = self._export(self._get_hwp(), path, dpi)
                self.ready = True
                answer(pages, None)
            elif kind == "frame":
                answer(self._frame(self._get_hwp(), *args), None)
            else:
                src, out, fmt = args
                answer(self._convert(self._get_hwp(), src, out, fmt), None)
        except Exception as e:
            self._quit()
            if kind == "frame":
                answer(None, f"한글 실시간 화면 실패: {e}")
            elif kind == "render":
                answer(self._fallback(*args[:2]), f"한글 미리보기 실패: {e}")
            else:
                answer(None, f"한글로 변환하지 못했습니다: {e}")
        finally:
            finished.set()
            timer.cancel()
            self.stuck = False

    def _watch_prompt(self, finished: threading.Event):
        """작업 중 한글이 '접근 허용' 창을 띄우면 맨 앞으로 가져오고 on_prompt로 알린다 (한 번만).
        보안 승인 모듈이 듣지 않는 한글(예: 2018)에서는 사용자가 [모두 허용]을 한 번 눌러야 한다."""
        if finished.wait(1.5):
            return
        for _ in range(600):
            dlg = _find_prompt(self._pid)
            if dlg:
                _bring_to_front(dlg)
                if self.on_prompt:
                    self.on_prompt()
                return
            if finished.wait(0.5):
                return

    def _get_hwp(self):
        if self._hwp is None:
            before = _hwp_pids()
            try:
                import win32com.client
                hwp = win32com.client.DispatchEx("HWPFrame.HwpObject")
            except Exception:
                self.available = False
                raise RuntimeError("한글 프로그램을 찾을 수 없습니다.")
            from .security import register
            register(hwp)
            try:
                hwp.XHwpWindows.Item(0).Visible = False
            except Exception:
                pass
            self.available = True
            self._hwp = hwp
            mine = _hwp_pids() - before
            self._pid = next(iter(mine)) if len(mine) == 1 else None
        return self._hwp

    def _quit(self):
        if self._hwp is not None:
            try:
                self._hwp.Clear(1)
                self._hwp.Quit()
            except Exception:
                pass
            self._hwp = None

    def _frame(self, hwp, data: bytes, dpi: int, focus_key=None):
        """실시간 화면: hwpx 바이트를 임시 파일로 열어 모든 쪽을 그리고, 강조 줄이 있는 쪽 번호를 찾는다.
        (쪽 이미지 경로 목록, 쪽 번호 0부터 또는 None)."""
        from PIL import Image
        self._frame_no += 1
        d = CACHE_DIR / "frames" / f"{self._frame_no % 3}"     # 화면이 읽는 중인 이전 것은 남겨 둔다
        d.mkdir(parents=True, exist_ok=True)
        for old in d.glob("*"):
            old.unlink(missing_ok=True)
        src = d / "frame.hwpx"
        src.write_bytes(data)
        if not hwp.Open(str(src), "HWPX", "forceopen:true;versionwarning:false"):
            raise RuntimeError("실시간 화면 문서를 열 수 없습니다.")
        try:
            focus_page = None
            if focus_key is not None and focus_key[0] == 0:   # SetPos는 첫 구역 본문 문단 번호로 찾는다
                try:
                    hwp.SetPos(0, int(focus_key[1]), 0)
                    focus_page = int(hwp.KeyIndicator()[3]) - 1
                except Exception:
                    focus_page = None
            pages = []
            for i in range(hwp.PageCount):
                bmp = d / f"page_{i:03d}.bmp"
                hwp.CreatePageImage(str(bmp), i, dpi, 24, "bmp")
                png = d / f"page_{i:03d}.png"
                Image.open(bmp).save(png, optimize=False)
                bmp.unlink(missing_ok=True)
                pages.append(str(png))
        finally:
            hwp.Clear(1)
        return pages, focus_page

    def _export(self, hwp, path: str, dpi: int) -> list[str]:
        from PIL import Image
        d = CACHE_DIR / _key(path, dpi)
        d.mkdir(parents=True, exist_ok=True)
        fmt = "HWPX" if path.lower().endswith(".hwpx") else "HWP"
        if not hwp.Open(os.path.abspath(path), fmt, "forceopen:true;versionwarning:false"):
            raise RuntimeError("문서를 열 수 없습니다.")
        pages = []
        try:
            _write_pagemap(hwp, path, d)
            for i in range(hwp.PageCount):
                bmp = d / f"page_{i:03d}.bmp"
                hwp.CreatePageImage(str(bmp), i, dpi, 24, "bmp")
                png = d / f"page_{i:03d}.png"
                Image.open(bmp).save(png, optimize=False)
                bmp.unlink(missing_ok=True)
                pages.append(str(png))
        finally:
            hwp.Clear(1)
        (d / "done").write_text("ok")
        return pages

    @staticmethod
    def _convert(hwp, src: str, out: str, fmt: str) -> str:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        src_fmt = "HWPX" if src.lower().endswith(".hwpx") else "HWP"
        if not hwp.Open(os.path.abspath(src), src_fmt, "forceopen:true;versionwarning:false"):
            raise RuntimeError("문서를 열 수 없습니다.")
        try:
            if not hwp.SaveAs(os.path.abspath(out), fmt, ""):
                raise RuntimeError("저장하지 못했습니다.")
        finally:
            hwp.Clear(1)
        return out

    @staticmethod
    def _fallback(path: str, dpi: int) -> list[str]:
        """한글 없이: 문서 내용을 직접 그린 간이 미리보기. 안 되면 hwpx에 든 미리보기 그림."""
        if not path.lower().endswith(".hwpx"):
            return []
        d = CACHE_DIR / ("simple_" + _key(path, dpi))
        if (d / "done").exists():
            return sorted(str(p) for p in d.glob("page_*.png"))
        try:
            from ..doc.render import render_pages
            pages = render_pages(path, dpi, d)
            (d / "done").write_text("ok")
            return pages
        except Exception:
            from ..doc import read_preview_png
            data = read_preview_png(path)
            if not data:
                return []
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            out = CACHE_DIR / (Path(path).stem + "_prv.png")
            out.write_bytes(data)
            return [str(out)]


def _hwp_pids() -> set[int]:
    """실행 중인 한글(Hwp.exe) 프로세스 번호들."""
    import subprocess
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Hwp.exe", "/FO", "CSV", "/NH"], capture_output=True,
                             text=True, timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except (OSError, subprocess.SubprocessError):
        return set()
    pids = set()
    for line in out.splitlines():
        parts = line.split('","')
        if len(parts) > 1 and parts[1].isdigit():
            pids.add(int(parts[1]))
    return pids


def _find_prompt(pid: int | None):
    """그 한글 프로세스가 띄운 '접근 허용' 창(제목이 '글'로 끝나는 작은 창)."""
    if pid is None:
        return None
    import win32gui
    import win32process
    found = []

    def enum(h, _):
        if not win32gui.IsWindowVisible(h):
            return True
        if win32process.GetWindowThreadProcessId(h)[1] != pid:
            return True
        title = win32gui.GetWindowText(h)
        if title.endswith("글") and " - " not in title:
            found.append(h)
        return True
    try:
        win32gui.EnumWindows(enum, None)
    except Exception:
        return None
    return found[0] if found else None


def _bring_to_front(h):
    import win32con
    import win32gui
    try:
        win32gui.ShowWindow(h, win32con.SW_SHOWNORMAL)
        flags = win32con.SWP_NOMOVE | win32con.SWP_NOSIZE
        win32gui.SetWindowPos(h, win32con.HWND_TOPMOST, 0, 0, 0, 0, flags)
        win32gui.SetWindowPos(h, win32con.HWND_NOTOPMOST, 0, 0, 0, 0, flags)
        win32gui.SetForegroundWindow(h)
    except Exception:
        pass


def _key(path: str, dpi: int) -> str:
    st = os.stat(path)
    raw = f"{os.path.abspath(path)}|{st.st_mtime_ns}|{st.st_size}|{dpi}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]


def _cached(path, dpi):
    d = CACHE_DIR / _key(path, dpi)
    if (d / "done").exists():
        if path.lower().endswith(".hwpx") and not (d / "pagemap.json").exists():
            return None
        return sorted(str(p) for p in d.glob("page_*.png"))
    return None


def _write_pagemap(hwp, path: str, d: Path):
    """본문(섹션 바로 아래) 줄마다 몇 쪽에서 시작하는지 기록한다."""
    if not path.lower().endswith(".hwpx"):
        return
    try:
        from ..doc import HwpxDocument
        total = sum(1 for _ in HwpxDocument(path).top_paragraphs())
        pm = []
        for i in range(total):
            hwp.SetPos(0, i, 0)
            pm.append(int(hwp.KeyIndicator()[3]))
        info = {"paras": pm, "pages": int(hwp.PageCount)}
        (d / "pagemap.json").write_text(json.dumps(info), encoding="utf-8")
    except Exception:
        pass
