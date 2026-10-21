import unittest

from hanq.ai.jsonstream import scan
from hanq.ai.jsonutil import JSONError, parse_json

FULL = ('```json\n{"reply": "ok", "slots": {"S1": "2025년 \\"계획\\"", "S2": "1. 첫째\\n2. 둘째", '
        '"S3": "끝"}, "tables": {"T1": [["a", "b"]]}, "blocks": [{"type": "heading", "text": "x"}]}\n```')


class ScanTest(unittest.TestCase):
    def test_prefixes_never_report_wrong_values(self):
        final = parse_json(FULL)
        seen_typing = set()
        for n in range(len(FULL) + 1):
            r = scan(FULL[:n])
            for k, v in r.entries.get("slots", {}).items():
                self.assertEqual(v, final["slots"][k], f"앞 {n}자에서 {k}")
            if r.typing:
                key, lid, partial = r.typing
                self.assertEqual(key, "slots")
                self.assertTrue(final["slots"][lid].startswith(partial), (lid, partial))
                seen_typing.add(lid)
        self.assertEqual(seen_typing, {"S1", "S2", "S3"})
        r = scan(FULL)
        self.assertEqual(r.entries["tables"], {"T1": [["a", "b"]]})
        self.assertEqual(r.items["blocks"], [{"type": "heading", "text": "x"}])
        self.assertEqual(r.scalars["reply"], "ok")

    def test_value_needs_delimiter(self):
        r = scan('{"slots": {"S1": "다 받음"')
        self.assertEqual(r.entries.get("slots"), {})
        self.assertEqual(r.typing, ("slots", "S1", "다 받음"))
        r = scan('{"slots": {"S1": "다 받음",')
        self.assertEqual(r.entries["slots"], {"S1": "다 받음"})

    def test_unescaped_quote_stops_safely(self):
        r = scan('{"slots": {"S1": "그는 "안녕"이라 말함", "S2": "x"}}')
        self.assertNotIn("S1", r.entries.get("slots", {}))

    def test_raw_newline_in_string_is_accepted(self):
        r = scan('{"slots": {"S1": "첫 줄\n둘째 줄", "S2": "x"}}')
        self.assertEqual(r.entries["slots"]["S1"], "첫 줄\n둘째 줄")

    def test_blocks_stream(self):
        text = '{"title": "제목", "blocks": [{"type": "heading", "text": "a"}, {"type": "item", "te'
        r = scan(text, objects=(), arrays=("blocks",))
        self.assertEqual(r.scalars["title"], "제목")
        self.assertEqual(len(r.items["blocks"]), 1)


class ParseTest(unittest.TestCase):
    def test_repair(self):
        self.assertEqual(parse_json('{"a": "그는 "안녕"이라 함",}')["a"], '그는 "안녕"이라 함')
        self.assertEqual(parse_json('설명\n{"a": [1, 2,]}\n끝')["a"], [1, 2])
        with self.assertRaises(JSONError):
            parse_json("JSON 없음")


if __name__ == "__main__":
    unittest.main()
