from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from assistant import SearchResults, ftp_configuration_warning, safe_slug


class AssistantTests(unittest.TestCase):
    def test_ftp_warning_identifies_missing_settings_without_showing_values(self) -> None:
        memory = SimpleNamespace(
            ftp_host="ftp.example.test",
            ftp_user="",
            ftp_password="secret",
        )

        warning = ftp_configuration_warning(memory)  # type: ignore[arg-type]

        self.assertIsNotNone(warning)
        assert warning is not None
        self.assertIn("MEMORY_FTP_USER", warning)
        self.assertIn("local-only", warning)
        self.assertNotIn("ftp.example.test", warning)
        self.assertNotIn("secret", warning)

    def test_ftp_warning_is_absent_when_all_settings_exist(self) -> None:
        memory = SimpleNamespace(ftp_host="host", ftp_user="user", ftp_password="secret")

        self.assertIsNone(ftp_configuration_warning(memory))  # type: ignore[arg-type]

    def test_safe_slug_formats_correctly(self) -> None:
        self.assertEqual("my-portfolio", safe_slug("My Portfolio!"))
        self.assertEqual("test-123-site", safe_slug("test 123 site"))
        with self.assertRaises(ValueError):
            safe_slug("???!!!")

    def test_search_results_decodes_duckduckgo_redirects(self) -> None:
        parser = SearchResults()
        html = """
        <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fpython.org%2Fdoc&rut=1">Python Documentation</a>
        <div class="result__snippet">Official documentation and guides for Python.</div>
        """
        parser.feed(html)
        self.assertEqual(1, len(parser.items))
        self.assertEqual("https://python.org/doc", parser.items[0]["url"])
        self.assertEqual("Python Documentation", parser.items[0]["title"])
        self.assertEqual("Official documentation and guides for Python.", parser.items[0]["snippet"])


if __name__ == "__main__":
    unittest.main()

