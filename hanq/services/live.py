"""LiveView: 작업이 보낸 문서(hwpx 바이트)를 전용 스레드에서 간이 렌더러로 그린다.

그리는 동안 새 문서가 오면 가장 최근 것만 그린다. 결과는 callback(RenderResult)으로 알린다
(작업 스레드에서 불리므로 UI는 after()로 넘겨 받아야 한다).
"""
import queue
import threading

from ..doc.render import render


class LiveView:
    def __init__(self, callback, dpi: int = 96):
        self._cb = callback
        self._dpi = dpi
        self._q: queue.Queue = queue.Queue()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def submit(self, data: bytes, token=None):
        """token은 그리는 요청을 구분하는 값(예: 작업 번호). 결과와 함께 그대로 돌려준다."""
        self._q.put((data, token))

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
            data, token = job
            try:
                result = render(data, self._dpi)
            except Exception:  # 그리기 실패는 화면만 건너뛴다 (문서 작업에는 영향 없음)
                continue
            self._cb(result, token)
