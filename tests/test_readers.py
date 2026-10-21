import os
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path

from hanq.readers import read_reference
from hanq.readers.hwp import _BodyParser, decode_para_text, parse_records
from hanq.services.context import build_context, read_references

from .helpers import PLAN_FORM

# 범정부오피스 양식 같은 실제 HWP 파일이 있으면 그것으로도 확인한다 (저장소에는 넣지 않음)
LOCAL_HWP_DIR = os.environ.get("HANQ_HWP_SAMPLES", r"C:\Users\Administrator\hwp_ai_writer\templates")


def _rec(tag, level, data=b""):
    return struct.pack("<I", tag | (level << 10) | (len(data) << 20)) + data


def _text(s):
    return (s + "\r").encode("utf-16-le")


class HwpRecordTest(unittest.TestCase):
    def test_inline_controls_are_skipped(self):
        # 탭(9)은 8글자 컨트롤, 그 뒤 글자는 살아 있어야 한다
        data = "가".encode("utf-16-le") + struct.pack("<H", 9) + b"\x00" * 14 + "나".encode("utf-16-le")
        self.assertEqual(decode_para_text(data), "가\t나")
        # 확장 한자(서로게이트 쌍)
        self.assertEqual(decode_para_text("𠀀".encode("utf-16-le")), "𠀀")

    def test_table_rows(self):
        # LIST_HEADER: 문단 수(2) 속성(4) ?(2) 열(2)@8 행(2)@10 합치기(2,2)
        cell = lambda col, row: struct.pack("<hIHHHHH", 1, 0, 0, col, row, 1, 1)  # noqa: E731
        raw = b"".join([
            _rec(66, 0), _rec(67, 1, _text("앞 줄")),
            _rec(71, 1, b" lbt"), _rec(77, 2, b"\x00" * 8),
            _rec(72, 2, cell(0, 0)), _rec(66, 2), _rec(67, 3, _text("구분")),
            _rec(72, 2, cell(1, 0)), _rec(66, 2), _rec(67, 3, _text("내용")),
            _rec(72, 2, cell(0, 1)), _rec(66, 2), _rec(67, 3, _text("일시")),
            _rec(72, 2, cell(1, 1)), _rec(66, 2), _rec(67, 3, _text("5. 23.")),
            _rec(66, 0), _rec(67, 1, _text("뒤 줄")),
        ])
        lines = _BodyParser(parse_records(raw)).paragraphs(0)
        self.assertEqual(lines, ["앞 줄", "| 구분 | 내용 |", "| 일시 | 5. 23. |", "뒤 줄"])

    @unittest.skipUnless(Path(LOCAL_HWP_DIR).is_dir() and any(Path(LOCAL_HWP_DIR).glob("*.hwp")),
                         "로컬 HWP 예제 없음")
    def test_local_hwp_files(self):
        for f in sorted(Path(LOCAL_HWP_DIR).glob("*.hwp")):
            with self.subTest(f=f.name):
                text = read_reference(str(f))
                self.assertIsInstance(text, str)
        self.assertIn("| 보도일시 |", read_reference(str(Path(LOCAL_HWP_DIR) / "경기보도자료.hwp")))


class OtherFormatsTest(unittest.TestCase):
    def test_hwpx_keeps_tables(self):
        text = read_reference(PLAN_FORM)
        self.assertIn("| 시 간 | 내 용 | 장 소 | 비 고 |", text)
        self.assertIn("추진 목적", text)

    def test_docx_and_text(self):
        with tempfile.TemporaryDirectory() as d:
            docx = Path(d) / "a.docx"
            w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
            body = (f'<w:document xmlns:w="{w}"><w:body><w:p><w:r><w:t>제목</w:t></w:r></w:p>'
                    "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>가</w:t></w:r></w:p></w:tc>"
                    "<w:tc><w:p><w:r><w:t>나</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>")
            with zipfile.ZipFile(docx, "w") as z:
                z.writestr("word/document.xml", body)
            self.assertEqual(read_reference(str(docx)), "제목\n| 가 | 나 |")
            txt = Path(d) / "b.txt"
            txt.write_bytes("한글 cp949".encode("cp949"))
            self.assertEqual(read_reference(str(txt)), "한글 cp949")
            # .hwp 이름이지만 실제로는 HWPX(zip)인 파일도 내용으로 판단
            fake = Path(d) / "c.hwp"
            fake.write_bytes(Path(PLAN_FORM).read_bytes())
            self.assertIn("추진 목적", read_reference(str(fake)))


class ContextTest(unittest.TestCase):
    def test_budget_is_shared(self):
        with tempfile.TemporaryDirectory() as d:
            big = Path(d) / "big.txt"
            small = Path(d) / "small.txt"
            big2 = Path(d) / "big2.txt"
            big.write_text("가" * 5000, encoding="utf-8")
            small.write_text("작은 자료", encoding="utf-8")
            big2.write_text("나" * 5000, encoding="utf-8")
            out = dict(read_references([str(big), str(small), str(big2)], 3000))
            self.assertEqual(out["small.txt"], "작은 자료")
            self.assertGreater(out["big2.txt"].count("나"), 1000, "뒤 자료도 몫을 받아야 함")
            self.assertLess(out["big.txt"].count("가"), 1500)
            ctx = build_context("요청", [str(small), str(Path(d) / "없음.txt")], {}, 1000)
            self.assertIn("## 참고 자료: small.txt", ctx)
            self.assertIn("읽기 실패", ctx)


if __name__ == "__main__":
    unittest.main()
