"""한글(HWP) COM으로 문서 각 쪽을 이미지로 내보내 미리보기를 만든다.

한글 인스턴스 하나를 전용 스레드에서 숨긴 채로 유지해 반복 미리보기를 빠르게 한다.
한글이 없으면 hwpx 안의 미리보기 이미지(첫 쪽)로 대신한다.
"""
import hashlib
import os
import queue
import threading
from pathlib import Path

from settings import CACHE_DIR


class Renderer:
    def __init__(self):
        self._q: queue.Queue = queue.Queue()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        self.available: bool | None = None

    def render(self, path: str, dpi: int, callback):
        """callback(list[str] png 경로, error 문자열 또는 None) — 작업 스레드에서 호출됨."""
        self._q.put((path, dpi, callback))

    def page_info(self, path: str, dpi: int = 96, timeout: int = 120):
        """(쪽 이미지 목록, {"paras": 본문 줄별 시작 쪽, "pages": 전체 쪽 수})를 기다려서 돌려준다.
        한글이 없으면 ([], None)."""
        import json
        done = threading.Event()
        box = {}

        def cb(pages, err):
            box["pages"], box["err"] = pages, err
            done.set()
        self.render(path, dpi, cb)
        if not done.wait(timeout) or box.get("err"):
            return [], None
        pm_file = CACHE_DIR / self._key(path, dpi) / "pagemap.json"
        try:
            pagemap = json.loads(pm_file.read_text(encoding="utf-8"))
            if isinstance(pagemap, list):  # 예전 형식
                pagemap = {"paras": pagemap, "pages": len(box["pages"])}
        except (OSError, ValueError):
            pagemap = None
        return box["pages"], pagemap

    def shutdown(self):
        self._q.put(None)

    def _loop(self):
        import pythoncom
        pythoncom.CoInitialize()
        hwp = None
        try:
            while True:
                job = self._q.get()
                if job is None:
                    break
                # 쌓인 요청 중 마지막 것만 처리
                while not self._q.empty():
                    nxt = self._q.get()
                    if nxt is None:
                        self._q.put(None)
                        break
                    job = nxt
                path, dpi, cb = job
                try:
                    cached = self._cached(path, dpi)
                    if cached:
                        cb(cached, None)
                        continue
                    if hwp is None:
                        hwp = self._start_hwp()
                    cb(self._export(hwp, path, dpi), None)
                except Exception as e:
                    if hwp is not None:
                        try:
                            hwp.Quit()
                        except Exception:
                            pass
                        hwp = None
                    cb(self._fallback(path), f"한글 미리보기 실패: {e}")
        finally:
            if hwp is not None:
                try:
                    hwp.Clear(1)
                    hwp.Quit()
                except Exception:
                    pass
            pythoncom.CoUninitialize()

    def _start_hwp(self):
        import win32com.client
        try:
            hwp = win32com.client.DispatchEx("HWPFrame.HwpObject")
        except Exception:
            self.available = False
            raise RuntimeError("한글 프로그램을 찾을 수 없습니다.")
        import hwp_security
        hwp_security.register(hwp)
        try:
            hwp.XHwpWindows.Item(0).Visible = False
        except Exception:
            pass
        self.available = True
        return hwp

    @staticmethod
    def _key(path: str, dpi: int) -> str:
        st = os.stat(path)
        raw = f"{os.path.abspath(path)}|{st.st_mtime_ns}|{st.st_size}|{dpi}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]

    def _cached(self, path, dpi):
        d = CACHE_DIR / self._key(path, dpi)
        if (d / "done").exists():
            if path.lower().endswith(".hwpx") and not (d / "pagemap.json").exists():
                return None
            return sorted(str(p) for p in d.glob("page_*.png"))
        return None

    def _export(self, hwp, path: str, dpi: int) -> list[str]:
        from PIL import Image
        d = CACHE_DIR / self._key(path, dpi)
        d.mkdir(parents=True, exist_ok=True)
        fmt = "HWPX" if path.lower().endswith(".hwpx") else "HWP"
        if not hwp.Open(os.path.abspath(path), fmt, "forceopen:true;versionwarning:false"):
            raise RuntimeError("문서를 열 수 없습니다.")
        pages = []
        try:
            self._write_pagemap(hwp, path, d)
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
    def _write_pagemap(hwp, path: str, d: Path):
        """본문(섹션 바로 아래) 줄마다 몇 쪽에서 시작하는지 기록한다."""
        import json
        if not path.lower().endswith(".hwpx"):
            return
        try:
            from hwpx_form import HwpxDoc, P
            doc = HwpxDoc(path)
            total = sum(len(list(r.iterchildren(P))) for r in doc.ordered_sections())
            pm = []
            for i in range(total):
                hwp.SetPos(0, i, 0)
                pm.append(int(hwp.KeyIndicator()[3]))
            info = {"paras": pm, "pages": int(hwp.PageCount)}
            (d / "pagemap.json").write_text(json.dumps(info), encoding="utf-8")
        except Exception:
            pass

    @staticmethod
    def _fallback(path: str) -> list[str]:
        from hwpx_form import read_preview_png
        data = read_preview_png(path) if path.lower().endswith(".hwpx") else None
        if not data:
            return []
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        out = CACHE_DIR / (Path(path).stem + "_prv.png")
        out.write_bytes(data)
        return [str(out)]
