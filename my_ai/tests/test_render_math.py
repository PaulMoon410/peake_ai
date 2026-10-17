from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from my_ai.memory_store import MemoryStore
import my_ai.harold.agent as harold_agent

_fake_language_model = types.ModuleType("language_model")


class _FakeLanguageModel:
    def load_model(self, *_args: object) -> bool:
        return True


_fake_language_model.NeuralLanguageModel = _FakeLanguageModel  # type: ignore[attr-defined]
with patch.dict(sys.modules, {"language_model": _fake_language_model}):
    import peakebot


class RenderMathTests(unittest.TestCase):
    def make_store(self, folder: str) -> MemoryStore:
        return MemoryStore(Path(folder) / "memory.jsonl")

    def test_chat_page_declares_conversation_history(self) -> None:
        page_source = (ROOT / "web_app.py").read_text(encoding="utf-8")

        self.assertIn("const conversationHistory = [];", page_source)

    def test_help_lists_only_supported_render_chat_commands(self) -> None:
        response = peakebot._handle_help_request("What are your commands?")

        self.assertIsNotNone(response)
        assert response is not None
        self.assertIn("learn math:", response)
        self.assertIn("recall math:", response)
        self.assertIn("remember that", response)
        self.assertIn("search web:", response)
        self.assertIn("learn about <topic>", response)
        self.assertIn("does not support the local CLI commands", response)
        self.assertIsNone(peakebot._handle_help_request("What commands do Hive bots use?"))

    def test_explicit_website_learning_routes_to_reader(self) -> None:
        with patch.object(peakebot, "_learn_from_website_url", return_value="learned") as learn:
            response = peakebot._handle_website_learning_request(
                "learn from https://example.org/article."
            )

        self.assertEqual("learned", response)
        learn.assert_called_once_with("https://example.org/article")
        self.assertIsNone(peakebot._handle_website_learning_request("Tell me about https://example.org"))

    def test_multi_source_research_command_passes_topic_and_all_urls(self) -> None:
        urls = [
            "https://one.example.org/article",
            "https://two.example.net/report",
            "https://three.example.edu/guide",
            "https://four.example.info/overview",
        ]
        with patch.object(peakebot, "_learn_from_sources", return_value="compared") as research:
            response = peakebot._handle_website_learning_request(
                f"learn about sleep and memory from {' | '.join(urls)}"
            )

        self.assertEqual("compared", response)
        research.assert_called_once_with("sleep and memory", urls)
        too_few = peakebot._handle_website_learning_request(
            "learn about sleep from https://one.example.org/article"
        )
        too_many = peakebot._handle_website_learning_request(
            "learn about sleep from " + " | ".join(urls + ["https://five.example.org/article"])
        )
        self.assertIn("2–4 article URLs", too_few or "")
        self.assertIn("2–4 article URLs", too_many or "")

    def test_multi_source_research_reports_citations_and_safe_fetch_policy(self) -> None:
        from types import SimpleNamespace

        urls = ["https://one.example.org/article", "https://two.example.net/report", "https://three.example.edu/guide"]
        pages = [
            SimpleNamespace(title="Article one", url=urls[0], notes_added=2),
            SimpleNamespace(title="Report two", url=urls[1], notes_added=1),
        ]
        report = SimpleNamespace(topic="sleep", pages=pages, notes_added=3, notes_uploaded=0, corroborations=[])
        with tempfile.TemporaryDirectory() as folder:
            with (
                patch.object(peakebot, "_get_mcf_memory_store", return_value=self.make_store(folder)),
                patch("my_ai.harold.evidence.SourceResearcher") as researcher_class,
            ):
                researcher_class.return_value.learn.return_value = report
                answer = peakebot._learn_from_sources("sleep", urls)

        self.assertIn(urls[0], answer)
        self.assertIn(urls[1], answer)
        self.assertIn("unverified", answer)
        fetcher = researcher_class.call_args.args[1]
        self.assertEqual(2.0, fetcher.policy.timeout_seconds)
        self.assertEqual(256 * 1024, fetcher.policy.max_bytes)
        self.assertEqual(1, fetcher.policy.max_redirects)
        self.assertTrue(fetcher.policy.respect_robots)

    def test_website_learning_uses_bounded_polite_reader_and_reports_source(self) -> None:
        from types import SimpleNamespace

        with tempfile.TemporaryDirectory() as folder:
            store = self.make_store(folder)
            page = SimpleNamespace(
                title="A public article",
                url="https://example.org/article",
                detail="2 observations",
            )
            report = SimpleNamespace(pages=[page], notes_added=2, notes_uploaded=2)
            with (
                patch.object(peakebot, "_get_mcf_memory_store", return_value=store),
                patch.object(harold_agent, "HaroldAgent") as agent_class,
            ):
                agent_class.return_value.learn_url.return_value = report
                answer = peakebot._learn_from_website_url("https://example.org/article")

            self.assertIn("extracted 2 concise observation(s)", answer)
            self.assertIn("https://example.org/article", answer)
            agent_class.return_value.learn_url.assert_called_once_with("https://example.org/article")
            config = agent_class.call_args.kwargs["config"]
            fetcher = agent_class.call_args.kwargs["fetcher"]
            self.assertEqual(1, config.pages_per_session)
            self.assertEqual(1, config.pages_per_host)
            self.assertFalse(config.use_model)
            self.assertEqual(8.0, fetcher.policy.timeout_seconds)
            self.assertTrue(fetcher.policy.respect_robots)

    def test_chat_calculates_and_saves_math_fact(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = self.make_store(folder)
            with (
                patch.object(peakebot, "_get_mcf_memory_store", return_value=store),
                patch.object(peakebot, "remember") as remember,
                patch.object(peakebot, "ask_local_llama") as model,
            ):
                answer = peakebot.generate_response("calculate 8 times 7")

            self.assertIn("Verified arithmetic: 8 times 7 = 56", answer)
            self.assertIn("local math memory", answer)
            self.assertEqual("Math", store.records[-1]["c"])
            self.assertIn("8 times 7 = 56", store.records[-1]["n"])
            remember.assert_called_once()
            model.assert_not_called()

    def test_chat_learns_unverified_math_statement(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = self.make_store(folder)
            with (
                patch.object(peakebot, "_get_mcf_memory_store", return_value=store),
                patch.object(peakebot, "remember"),
            ):
                answer = peakebot.generate_response("learn math: pi is irrational")

            self.assertIn("unverified math note", answer)
            self.assertIn("pi is irrational", store.records[-1]["n"])
            self.assertIn("(unverified)", store.records[-1]["n"])

    def test_chat_answers_natural_what_is_arithmetic(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = self.make_store(folder)
            with (
                patch.object(peakebot, "_get_mcf_memory_store", return_value=store),
                patch.object(peakebot, "remember"),
            ):
                answer = peakebot.generate_response("what is 9 times 9?")

            self.assertIn("Verified arithmetic: 9 times 9 = 81", answer)

    def test_empty_math_recall_asks_for_a_topic(self) -> None:
        answer = peakebot._handle_math_request("recall math")

        self.assertIn("Which math topic", answer or "")

    def test_new_math_fact_uploads_to_shared_ftp(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = self.make_store(folder)
            store.ftp_host = "ftp.example.test"
            store.ftp_user = "test-user"
            store.ftp_password = "test-password"
            with patch.object(store, "upload") as upload:
                with patch.object(peakebot, "_get_mcf_memory_store", return_value=store):
                    answer = peakebot._learn_math_statement("3 + 4")

            self.assertIn("shared math memory", answer)
            upload.assert_called_once_with(store.records[-1])

    def test_math_recall_uses_remote_math_category(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = self.make_store(folder)
            store.ftp_host = "ftp.example.test"
            store.ftp_user = "test-user"
            store.ftp_password = "test-password"
            with patch.object(store, "relevant_remote", return_value="- [Math] area = pi r squared") as recall:
                with (
                    patch.object(peakebot, "_get_mcf_memory_store", return_value=store),
                    patch.object(peakebot, "remember"),
                ):
                    answer = peakebot.generate_response("recall math: circles")

            self.assertIn("area = pi r squared", answer)
            recall.assert_called_once_with("cat:Math circles", limit=6, max_chars=1400)

    def test_non_math_prompt_is_not_intercepted(self) -> None:
        self.assertIsNone(peakebot._handle_math_request("What is the capital of France?"))


if __name__ == "__main__":
    unittest.main()
