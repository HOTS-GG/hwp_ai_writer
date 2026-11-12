"""한글의 글자·문단·표·용지 모양 바꾸기, 표가 없는 문서에 표 넣기, 대화창 링크."""
import unittest
from pathlib import Path

from hanq.doc import Editor, EditPlan, HwpxDocument, Outline
from hanq.doc.xml import CELLSZ, P, RUN, SUBLIST, SZ, TBL, TC, TR, hc, hh, hp, para_text
from hanq.ui.chat import _PAGE_WORDS, split_urls

FORMS = Path(__file__).parent.parent / "forms"
PLAN = FORMS / "01_행사·사업 운영 계획서.hwpx"
GONGMUN = FORMS / "07_공문(기안문).hwpx"


def _open(path):
    doc = HwpxDocument(str(path))
    o = Outline(doc, edit=True)
    return doc, o, Editor(doc, o)


def _item(doc, list_tag, item_tag, item_id):
    return next(e for e in doc.header_root().find(f".//{hh(list_tag)}") if e.tag == hh(item_tag)
                and e.get("id") == item_id)


class FormatTest(unittest.TestCase):
    def setUp(self):
        self.doc, self.o, self.ed = _open(PLAN)
        self.body = [k for k, p in self.o.lines.items() if p.getparent().tag != SUBLIST and para_text(p).strip()]

    def _apply(self, data):
        return self.ed.apply(EditPlan.from_ai(data, self.o))

    def test_char_shape(self):
        lid = self.body[0]
        r = self._apply({"styles": [{"target": lid, "font": "맑은 고딕", "spacing": -10, "ratio": 90,
                                     "strike": True, "superscript": True}]})
        self.assertEqual((r.styled, r.missed), (1, []))
        cp = _item(self.doc, "charProperties", "charPr", self.o.lines[lid].find(RUN).get("charPrIDRef"))
        self.assertEqual(cp.find(hh("spacing")).get("hangul"), "-10")
        self.assertEqual(cp.find(hh("ratio")).get("latin"), "90")
        self.assertEqual(cp.find(hh("strikeout")).get("shape"), "SOLID")
        self.assertIsNotNone(cp.find(hh("supscript")))
        fid = cp.find(hh("fontRef")).get("hangul")
        faces = next(f for f in self.doc.header_root().iter(hh("fontface")) if f.get("lang") == "HANGUL")
        self.assertEqual(next(f for f in faces if f.get("id") == fid).get("face"), "맑은 고딕")

    def test_paragraph_shape(self):
        lid = self.body[1]
        r = self._apply({"styles": [{"target": lid, "space_before": 10, "left_margin": "20pt", "indent": -10}]})
        self.assertEqual(r.styled, 1)
        pp = _item(self.doc, "paraProperties", "paraPr", self.o.lines[lid].get("paraPrIDRef"))
        for m in pp.iter(hh("margin")):
            scale = 100 if m.getparent().tag == hp("case") else 200
            self.assertEqual(m.find(hc("prev")).get("value"), str(10 * scale))
            self.assertEqual(m.find(hc("left")).get("value"), str(20 * scale))
            self.assertEqual(m.find(hc("intent")).get("value"), str(-10 * scale))

    def test_whole_document_and_page(self):
        r = self._apply({"styles": [{"target": "all", "line_spacing": 140}], "page": {"margin_left": 15}})
        self.assertEqual((r.styled, r.page), (1, 1))
        margin = self.doc.ordered_sections()[0].find(f".//{hp('pagePr')}/{hp('margin')}")
        self.assertEqual(margin.get("left"), str(int(15 * 7200 / 25.4)))
        cell_p = next(p for p in self.doc.ordered_sections()[0].iter(P) if p.getparent().tag == SUBLIST)
        pp = _item(self.doc, "paraProperties", "paraPr", cell_p.get("paraPrIDRef"))
        self.assertEqual({ls.get("value") for ls in pp.iter(hh("lineSpacing"))}, {"140"})

    def test_table_shape(self):
        bid, tbl = next((k, t) for k, t in self.o.boxes.items() if t.get("colCnt") == "3")
        tid = next(iter(self.o.tables))
        total = int(tbl.find(SZ).get("width"))
        r = self._apply({"styles": [{"target": bid, "col_widths": [50, 25, 25]},
                                    {"target": tid, "cell_background": "#FFF2CC", "row_height": 12},
                                    {"target": bid, "col_widths": [1, 2]}]})   # 열 개수가 다르면 반영하지 않음
        self.assertEqual(r.styled, 2)
        self.assertIn("모양 바꾸기 1건", r.missed)
        widths = [int(tc.find(CELLSZ).get("width")) for tc in tbl.find(TR).iterfind(TC)]
        self.assertEqual(sum(widths), total)
        self.assertAlmostEqual(widths[0] / total, 0.5, places=2)
        tc = self.o.tables[tid].trs[0].find(TC)
        bf = _item(self.doc, "borderFills", "borderFill", tc.get("borderFillIDRef"))
        self.assertEqual(bf.find(f"{hc('fillBrush')}/{hc('winBrush')}").get("faceColor"), "#FFF2CC")
        self.assertEqual(tc.find(CELLSZ).get("height"), str(int(12 * 7200 / 25.4)))

    def test_lines_given_as_one_string(self):
        """AI가 줄 목록 대신 글 하나를 줘도 글자마다 한 줄이 되지 않는다."""
        r = self._apply({"inserts": [{"after": self.body[0], "lines": "새 줄 하나"}]})
        self.assertEqual(r.inserted, 1)


