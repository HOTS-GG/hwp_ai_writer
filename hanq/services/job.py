"""작업 하나(생성·수정)의 상태 알림·실시간 화면·중단을 한데 묶는다. UI 없이도 쓸 수 있다."""
import threading
import time

from ..ai import Cancelled
from ..doc.render import FOCUS_ATTR


class Job:
    """
    on_status(msg)       상태 줄에 보일 글
    on_frame(bytes)      실시간 화면용 문서(hwpx 바이트, 방금 쓴 줄에 강조 표시가 붙어 있음)
    frame_interval       화면을 다시 그리는 최소 간격(초)
    on_draft(bytes)      쓰는 도중의 문서(강조 표시 없음) — 중간에 꺼져도 살리기 위한 저장용
    draft_interval       on_draft를 부르는 최소 간격(초)
    """

    def __init__(self, on_status=None, on_frame=None, frame_interval: float = 0.25,
                 on_draft=None, draft_interval: float = 3.0):
        self.on_status = on_status
        self.on_frame = on_frame
        self.frame_interval = frame_interval
        self.on_draft = on_draft
        self.draft_interval = draft_interval
        self.stop = threading.Event()
        self._last_frame = 0.0
        self._last_draft = 0.0

    def status(self, msg: str):
        if self.on_status:
            self.on_status(msg)

    def check(self):
        if self.stop.is_set():
            raise Cancelled()

    @property
    def live(self) -> bool:
        """받는 대로 문서에 반영할지 (화면에 보이거나, 쓰는 도중의 문서를 저장할 때)."""
        return self.on_frame is not None or self.on_draft is not None

    @property
    def visible(self) -> bool:
        """실시간 화면이 있는지. 한 줄씩 보여 주는 연출(기다림)은 화면이 있을 때만 한다."""
        return self.on_frame is not None

    def frame(self, doc, focus=(), force: bool = False):
        """문서의 지금 모습을 화면에 보낸다. focus 줄(hp:p)은 노랗게 강조한다. 너무 잦으면 건너뛴다."""
        now = time.monotonic()
        if self.on_draft is not None and (force or now - self._last_draft >= self.draft_interval):
            self._last_draft = now
            try:
                self.on_draft(doc.to_bytes())
            except Exception:
                pass   # 저장 실패가 작성을 멈추게 하지 않는다
        if self.on_frame is None:
            return
        if not force and now - self._last_frame < self.frame_interval:
            return
        self._last_frame = now
        marked = [p for p in focus if p is not None and p.getparent() is not None]
        for p in marked:
            p.set(FOCUS_ATTR, "1")
        try:
            data = doc.to_bytes()
        finally:
            for p in marked:
                p.attrib.pop(FOCUS_ATTR, None)
        self.on_frame(data)
