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
              "설정 탭에서 보안 승인 모듈을 등록하면 이 창이 더 이상 뜨지 않습니다.")


class HwpWorker:
    def __init__(self, timeout: int = 60):
        self.timeout = timeout
        self.available: bool | None = None if IS_WIN else False
        self._q: queue.Queue = queue.Queue()
        self.stuck = False   # 한글이 응답하지 않는 중 (그동안 미리보기는 간이 렌더러로)
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    # ── 공개 작업 ───────────────────────────────────────────────────────
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
                # 쌓인 미리보기 요청은 마지막 것만 (변환은 모두 처리)
                if job[0] == "render":
                    pending = []
                    while not self._q.empty():
                        nxt = self._q.get()
                        if nxt is None:
                            self._q.put(None)
                            break
                        if nxt[0] == "render":
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
            answer(self._fallback(*args[:2]) if kind == "render" else None, STUCK_HINT)

        # 제한 시간이 지나면 먼저 알린다 (COM 호출 자체는 끊을 수 없다)
        timer = threading.Timer(self.timeout, on_timeout)
        timer.daemon = True
        timer.start()
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
                answer(self._export(self._get_hwp(), path, dpi), None)
            else:
                src, out, fmt = args
                answer(self._convert(self._get_hwp(), src, out, fmt), None)
        except Exception as e:
            self._quit()
            if kind == "render":
                answer(self._fallback(*args[:2]), f"한글 미리보기 실패: {e}")
            else:
                answer(None, f"한글로 변환하지 못했습니다: {e}")
        finally:
            timer.cancel()
            self.stuck = False

    def _get_hwp(self):
        if self._hwp is None:
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
        return self._hwp

    def _quit(self):
        if self._hwp is not None:
            try:
                self._hwp.Clear(1)
                self._hwp.Quit()
            except Exception:
                pass
            self._hwp = None

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