class TableWithoutProtoTest(unittest.TestCase):
    def test_gongmun_gets_plain_table(self):
        """공문처럼 본뜰 표가 없는 문서에도 표가 들어간다."""
        doc, o, ed = _open(GONGMUN)
        self.assertEqual(sum(1 for r in doc.ordered_sections() for _ in r.iter(TBL)), 0)
        lid = next(k for k, p in o.lines.items() if para_text(p).strip())
        r = ed.apply(EditPlan.from_ai({"inserts": [{"after": lid, "table": {
            "columns": ["시간", "활동", "장소"], "rows": [["09:00", "개회", "강당"]]}}]}, o))
        self.assertEqual((r.inserted, r.missed), (1, []))
        tbl = next(t for root in doc.ordered_sections() for t in root.iter(TBL))
        self.assertEqual((tbl.get("rowCnt"), tbl.get("colCnt")), ("2", "3"))
        self.assertEqual(sum(int(tc.find(CELLSZ).get("width")) for tc in tbl.find(TR).iterfind(TC)),
                         doc.text_width())

    def test_bad_table_is_reported(self):
        doc, o, ed = _open(GONGMUN)
        lid = next(iter(o.lines))
        r = ed.apply(EditPlan.from_ai({"inserts": [{"after": lid, "table": {"columns": []}}]}, o))
        self.assertEqual(r.inserted, 0)
        self.assertTrue(r.missed)


