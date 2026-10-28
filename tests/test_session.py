"""작업 기록: 버전·대화 저장, 쓰는 도중 저장(중간에 꺼져도 살리기), 보관 기간 정리."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hanq.ai import AIConfig, Cancelled
from hanq.doc import HwpxDocument
from hanq.doc.render import FOCUS_ATTR
from hanq.services import Job, fill_form
from hanq.services import stream as stream_mod
from hanq.session import DONE, GENERATING, INTERRUPTED, SessionStore

from .helpers import PLAN_FORM
from .test_services import fake_complete


class SessionStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = SessionStore(Path(self.tmp.name) / "sessions")

    def test_versions_chat_and_reload(self):
        s = self.store.new("과학 축전 계획", form="[기본] 행사 계획서", request="축전")
        v1 = s.add_version(PLAN_FORM)
        v2 = s.add_version(PLAN_FORM)
        s.add_chat("me", "장소 바꿔줘")
        s.set_history([("user", "장소 바꿔줘"), ("ai", "바꿨습니다")])
        self.assertNotEqual(v1, v2)
        again = self.store.load(s.id)
        self.assertEqual(again.version_paths(), [v1, v2])
        self.assertEqual(again.data["chat"], [["me", "장소 바꿔줘"]])
        self.assertEqual(again.data["request"], "축전")
        again.pop_version()
        self.assertEqual(self.store.load(s.id).version_paths(), [v1])

    def test_draft_only_session_is_listed_as_interrupted(self):
        s = self.store.new("작성 중", status=GENERATING)
        self.assertEqual(self.store.list(), [])            # 아무것도 없으면 목록에 없음
        s.set_draft(Path(PLAN_FORM).read_bytes(), force=True)
        listed = self.store.list()
        self.assertEqual([x.id for x in listed], [s.id])
        self.assertEqual(listed[0].status, INTERRUPTED)    # 'generating'으로 남았다 = 중간에 꺼짐
        self.assertIn("작성 도중 멈춤", listed[0].describe())
        listed[0].add_version(listed[0].draft_path())
        self.assertEqual(self.store.load(s.id).status, DONE)
        self.assertIsNone(self.store.load(s.id).draft_path())

    def test_cleanup_removes_old_and_empty(self):
        old = self.store.new("오래된 것")
        old.add_version(PLAN_FORM)
        data = json.loads((old.dir / "session.json").read_text(encoding="utf-8"))
        data["updated"] = "2000-01-01T00:00:00"
        (old.dir / "session.json").write_text(json.dumps(data), encoding="utf-8")
        empty = self.store.new("빈 것")
        keep = self.store.new("최근 것")
        keep.add_version(PLAN_FORM)
        self.store.cleanup(keep_days=7)
        self.assertFalse(old.dir.exists())
        self.assertFalse(empty.dir.exists())
        self.assertEqual([s.id for s in self.store.list()], [keep.id])

    def test_inputs(self):
        self.store.save_inputs({"form": "자유 작성", "request": "축전 계획", "refs": []})
        self.assertEqual(self.store.load_inputs()["request"], "축전 계획")


class DraftTest(unittest.TestCase):
    def test_draft_is_clean_and_survives_stop(self):
        """AI가 쓰는 도중에 멈춰도, 그때까지 채운 줄이 든 문서가 저장된다 (강조 표시는 없이)."""
        stream_mod.LineStreamer.SCAN_INTERVAL = 0
        answer = json.dumps({"slots": {"S1": "2025년 과학 탐구 축전 운영 계획", "S2": "-과학정보부-",
                                       "S3": "2025. 5.", "S4": "2025년 과학 탐구 축전 운영 계획"}},
                            ensure_ascii=False) + " " * 400
        drafts = []
        job = Job(on_draft=drafts.append, draft_interval=0)
        self.assertTrue(job.live)
        out = str(Path(tempfile.mkdtemp()) / "out.hwpx")
        with mock.patch.object(stream_mod, "complete", fake_complete(answer, chunk=5, stop_after=len(answer) - 50)):
            with self.assertRaises(Cancelled):
                fill_form(job, PLAN_FORM, out, "", [], {}, AIConfig(provider="claude", api_key="t", model="t"))
        self.assertFalse(Path(out).exists())       # 결과 파일은 없지만
        self.assertTrue(drafts)                     # 쓰던 문서는 남았다
        last = drafts[-1]
        self.assertIn("과학 탐구 축전", HwpxDocument.from_bytes(last).plain_text())
        self.assertNotIn(FOCUS_ATTR.encode(), last)


if __name__ == "__main__":
    unittest.main()
