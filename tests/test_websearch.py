"""웹 검색 연결, 표 안의 표, 출처 정리."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hanq.ai import AIConfig, providers
from hanq.doc import Editor, EditPlan, HwpxDocument, Outline
from hanq.doc.xml import SUBLIST, TBL
from hanq.services.stream import sources_of

FORM = Path(__file__).parent.parent / "forms" / "04_출장·연수 결과 보고서.hwpx"


class _Resp:
    status_code = 200

    def __init__(self, lines):
        self._lines = lines

    def iter_lines(self):
        return iter(self._lines)

    def close(self):
        pass


class WebSearchTest(unittest.TestCase):
    def _post(self, provider, events, web=True):
        cfg = AIConfig(provider, "key", "m", web_search=web)
        with mock.patch.object(providers.requests, "post", return_value=_Resp(events)) as post:
            text = providers.complete(cfg, "SYS", "USER")
        return post.call_args, text

    def test_claude_tool_and_rule(self):
        args, text = self._post("claude", [b'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"{}"}}'])
        body = args.kwargs["json"]
        self.assertEqual(body["tools"][0]["name"], "web_search")
        self.assertIn("이미지·영상", body["system"])
        self.assertEqual(text, "{}")

    def test_no_search_when_off(self):
        args, _ = self._post("claude", [b'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"{}"}}'],
                             web=False)
        self.assertNotIn("tools", args.kwargs["json"])
        self.assertNotIn("웹 검색", args.kwargs["json"]["system"])

    def test_openai_uses_responses(self):
        args, text = self._post("openai", [b'data: {"type":"response.output_text.delta","delta":"{}"}'])
        self.assertTrue(args.args[0].endswith("/v1/responses"))
        self.assertEqual(args.kwargs["json"]["tools"], [{"type": "web_search"}])
        self.assertEqual(text, "{}")

    def test_gemini_and_openrouter(self):
        args, _ = self._post("gemini", [b'data: {"candidates":[{"content":{"parts":[{"text":"{}"}]}}]}'])
        self.assertIn({"google_search": {}}, args.kwargs["json"]["tools"])
        self.assertNotIn("responseMimeType", args.kwargs["json"]["generationConfig"])
        args, _ = self._post("openrouter", [b'data: {"choices":[{"delta":{"content":"{}"}}]}'])
        self.assertEqual(args.kwargs["json"]["plugins"][0]["id"], "web")

    def test_cli_flags(self):
        seen = {}

        def fake_run(cmd, prompt, timeout, cwd, stream, on_line=None):
            seen["cmd"] = cmd
            if on_line:
                on_line('{"type":"result","result":"{}"}')
            return ""
        with tempfile.TemporaryDirectory() as d, mock.patch.object(providers, "_run_cli", fake_run):
            exe = os.path.join(d, "claude.exe")   # 실제로 있는 파일 (실행하지는 않음)
            open(exe, "wb").close()
            providers.complete(AIConfig("claude_code", exe, "", web_search=True), "S", "U")
            self.assertIn("WebSearch", seen["cmd"])
            providers.complete(AIConfig("claude_code", exe, "", web_search=False), "S", "U")
            self.assertNotIn("WebSearch", seen["cmd"])
            self.assertNotIn("--allowedTools", seen["cmd"])

    def test_sources_of(self):
        got = sources_of({"sources": [{"title": "교육부", "url": "https://moe.go.kr"}, "https://moe.go.kr",
                                      {"title": "가짜", "url": "javascript:x"}, "ftp://x"]})
        self.assertEqual(got, [("교육부", "https://moe.go.kr")])


class NestedTableTest(unittest.TestCase):
    def test_table_inside_cell(self):
        doc = HwpxDocument(str(FORM))
        o = Outline(doc, edit=True)
        lid = next(k for k, p in o.lines.items() if p.getparent().tag == SUBLIST)
        cell_sl = o.lines[lid].getparent()
        before = len(list(cell_sl.iter(TBL)))
        r = Editor(doc, o).apply(EditPlan.from_ai({"inserts": [{"after": lid, "table": {
            "columns": ["시간", "활동"], "rows": [["09:00", "개회"]]}}]}, o))
        self.assertEqual(r.inserted, 1)
        self.assertEqual(len(list(cell_sl.iter(TBL))), before + 1)


if __name__ == "__main__":
    unittest.main()