class ObjectsTest(unittest.TestCase):
    """칸 합치기·나누기, 각주, 머리말·꼬리말·쪽 번호, 용지 방향·다단, 수식·글상자·차트·그림."""

    def setUp(self):
        self.doc, self.o, self.ed = _open(PLAN)
        self.ed.images = {"icon.png": str(FORMS.parent / "assets" / "icon.png")}
        self.body = [k for k, p in self.o.lines.items() if p.getparent().tag != SUBLIST and para_text(p).strip()]
        self.bid, self.tbl = next((k, t) for k, t in self.o.boxes.items()
                                  if (t.get("rowCnt"), t.get("colCnt")) == ("4", "4"))

    def _apply(self, data):
        return self.ed.apply(EditPlan.from_ai(data, self.o))

    def _reopen(self):
        """저장했다 다시 열어도 온전한 문서인지 (XML·압축 파일)."""
        return HwpxDocument(data=self.doc.to_bytes())

    def test_merge_then_split(self):
        cells = sum(1 for _ in self.tbl.iter(TC))
        total = int(self.tbl.find(SZ).get("width"))
        r = self._apply({"merges": [{"table": self.bid, "from": [2, 1], "to": [3, 2]},
                                    {"table": self.bid, "from": [1, 1], "to": [4, 4]}]})   # 행이 통째로 사라지는 건 거절
        self.assertEqual(r.merged, 1)
        self.assertIn("칸 합치기·나누기 1건", r.missed)
        self.assertEqual(sum(1 for _ in self.tbl.iter(TC)), cells - 3)
        big = self.tbl.findall(TR)[1].find(TC)
        self.assertEqual((big.find(hp("cellSpan")).get("rowSpan"), big.find(hp("cellSpan")).get("colSpan")), ("2", "2"))
        for tr in self.tbl.findall(TR)[:1]:
            self.assertEqual(sum(int(tc.find(CELLSZ).get("width")) for tc in tr.iterfind(TC)), total)

        doc = self._reopen()
        o = Outline(doc, edit=True)
        self.assertIn("2행×2열 합침", o.text)
        r = Editor(doc, o).apply(EditPlan.from_ai({"splits": [{"table": self.bid, "cell": [2, 1]}]}, o))
        self.assertEqual(r.merged, 1)
        tbl = o.boxes[self.bid]
        self.assertEqual(sum(1 for _ in tbl.iter(TC)), cells)
        for tr in tbl.findall(TR):
            self.assertEqual([tc.find(hp("cellAddr")).get("colAddr") for tc in tr.iterfind(TC)], ["0", "1", "2", "3"])
            self.assertEqual(sum(int(tc.find(CELLSZ).get("width")) for tc in tr.iterfind(TC)), total)

    def test_footnote(self):
        lid = self.body[0]
        word = para_text(self.o.lines[lid]).strip().split()[1]
        r = self._apply({"footnotes": [{"target": lid, "text": "근거 자료", "part": word},
                                       {"target": self.body[1], "text": "둘째"}]})
        self.assertEqual(r.footnotes, 2)
        notes = list(self._reopen().ordered_sections()[0].iter(hp("footNote")))
        self.assertEqual([n.get("number") for n in notes], ["1", "2"])
        self.assertIn("근거 자료", "".join(notes[0].itertext()))
        self.assertTrue(para_text(self.o.lines[lid]).strip().endswith(para_text(self.o.lines[lid]).strip()[-3:]))

    def test_page_settings(self):
        before = self.doc.text_width()
        r = self._apply({"page": {"orientation": "landscape", "columns": 2, "page_number": "bottom_right",
                                  "header": "머리말 글", "footer": "꼬리말 글"}})
        self.assertEqual((r.page, r.missed), (1, []))
        sec = self._reopen().ordered_sections()[0]
        self.assertEqual(sec.find(f".//{hp('pagePr')}").get("landscape"), "NARROWLY")
        self.assertEqual(next(sec.iter(hp("colPr"))).get("colCount"), "2")
        self.assertEqual([p.get("pos") for p in sec.iter(hp("pageNum"))], ["BOTTOM_RIGHT"])
        self.assertIn("머리말 글", "".join(next(sec.iter(hp("header"))).itertext()))
        self.assertIn("꼬리말 글", "".join(next(sec.iter(hp("footer"))).itertext()))
        # 본문 폭이 바뀌면 본문의 표도 그 폭에 맞춘다
        self.assertLess(self.doc.text_width(), before)
        self.assertLessEqual(int(self.tbl.find(SZ).get("width")), self.doc.text_width() + 50)
        # 지우기
        self._apply({"page": {"page_number": "none", "header": ""}})
        sec = self.doc.ordered_sections()[0]
        self.assertEqual((len(list(sec.iter(hp("pageNum")))), len(list(sec.iter(hp("header"))))), (0, 0))

    def test_insert_objects(self):
        r = self._apply({"inserts": [
            {"after": self.body[0], "equation": "a over b"},
            {"after": self.body[1], "textbox": {"lines": ["안내", "둘째 줄"]}},
            {"after": self.body[2], "chart": {"type": "pie", "title": "비율", "labels": ["가", "나"], "values": [3, 1]}},
            {"after": self.body[3], "image": "icon.png", "width": 30},
            {"after": self.body[4], "chart": {"type": "bar", "labels": [], "series": []}}]})   # 숫자 없는 차트는 거절
        self.assertEqual(r.inserted, 4)
        self.assertIn("끼워 넣을 줄 1건", r.missed)
        doc = self._reopen()
        sec = doc.ordered_sections()[0]
        self.assertEqual(next(sec.iter(hp("script"))).text, "a over b")
        self.assertIn("둘째 줄", "".join(t for r_ in sec.iter(hp("rect")) for t in r_.itertext()))
        refs = [i.get("binaryItemIDRef") for i in sec.iter(hc("img"))]
        new = [n for n in refs if doc.read_item(f"BinData/{n}.png")]
        self.assertEqual(len(new), 2)   # 차트 그림 + 붙인 그림
        self.assertTrue(all(f'id="{n}"' in doc.read_item("Contents/content.hpf").decode("utf-8") for n in new))

    def test_insert_after_table(self):
        """표(T·B번호)를 기준으로 그 아래에 넣을 수 있다 — AI가 '표 아래에'를 이렇게 쓴다."""
        tid = next(iter(self.o.tables))
        holder = self.o.tables[tid].tbl.getparent().getparent()
        r = self._apply({"inserts": [{"after": tid, "image": "icon.png", "width": 50}]})
        self.assertEqual((r.inserted, r.missed), (1, []))
        self.assertIsNotNone(holder.getnext().find(f"{RUN}/{hp('pic')}"))

    def test_image_needs_attached_file(self):
        """붙인 그림이 없으면 넣지 않고, 여러 장이면 이름이 맞는 것만 넣는다."""
        self.ed.images = {}
        self.assertEqual(self._apply({"inserts": [{"after": self.body[0], "image": "icon.png"}]}).inserted, 0)
        self.ed.images = {"a.png": str(FORMS.parent / "assets" / "icon.png"),
                          "b.png": str(FORMS.parent / "assets" / "icon.png")}
        r = self._apply({"inserts": [{"after": self.body[0], "image": "c.png"}, {"after": self.body[0], "image": "b"}]})
        self.assertEqual(r.inserted, 1)

    def test_resize_picture(self):
        iid, pic = next((k, e) for k, e in self.o.images.items() if e.tag == hp("pic"))
        w0, h0 = (int(pic.find(SZ).get(k)) for k in ("width", "height"))
        r = self._apply({"styles": [{"target": iid, "width": 10}]})
        self.assertEqual(r.styled, 1)
        w, h = (int(pic.find(SZ).get(k)) for k in ("width", "height"))
        self.assertEqual(w, int(10 * 7200 / 25.4))
        self.assertAlmostEqual(w / h, w0 / h0, places=1)


class ChatLinkTest(unittest.TestCase):
    def test_split_urls(self):
        self.assertEqual(split_urls("내용은 https://www.moe.go.kr/view.do?m=1을 참고, https://b.kr/y."),
                         [("내용은 ", False), ("https://www.moe.go.kr/view.do?m=1", True), ("을 참고, ", False),
                          ("https://b.kr/y", True), (".", False)])
        self.assertEqual(split_urls("(https://a.kr/x_(y))")[1], ("https://a.kr/x_(y)", True))

    def test_page_words(self):
        for text, want in (("오른쪽으로 정렬해줘", False), ("아래쪽 줄 지워줘", False), ("2쪽으로 줄여줘", True),
                           ("한 페이지에 들어가게", True), ("분량을 줄여줘", True)):
            self.assertEqual(bool(_PAGE_WORDS.search(text)), want, text)


if __name__ == "__main__":
    unittest.main()
