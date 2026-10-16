from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from assistant import (
    SearchResults,
    build_search_answer_prompt,
    contextual_search_query,
    ftp_configuration_warning,
    safe_slug,
)


class AssistantTests(unittest.TestCase):
    def test_contextual_search_query_resolves_follow_up_with_last_user_topic(self) -> None:
        history = [("How do I make a Hive bot?", "Start by choosing one safe task.")]

        self.assertEqual(
            "How do I make a Hive bot? what about Python?",
            contextual_search_query("what about Python?", history),
        )

    def test_contextual_search_query_leaves_standalone_search_alone(self) -> None:
        self.assertEqual(
            "latest Python release",
            contextual_search_query("latest Python release", [("Hive bot", "Okay")]),
        )

    def test_search_answer_prompt_requests_conversation_and_selective_sources(self) -> None:
        prompt = build_search_answer_prompt(
            "what about Python?",
            [
                {"title": "Python Docs", "snippet": "Official guide.", "url": "https://python.org/docs"},
                {"title": "Another result", "snippet": "More detail.", "url": "https://example.org"},
            ],
            [("How do I make a Hive bot?", "Start with one safe task.")],
        )

        self.assertIn("How do I make a Hive bot?", prompt)
        self.assertIn("Give the answer before sources", prompt)
        self.assertIn("at most three relevant markdown links", prompt)
        self.assertIn("Do not dump the results as a list of links", prompt)

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

