"""가짜 AI로 생성·수정 흐름 전체를 돌려 본다 (실제 AI 호출 없음).

가짜 AI는 응답을 몇 글자씩 나눠 on_text로 흘려보내, 실시간 반영(화면 프레임)도 함께 확인한다.
"""
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from hanq.ai import AIConfig, Cancelled
from hanq.doc import HwpxDocument, Outline
from hanq.doc.render import FOCUS_ATTR
from hanq.doc.xml import para_text
from hanq.services import Job, build_document, edit_document, fill_form
from hanq.services import stream as stream_mod

from .helpers import PLAN_FORM, REPORT_FORM, find_line


def fake_complete(answer: str, chunk: int = 7, stop_after: int | None = None):
    def complete(cfg, system, user, images=None, on_text=None, on_progress=None, stop=None, on_note=None):
        complete.user = user
        for i in range(chunk, len(answer) + chunk, chunk):
            if stop is not None and stop.is_set():
                raise Cancelled()
            if stop_after is not None and i > stop_after:
                stop.set()
            if on_text:
                on_text(answer[:i])
        return answer
    return complete


def focused(doc) -> list:
    return [p for root in doc.ordered_sections() for p in root.iter() if p.get(FOCUS_ATTR)]


class Recorder:
    def __init__(self):
        self.frames: list[bytes] = []
        self.status: list[str] = []

    def job(self) -> Job:
        return Job(on_status=self.status.append, on_frame=self.frames.append, frame_interval=0)


AI = AIConfig(provider="claude", api_key="test", model="test")


class FillFormTest(unittest.TestCase):
    def setUp(self):
        stream_mod.LineStreamer.SCAN_INTERVAL = 0
        self.tmp = tempfile.TemporaryDirectory()
        self.out = str(Path(self.tmp.name) / "out.hwpx")
        o = Outline(HwpxDocument(PLAN_FORM))
        self.l_name = find_line(o, "1. 행사명")
        self.l_place = find_line(o, "3. 장소")
        self.answer = json.dumps({
            "slots": {self.l_name: "  1. 행사명: 2025 과학 탐구 축전",
                      self.l_place: "  3. 장소: 본교 체육관\n  4. 보조 장소: 과학실"},
            "tables": {"T1": [["09:00~10:00", "개회식", "강당", ""], ["10:00~12:00", "부스 운영", "체육관", ""]]},
        }, ensure_ascii=False)

    def tearDown(self):
        self.tmp.cleanup()

    def test_streams_frames_and_saves(self):
        rec = Recorder()
        with mock.patch.object(stream_mod, "complete", fake_complete(self.answer)):
            res = fill_form(rec.job(), PLAN_FORM, self.out, "축전 계획", [], {}, AI)
        text = HwpxDocument(self.out).plain_text()
        self.assertIn("2025 과학 탐구 축전", text)
        self.assertEqual(text.count("4. 보조 장소: 과학실"), 1)
        self.assertIn("부스 운영", text)
        self.assertEqual(res.report.lines, 2)
        self.assertEqual(res.report.tables, 1)
        # 처음 양식 + 받는 중 여러 장 + 마지막
        self.assertGreater(len(rec.frames), 5)
        typed = [f for f in rec.frames if focused(HwpxDocument.from_bytes(f))]
        self.assertTrue(typed, "받는 중인 줄은 강조 표시가 붙은 화면으로 와야 함")
        self.assertFalse(focused(HwpxDocument(self.out)), "저장 파일에는 강조 표시가 없어야 함")
        # 받는 중 화면에 쓰던 글자(앞부분)가 보였는지
        partials = [HwpxDocument.from_bytes(f).plain_text() for f in rec.frames[1:-1]]
        self.assertTrue(any("1. 행사명: 2025" in t and "과학 탐구 축전" not in t for t in partials))

    def test_codex_like_replay(self):
        rec = Recorder()
        ai = AIConfig(provider="codex", api_key="x", model="")
        with mock.patch.object(stream_mod, "complete", fake_complete(self.answer)), \
                mock.patch.object(stream_mod.time, "sleep", lambda s: None):
            fill_form(rec.job(), PLAN_FORM, self.out, "", [], {}, ai)
        self.assertGreaterEqual(len(rec.frames), 4)
        self.assertIn("본교 체육관", HwpxDocument(self.out).plain_text())

    def test_stop(self):
        rec = Recorder()
        with mock.patch.object(stream_mod, "complete", fake_complete(self.answer, stop_after=40)):
            with self.assertRaises(Cancelled):
                fill_form(rec.job(), PLAN_FORM, self.out, "", [], {}, AI)
        self.assertFalse(Path(self.out).exists())

    def test_references_reach_prompt(self):
        rec = Recorder()
        ref = Path(self.tmp.name) / "공문.txt"
        ref.write_text("행사 장소는 시청각실임", encoding="utf-8")
        fake = fake_complete(self.answer)
        with mock.patch.object(stream_mod, "complete", fake):
            fill_form(rec.job(), PLAN_FORM, self.out, "", [str(ref)], {"school_name": "한큐고"}, AI)
        self.assertIn("## 참고 자료: 공문.txt", fake.user)
        self.assertIn("시청각실", fake.user)
        self.assertIn("한큐고", fake.user)


