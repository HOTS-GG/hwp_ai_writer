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
    """

    def __init__(self, on_status=None, on_frame=None, frame_interval: float = 0.25):
        self.on_status = on_status
        self.on_frame = on_frame
        self.frame_interval = frame_interval
        self.stop = threading.Event()
        self._last_frame = 0.0

    def status(self, msg: str):
        if self.on_status:
            self.on_status(msg)

    def check(self):
        if self.stop.is_set():
            raise Cancelled()

    @property
    def live(self) -> bool:
        return self.on_frame is not None

    def frame(self, doc, focus=(), force: bool = False):
        """문서의 지금 모습을 화면에 보낸다. focus 줄(hp:p)은 노랗게 강조한다. 너무 잦으면 건너뛴다."""
        if self.on_frame is None:
            return
        now = time.monotonic()
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
