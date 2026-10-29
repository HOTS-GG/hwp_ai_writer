"""AI 오류를 쉬운 말로 바꾸는 규칙."""
import unittest

from hanq.ai.explain import explain


class ExplainTest(unittest.TestCase):
    def fix(self, msg):
        h = explain(msg)
        return h.fix if h else None

    def test_cases(self):
        cases = {
            "[401] invalid x-api-key": "key",
            "[400] API key not valid. Please pass a valid API key.": "key",
            "API 키가 없습니다. 설정 탭에서 입력해주세요.": "connect",
            "Claude Code 오류: Invalid API key · Please run /login": "key",
            "Codex: Not logged in": "login",
            "Claude Code를 찾을 수 없습니다.": "login",
            "[400] Your credit balance is too low": "connect",
            "[429] rate_limit_error": "",
            "[529] Overloaded": "model",
            "[404] model: claude-x not found": "model",
            "JSON 끝남\n\n응답이 중간에 잘렸을 수 있습니다.": "tokens",
            "응답 대기 시간(600초)을 넘었습니다.": "tokens",
            "AI 서버에 연결하지 못했습니다: ConnectionError": "",
        }
        for msg, want in cases.items():
            self.assertEqual(self.fix(msg), want, msg)

    def test_unknown_keeps_original(self):
        self.assertIsNone(explain("뭔가 이상한 일"))


if __name__ == "__main__":
    unittest.main()