class BuildTest(unittest.TestCase):
    def test_blocks_appear_one_by_one(self):
        from hanq.services import generate as gen_mod
        gen_mod._LiveBuilder.SCAN_INTERVAL = 0
        spec = {"title": "독서 주간 운영 계획", "department": "국어과", "date": "2025. 4.",
                "blocks": [{"type": "heading", "text": "목적"}, {"type": "item", "text": "1. 독서 습관 형성"},
                           {"type": "heading", "text": "일정"},
                           {"type": "table", "columns": ["날짜", "내용"], "rows": [["4. 1.", "개막"]]}],
                "attachment": ""}
        rec = Recorder()
        with tempfile.TemporaryDirectory() as d:
            out = str(Path(d) / "b.hwpx")
            with mock.patch.object(stream_mod, "complete", fake_complete(json.dumps(spec, ensure_ascii=False), 5)):
                res = build_document(rec.job(), PLAN_FORM, out, "독서 주간", [], {}, AI)
            text = HwpxDocument(out).plain_text()
        self.assertEqual(res.title, "독서 주간 운영 계획")
        self.assertIn("1. 독서 습관 형성", text)
        counts = [HwpxDocument.from_bytes(f).plain_text().count("독서 습관") for f in rec.frames]
        self.assertEqual(counts[0], 0)
        self.assertEqual(counts[-1], 1)


class EditTest(unittest.TestCase):
    def test_delete_and_unchanged_warning(self):
        doc = HwpxDocument(REPORT_FORM)
        o = Outline(doc, edit=True)
        lid = next(k for k, p in o.lines.items() if "○" in "".join(p.itertext()) and p.getparent().getparent() is None)
        with tempfile.TemporaryDirectory() as d:
            out = str(Path(d) / "e.hwpx")
            answer = json.dumps({"reply": "지웠습니다.", "deletes": [lid]}, ensure_ascii=False)
            with mock.patch.object(stream_mod, "complete", fake_complete(answer)):
                res = edit_document(Recorder().job(), REPORT_FORM, out, "지워줘", [], AI)
            self.assertEqual(res.changed, 1)
            self.assertTrue(Path(out).exists())
            # 같은 글자를 그대로 돌려주면 '바뀌지 않음' 경고
            same = "".join(o.lines[lid].itertext())
            answer = json.dumps({"reply": "고쳤습니다.", "slots": {lid: same}}, ensure_ascii=False)
            out2 = str(Path(d) / "e2.hwpx")
            with mock.patch.object(stream_mod, "complete", fake_complete(answer)):
                res = edit_document(Recorder().job(), REPORT_FORM, out2, "고쳐줘", [], AI)
            self.assertEqual(res.changed, 0)
            self.assertIn("바뀌지 않았습니다", res.warning)
            self.assertFalse(Path(out2).exists())


class JobTest(unittest.TestCase):
    def test_frame_throttle(self):
        frames = []
        job = Job(on_frame=frames.append, frame_interval=10)
        doc = HwpxDocument(PLAN_FORM)
        job.frame(doc)
        job.frame(doc)
        self.assertEqual(len(frames), 1)
        job.frame(doc, force=True)
        self.assertEqual(len(frames), 2)
        time.sleep(0)


