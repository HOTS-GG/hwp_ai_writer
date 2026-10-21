import tempfile
import unittest
from pathlib import Path

from hanq.doc import DocumentBuilder, EditPlan, Editor, HwpxDocument, Outline
from hanq.doc.render import FOCUS_ATTR, render
from hanq.doc.xml import RUN, T, para_text, set_para_text, t_text

from .helpers import FORMS, PLAN_FORM, REPORT_FORM, body_lines, find_line, split_runs


class OutlineTest(unittest.TestCase):
    def test_every_form_opens_and_lines_are_unique(self):
        for f in FORMS:
            with self.subTest(form=Path(f).name):
                doc = HwpxDocument(str(f))
                for edit in (False, True):
                    o = Outline(doc, edit=edit)
                    self.assertEqual(len(o.lines), len(set(map(id, o.lines.values()))))
                    self.assertTrue(o.text)

    def test_mixed_format_line_is_one_slot(self):
        doc = HwpxDocument(PLAN_FORM)
        p = split_runs(doc, "1. 행사명", 6)
        self.assertEqual(len(p.findall(RUN)), 2)
        o = Outline(doc, edit=True)
        hits = [lid for lid, q in o.lines.items() if q is p]
        self.assertEqual(len(hits), 1, "한 줄은 번호 하나")
        self.assertIn("1. 행사명: ○○○○", o.text)

    def test_fill_mode_marks_placeholders_examples_and_tables(self):
        o = Outline(HwpxDocument(PLAN_FORM))
        self.assertTrue(o.has_placeholders)
        self.assertGreater(o.fill_count, 10)
        self.assertEqual(len(o.tables), 2)
        self.assertTrue(any(k.startswith("E") for k in o.lines))
        self.assertEqual(len(o.headings), 8)


class SetTextTest(unittest.TestCase):
    def test_keeps_matching_marker_run(self):
        doc = HwpxDocument(PLAN_FORM)
        p = split_runs(doc, "1. 행사명", 6)   # ['  1. 행', '사명: ○○○○']
        first = t_text(p.find(f"{RUN}/{T}"))
        set_para_text(p, first + "과학 축전")
        self.assertEqual([t_text(t) for t in p.iter(T)], [first, "과학 축전"])
        set_para_text(p, "전혀 다른 줄")
        self.assertEqual(para_text(p), "전혀 다른 줄")


class EditorTest(unittest.TestCase):
    def setUp(self):
        self.doc = HwpxDocument(PLAN_FORM)
        self.o = Outline(self.doc)
        self.ed = Editor(self.doc, self.o)

    def test_fill_multi_line_and_refill_does_not_duplicate(self):
        lid = find_line(self.o, "1. 행사명")
        self.ed.fill_line(lid, "  1. 행사명: 축전\n  2. 일시: 5. 23.")
        self.assertEqual(sum("2. 일시: 5. 23." in s for s in body_lines(self.doc)), 1)
        # 받는 중 값 → 최종 값이 다르면 다시 넣는다 (앞서 붙인 줄은 걷어냄)
        self.ed.fill_line(lid, "  1. 행사명: 과학 축전\n  2. 일시: 5. 24.")
        lines = body_lines(self.doc)
        self.assertEqual(sum("2. 일시: 5. 23." in s for s in lines), 0)
        self.assertEqual(sum("2. 일시: 5. 24." in s for s in lines), 1)

    def test_empty_value_removes_line(self):
        lid = find_line(self.o, "3. 장소")
        self.ed.fill_line(lid, "")
        self.assertFalse(any("3. 장소" in s for s in body_lines(self.doc)))

    def test_table_rows_grow(self):
        tid = next(iter(self.o.tables))
        rows = [[f"{h}:00", "활동", "강당", ""] for h in range(9, 15)]
        self.ed.fill_table(tid, rows)
        self.assertEqual(len(self.o.tables[tid].trs), 6)
        self.assertIn("14:00", self.doc.plain_text())

    def test_apply_reports_dropped_and_counts(self):
        lid = find_line(self.o, "1. 행사명")
        plan = EditPlan.from_ai({"slots": {lid: "  1. 행사명: 축전", "S9999": "x"},
                                 "new_sections": [{"title": "홍보 계획", "lines": ["1. 누리집 게시"]}],
                                 "deletes": ["H9999"]}, self.o)
        rep = self.ed.apply(plan)
        self.assertEqual(rep.lines, 1)
        self.assertEqual(rep.sections, 1)
        self.assertTrue(any("S9999" in m and "H9999" in m for m in rep.missed))
        self.assertIn("홍보 계획", self.doc.plain_text())

    def test_type_line_is_temporary(self):
        lid = find_line(self.o, "3. 장소")
        self.ed.type_line(lid, "  3. 장소: 체")
        self.assertIn("3. 장소: 체", self.doc.plain_text())
        self.ed.fill_line(lid, "  3. 장소: 체육관")
        self.ed.type_line(lid, "무시됨")
        self.assertIn("3. 장소: 체육관", self.doc.plain_text())


