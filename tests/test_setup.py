"""자동 업데이트, 구독 연결(CLI) 상태 읽기, 보안 모듈 자동 찾기 — 네트워크·레지스트리 없이 시험."""
import hashlib
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from hanq import updater
from hanq.hwp import security


class VersionTest(unittest.TestCase):
    def test_compare(self):
        self.assertTrue(updater.is_newer("1.2.0", "1.1.1"))
        self.assertTrue(updater.is_newer("v1.1.10", "1.1.9"))
        self.assertFalse(updater.is_newer("1.1.1", "1.1.1"))
        self.assertFalse(updater.is_newer("1.0.9", "1.1.0"))

    def test_notes_keep_only_changes(self):
        body = ("## 바뀐 점\n자동 업데이트 추가\n\nCo-Authored-By: X <x@y>\n\n"
                "## 내려받기\n| 윈도우 | a.exe |\n")
        self.assertEqual(updater._clean_notes(body), "자동 업데이트 추가")


class ReleaseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.payload = b"HanQ setup" * 1000
        self.file = Path(self.tmp.name) / "setup.exe"
        self.file.write_bytes(self.payload)
        self.sha = hashlib.sha256(self.payload).hexdigest()

    def _api(self, version="9.0.0"):
        name = updater.asset_name_for(version)
        return {"tag_name": f"v{version}", "html_url": "https://example/releases",
                "body": "## 바뀐 점\n좋아짐\n## 내려받기\n표",
                "assets": [{"name": name, "browser_download_url": self.file.as_uri(),
                            "size": len(self.payload), "digest": f"sha256:{self.sha}"}]}

    def test_check_finds_newer_and_asset(self):
        with mock.patch.object(updater, "_get_json", return_value=self._api()):
            rel = updater.check()
        self.assertEqual(rel.version, "9.0.0")
        self.assertEqual(rel.notes, "좋아짐")
        self.assertEqual(rel.sha256, self.sha)

    def test_check_none_when_same(self):
        with mock.patch.object(updater, "_get_json", return_value=self._api(updater.APP_VERSION)):
            self.assertIsNone(updater.check())

    def test_download_verifies_hash(self):
        with mock.patch.object(updater, "_get_json", return_value=self._api()), \
                mock.patch.object(updater, "CACHE_DIR", Path(self.tmp.name) / "cache"):
            rel = updater.check()
            path = updater.download(rel)
            self.assertEqual(path.read_bytes(), self.payload)
            rel.sha256 = "0" * 64
            with self.assertRaises(updater.UpdateError):
                updater.download(rel)


class SecurityAutoFindTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "home"
        (self.home / "Downloads" / "받은 것").mkdir(parents=True)
        self.registered = {}
        patches = [
            mock.patch("pathlib.Path.home", return_value=self.home),
            mock.patch.object(security, "SECURITY_DIR", Path(self.tmp.name) / "security"),
            mock.patch.object(security, "winreg", object()),
            mock.patch.object(security, "registered_path", lambda: self.registered.get("dll")),
            mock.patch.object(security, "_write_registry", lambda p: self.registered.__setitem__("dll", str(p))),
            mock.patch.object(security, "resource_dir", lambda: Path(self.tmp.name) / "none"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_finds_dll_inside_zip(self):
        z = self.home / "Downloads" / "받은 것" / "HwpAutomation_보안모듈.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("HwpAutomation/FilePathCheckerModuleExample.dll", b"MZ fake dll")
        dll = security.auto_install()
        self.assertIsNotNone(dll)
        self.assertEqual(Path(self.registered["dll"]).read_bytes(), b"MZ fake dll")

    def test_finds_loose_dll(self):
        (self.home / "Downloads" / "FilePathCheckerModuleExample.dll").write_bytes(b"MZ")
        self.assertIsNotNone(security.auto_install())
        self.assertTrue(self.registered["dll"].endswith("FilePathCheckerModuleExample.dll"))

    def test_nothing_found(self):
        self.assertIsNone(security.auto_install())
        self.assertNotIn("dll", self.registered)

    def test_already_registered_is_left_alone(self):
        existing = Path(self.tmp.name) / "existing.dll"
        existing.write_bytes(b"MZ")
        self.registered["dll"] = str(existing)
        (self.home / "Downloads" / "FilePathCheckerModuleExample.dll").write_bytes(b"MZ")
        self.assertIsNone(security.auto_install())
        self.assertEqual(self.registered["dll"], str(existing))


class AnnotateTest(unittest.TestCase):
    def test_plan_form_marks_blanks_examples_tables(self):
        import io
        from hanq.doc.annotate import COLORS, annotate
        from tests.helpers import PLAN_FORM

        def header(data: bytes) -> str:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                return z.read("Contents/header.xml").decode("utf-8")

        data, summary = annotate(PLAN_FORM)
        self.assertTrue(summary.has_placeholders)
        self.assertGreater(summary.fill_lines, 10)
        self.assertGreater(summary.tables, 0)
        self.assertIn("빈칸", summary.describe())
        for color in COLORS.values():
            self.assertIn(color, header(data))
        # 원본 파일은 그대로
        self.assertNotIn(COLORS["fill"], header(Path(PLAN_FORM).read_bytes()))

    def test_empty_form_explains_how(self):
        from hanq.doc.annotate import FormSummary
        s = FormSummary(0, 0, 0, 0, 0, False)
        self.assertIn("○○○○", s.describe())


@unittest.skipUnless(sys.platform == "win32", "가짜 CLI는 윈도우 .cmd로 만든다")
class CliStatusTest(unittest.TestCase):
    def _fake(self, body: str) -> str:
        d = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(d, ignore_errors=True))
        script = d / "fake.py"
        script.write_text(f"import sys\nsys.stdout.write({body!r})\n", encoding="utf-8")
        cmd = d / "fake.cmd"
        cmd.write_text(f'@"{sys.executable}" "{script}" %*\n', encoding="utf-8")
        return str(cmd)

    def test_claude_logged_in(self):
        from hanq.ai import cli_setup
        exe = self._fake('{"loggedIn": true, "subscriptionType": "max"}')
        self.assertEqual(cli_setup.login_status("claude_code", exe), (True, "로그인됨 (max 구독)"))

    def test_claude_logged_out(self):
        from hanq.ai import cli_setup
        exe = self._fake('{"loggedIn": false}')
        self.assertFalse(cli_setup.login_status("claude_code", exe)[0])

    def test_codex_status(self):
        from hanq.ai import cli_setup
        self.assertTrue(cli_setup.login_status("codex", self._fake("Logged in using ChatGPT"))[0])
        self.assertFalse(cli_setup.login_status("codex", self._fake("Not logged in"))[0])


if __name__ == "__main__":
    unittest.main()