if __name__ == "__main__":
    unittest.main()


class HangulLiveTest(unittest.TestCase):
    """한글을 쓸 수 있으면(접근 허용됨) 실시간 화면을 한글이 그리고, 못 쓰면 다른 엔진으로 넘어간다."""

    class FakeHangul:
        def __init__(self, ready, pages):
            self.ready, self.stuck, self.pages, self.calls = ready, False, pages, []

        def render_frame(self, data, dpi, focus_key=None, timeout=20.0):
            self.calls.append(focus_key)
            return (self.pages, 1) if self.pages else None

    def _frame_bytes(self):
        doc = HwpxDocument(PLAN_FORM)
        o = Outline(doc)
        o.lines[find_line(o, "1. 행사명")].set(FOCUS_ATTR, "1")
        return doc.to_bytes()

    def test_uses_hangul_when_ready(self):
        from PIL import Image
        from hanq.services.live import LiveView
        with tempfile.TemporaryDirectory() as d:
            png = str(Path(d) / "p.png")
            Image.new("RGB", (10, 10), "white").save(png)
            fake = self.FakeHangul(True, [png, png])
            live = LiveView(lambda r, t: None, hangul=fake)
            res = live._render("bytes", self._frame_bytes())
            live.close()
        self.assertEqual(len(res.pages), 2)
        self.assertEqual(res.focus_page, 1)
        self.assertIsNotNone(fake.calls[0], "강조 줄 위치를 한글에 넘겨야 함")

    def test_falls_back_when_not_ready_or_failed(self):
        from hanq.services.live import LiveView
        for fake in (self.FakeHangul(False, ["x"]), self.FakeHangul(True, [])):
            live = LiveView(lambda r, t: None, hangul=fake)
            res = live._render("bytes", self._frame_bytes())
            live.close()
            self.assertGreaterEqual(len(res.pages), 2)


class ReviewRegressionTest(unittest.TestCase):
    def test_replay_skips_wait_without_preview(self):
        """미리보기를 끈 채 자동 저장(on_draft)만 켜져 있으면 replay가 기다리지 않는다."""
        from hanq.doc import Editor
        doc = HwpxDocument(str(PLAN_FORM))
        outline = Outline(doc)
        job = Job(on_draft=lambda b: None)
        s = stream_mod.LineStreamer(Editor(doc, outline), job)
        slots = {lid: "x" for lid in list(outline.lines)[:30]}
        t = time.monotonic()
        s.replay({"slots": slots})
        self.assertLess(time.monotonic() - t, 0.5)

    def test_prune_cache_removes_only_old(self):
        import os
        from hanq.ui import app as app_mod
        with tempfile.TemporaryDirectory() as d:
            old, new = Path(d) / "old", Path(d) / "new.txt"
            old.mkdir(); (old / "a.png").write_bytes(b"1"); new.write_text("n")
            os.utime(old, (0, 0))
            with mock.patch.object(app_mod, "CACHE_DIR", Path(d)):
                app_mod._prune_cache()
            self.assertFalse(old.exists())
            self.assertTrue(new.exists())


class GongmunFormTest(unittest.TestCase):
    def test_gongmun_form_fixed_parts(self):
        """공문 양식: 수신·제목·본문만 채우고, 학교 이름·발신명의·기안자/시행 줄은 고정."""
        o = Outline(HwpxDocument(str(Path(__file__).parent.parent / "forms" / "07_공문(기안문).hwpx")))
        filled = " ".join(para_text(p) for p in o.lines.values())
        self.assertIn("수신", filled)
        self.assertIn("붙임", filled)
        for fixed in ("춘 천 고 등 학 교", "춘천고등학교장", "기안자", "시행"):
            self.assertNotIn(fixed, filled)
        self.assertNotIn("(예시문) 춘천고등학교장 귀하",
                         Outline(HwpxDocument(str(Path(__file__).parent.parent / "forms" / "05_관리계획·규정형 문서.hwpx"))).text)
