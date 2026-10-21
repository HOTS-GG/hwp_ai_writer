"""rhwp 실행 파일이 있을 때만: 쪽 그리기, 쪽 위치, HWP→HWPX 변환, 실시간 화면의 강조 위치."""
import tempfile
import unittest
from pathlib import Path

from hanq.doc import HwpxDocument, Outline
from hanq.doc.render import FOCUS_ATTR
from hanq.hwp.rhwp import get_rhwp
from hanq.services.live import LiveView

from .helpers import PLAN_FORM, find_line
from .test_readers import LOCAL_HWP_DIR

RHWP = get_rhwp()


@unittest.skipIf(RHWP is None, "rhwp 없음 (python tools/fetch_rhwp.py)")
class RhwpTest(unittest.TestCase):
    def test_render_and_layout(self):
        with tempfile.TemporaryDirectory() as d:
            pages = RHWP.render_to_dir(PLAN_FORM, Path(d), 96)
            self.assertGreaterEqual(len(pages), 2)
        lay = RHWP.layout(PLAN_FORM)
        self.assertEqual(lay.pages, len(pages))
        counts = [sum(1 for _ in r.iterchildren("{*}p")) for r in HwpxDocument(PLAN_FORM).ordered_sections()]
        pm = lay.para_pages(counts)
        self.assertEqual(len(pm), sum(counts))
        self.assertEqual(pm, sorted(pm))

    def test_live_focus_page(self):
        doc = HwpxDocument(PLAN_FORM)
        o = Outline(doc)
        p = o.lines[find_line(o, "1. 행사명")]
        p.set(FOCUS_ATTR, "1")
        live = LiveView(lambda r, t: None, rhwp=RHWP)
        res = live._render("bytes", doc.to_bytes())
        live.close()
        self.assertGreaterEqual(len(res.pages), 2)
        self.assertIsNotNone(res.focus_page)
        self.assertGreater(res.focus_y, 0)

    @unittest.skipUnless(Path(LOCAL_HWP_DIR).is_dir() and any(Path(LOCAL_HWP_DIR).glob("*.hwp")), "로컬 HWP 예제 없음")
    def test_hwp_to_hwpx(self):
        src = sorted(Path(LOCAL_HWP_DIR).glob("*.hwp"))[0]
        with tempfile.TemporaryDirectory() as d:
            out = RHWP.to_hwpx(str(src), str(Path(d) / "a.hwpx"))
            text = HwpxDocument(out).plain_text()
        self.assertTrue(text.strip())


if __name__ == "__main__":
    unittest.main()