class EditModeTest(unittest.TestCase):
    def setUp(self):
        self.doc = HwpxDocument(REPORT_FORM)
        self.o = Outline(self.doc, edit=True)
        self.ed = Editor(self.doc, self.o)

    def test_delete_line_by_s_number(self):
        lid = next(k for k, p in self.o.lines.items()
                   if para_text(p).strip() and p.getparent().getparent() is None and "○" in para_text(p))
        text = para_text(self.o.lines[lid])
        rep = self.ed.apply(EditPlan.from_ai({"deletes": [lid]}, self.o))
        self.assertEqual(rep.deleted, 1)
        self.assertNotIn(text, body_lines(self.doc))

    def test_delete_heading_and_renumber(self):
        heads = list(self.o.headings)
        rep = self.ed.apply(EditPlan.from_ai({"deletes": [heads[0]]}, self.o))
        self.assertEqual(rep.deleted, 1)
        nums = [h[1][1] for h in self.ed._all_headings()]
        from hanq.doc.xml import cell_text
        self.assertEqual(cell_text(nums[0]).strip(), "1")

    def test_replace_all_across_runs(self):
        p = split_runs(self.doc, next(s.strip()[:4] for s in body_lines(self.doc) if len(s.strip()) > 8), 3)
        whole = para_text(p)
        rep = self.ed.apply(EditPlan.from_ai({"replace_all": [{"find": whole.strip()[1:6], "replace": "★"}]}, self.o))
        self.assertGreaterEqual(rep.replaced, 1)
        self.assertIn("★", para_text(p))

    def test_style_whole_line_and_unchanged_detection(self):
        lid = next(k for k, p in self.o.lines.items() if para_text(p).strip())
        before = self.doc.snapshot()
        rep = self.ed.apply(EditPlan.from_ai({"styles": [{"target": lid, "bold": True, "color": "빨강"}]}, self.o))
        self.assertEqual(rep.styled, 1)
        self.assertNotEqual(before, self.doc.snapshot())


class SaveBuildRenderTest(unittest.TestCase):
    def test_save_reopen(self):
        doc = HwpxDocument(PLAN_FORM)
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "a.hwpx"
            doc.save(str(out))
            again = HwpxDocument(str(out))
            self.assertEqual(again.plain_text(), doc.plain_text())
            self.assertEqual(HwpxDocument.from_bytes(doc.to_bytes()).plain_text(), doc.plain_text())

    def test_builder(self):
        spec = {"title": "테스트 계획", "department": "과학정보부", "date": "2025. 3.",
                "blocks": [{"type": "heading", "text": "목적"}, {"type": "item", "text": "1. 가나다"},
                           {"type": "table", "columns": ["a", "b", "c"], "rows": [["1", "2", "3"]]},
                           {"type": "heading", "text": "운영"}, {"type": "note", "text": "변경 가능"}],
                "attachment": "동의서 1부"}
        doc = DocumentBuilder(PLAN_FORM).build(spec)
        text = doc.plain_text()
        for s in ("테스트 계획", "-과학정보부-", "1. 가나다", "※ 변경 가능", "붙임  동의서 1부.  끝."):
            self.assertIn(s, text)
        self.assertEqual(len(Outline(doc).headings), 2)

    def test_render_focus(self):
        doc = HwpxDocument(PLAN_FORM)
        o = Outline(doc)
        p = o.lines[find_line(o, "1. 행사명")]
        p.set(FOCUS_ATTR, "1")
        r = render(doc.to_bytes())
        self.assertGreaterEqual(len(r.pages), 2)
        self.assertEqual(r.focus_page, 1)
        self.assertIsNotNone(r.focus_y)


if __name__ == "__main__":
    unittest.main()
