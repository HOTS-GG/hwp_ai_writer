"""LiveView: 문서(hwpx 바이트나 파일)를 전용 스레드에서 쪽 이미지로 그린다.

그리는 엔진 순서 (실시간 화면):
  1) 한글 — 이번 실행에서 한글 미리보기가 한 번 성공했으면(접근 허용됨) 한글이 직접 그린다. 가장 정확
  2) rhwp — 한글 없이 거의 같은 모양 (도형·글꼴 일부가 다를 수 있음)
  3) 간이 렌더러
원본 파일(참고 자료·양식)은 1쪽만이라도 파일 안에 한글이 저장해 둔 그림(PrvImage)을 쓴다.
작업이 보낸 문서에서 '방금 쓴 줄'(FOCUS_ATTR 표시)은 노란 음영으로 칠하고, 그 줄이 놓인 쪽·위치를 함께 알린다.
그리는 동안 새 요청이 오면 가장 최근 것만 그린다. 결과는 callback(RenderResult, token)으로 알린다
(작업 스레드에서 불리므로 UI는 after()로 넘겨 받아야 한다).
"""
import queue
import tempfile
import threading
from pathlib import Path

from ..doc.render import FOCUS_ATTR, FOCUS_FILL, RenderResult, render

ENGINE_HANGUL = "hangul"
ENGINE_RHWP = "rhwp"
ENGINE_SIMPLE = "simple"


class LiveView:
    def __init__(self, callback, dpi: int = 96, rhwp=None, hangul=None):
        """rhwp: hanq.hwp.rhwp.Rhwp 또는 None. hangul: hanq.hwp.HwpWorker 또는 None."""
        self._cb = callback
        self.dpi = dpi
        self.rhwp = rhwp
        self.hangul = hangul
        self._q: queue.Queue = queue.Queue()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    @property
    def engine(self) -> str:
        if self.hangul is not None and self.hangul.ready and not self.hangul.stuck:
            return ENGINE_HANGUL
        return ENGINE_RHWP if self.rhwp is not None else ENGINE_SIMPLE

    def submit(self, data: bytes, token=None):
        """메모리의 hwpx(실시간 화면). token은 요청 구분값으로 결과와 함께 돌려준다."""
        self._q.put(("bytes", data, token))

    def submit_file(self, path: str, token=None, original: bool = False):
        """파일(hwpx·hwp) 미리보기. original=True면 한글로 저장된 그대로의 파일(참고 자료·양식)이라
        파일 안의 첫 쪽 그림이 정확하므로 1쪽은 그 그림을 쓴다."""
        self._q.put(("file", (path, original), token))

    def close(self):
        self._q.put(None)

    def _loop(self):
        while True:
            job = self._q.get()
            if job is None:
                return
            while not self._q.empty():      # 쌓인 것 중 마지막만
                nxt = self._q.get()
                if nxt is None:
                    return
                job = nxt
            kind, src, token = job
            original = False
            if kind == "file":
                src, original = src
            try:
                result = self._render(kind, src)
            except Exception:   # 그리기 실패는 화면만 건너뛴다 (문서 작업에는 영향 없음)
                try:
                    result = self._render_simple(kind, src)
                except Exception:
                    continue
            if original and result.pages:
                result = _with_saved_first_page(result, src)
            self._cb(result, token)

    # ── 그리기 ──────────────────────────────────────────────────────────
    def _render(self, kind: str, src):
        if kind == "bytes" and self.engine == ENGINE_HANGUL:
            data, focus_key = _shade_focus(src)
            got = self.hangul.render_frame(data, self.dpi, focus_key)
            if got is not None:
                from PIL import Image
                paths, fp = got
                pages = []
                for p in paths:
                    with Image.open(p) as im:
                        pages.append(im.convert("RGB"))
                return RenderResult(pages, fp, None)
        if self.rhwp is None:
            return self._render_simple(kind, src)
        if kind == "file":
            data = Path(src).read_bytes()
            if not data.startswith(b"PK"):          # HWP 바이너리는 파일 그대로 그린다
                from PIL import Image
                with tempfile.TemporaryDirectory(prefix="hanq_rhwp_") as d:
                    pages = []
                    for p in self.rhwp.render_to_dir(src, Path(d), self.dpi):
                        with Image.open(p) as im:
                            pages.append(im.convert("RGB"))
                return RenderResult(pages, None, None)
            src = data
        data, focus_key = _shade_focus(src)
        pages, layout = self.rhwp.render_bytes(data, self.dpi, with_layout=focus_key is not None)
        fp = fy = None
        if focus_key is not None and layout is not None and focus_key in layout.pos:
            fp, y96 = layout.pos[focus_key]
            fy = int(y96 * self.dpi / 96)
        return RenderResult(pages, fp, fy)

    def _render_simple(self, kind: str, src):
        if kind == "file" and not str(src).lower().endswith(".hwpx"):
            raise ValueError("간이 렌더러는 HWPX만 그립니다.")
        return render(src, self.dpi)


def _with_saved_first_page(result: RenderResult, path: str) -> RenderResult:
    """1쪽을 파일 안에 한글이 저장해 둔 첫 쪽 그림으로 바꾼다 (쪽 크기에 맞춰)."""
    im = None
    try:
        if str(path).lower().endswith(".hwpx"):
            import io
            from PIL import Image
            from ..doc import read_preview_png
            data = read_preview_png(path)
            im = Image.open(io.BytesIO(data)).convert("RGB") if data else None
        else:
            from ..readers.hwp import preview_image
            im = preview_image(path)
    except Exception:
        im = None
    if im is None:
        return result
    w = result.pages[0].width
    im = im.resize((w, int(im.height * w / im.width)))
    return RenderResult([im] + list(result.pages[1:]), result.focus_page, result.focus_y)


def _shade_focus(data: bytes):
    """FOCUS_ATTR가 붙은 줄을 노란 음영 글자로 바꾼 사본과, 첫 강조 줄의 (구역 번호, 본문 문단 번호).
    강조할 줄이 없으면 (원래 바이트, None)."""
    from ..doc import HwpxDocument
    from ..doc.xml import P, RUN, top_para
    doc = HwpxDocument.from_bytes(data)
    focus_key = None
    found = False
    for sec_i, root in enumerate(doc.ordered_sections()):
        for p in [p for p in root.iter(P) if p.get(FOCUS_ATTR)]:
            found = True
            del p.attrib[FOCUS_ATTR]
            for run in p.iterfind(RUN):
                run.set("charPrIDRef", doc.charpr_variant(run.get("charPrIDRef", "0"), {"background": FOCUS_FILL}))
            if focus_key is None:
                top = top_para(p)
                if top is not None and top.getparent() is root:
                    focus_key = (sec_i, list(root.iterchildren(P)).index(top))
    return (doc.to_bytes() if found else data), focus_key
