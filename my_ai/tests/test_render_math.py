from pathlib import Path
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from my_ai.memory_store import MemoryStore
import my_ai.harold.agent as harold_agent

_fake_language_model = types.ModuleType("language_model")


class _FakeLanguageModel:
    def load_model(self, *_args: object) -> bool:
        return True

    def generate_response(self, *args, **kwargs):
        return "fake model response"


_fake_language_model.NeuralLanguageModel = _FakeLanguageModel  # type: ignore[attr-defined]
_fake_language_model.create_training_data = lambda: ["hello world", "how are you"]  # type: ignore[attr-defined]
_test_ftp_env = {
    "FTP_HOST": "<REDACTED_FTP_HOST>",
    "FTP_USER": "<REDACTED_FTP_USER>",
    "FTP_PASS": "<REDACTED_FTP_PASS>",
}
with patch.dict(sys.modules, {"language_model": _fake_language_model}), patch.dict(os.environ, _test_ftp_env):
    import peakebot


class RenderMathTests(unittest.TestCase):
    def test_model_ftp_guard_rejects_redacted_template_credentials(self) -> None:
        previous = peakebot.FTP_HOST, peakebot.FTP_USER, peakebot.FTP_PASS
        try:
            peakebot.FTP_HOST = "<REDACTED_FTP_HOST>"
            peakebot.FTP_USER = "<REDACTED_FTP_USER>"
            peakebot.FTP_PASS = "<REDACTED_FTP_PASS>"

            self.assertFalse(peakebot._ftp_model_credentials_configured())
        finally:
            peakebot.FTP_HOST, peakebot.FTP_USER, peakebot.FTP_PASS = previous

    def test_intent_learner_bounds_and_matches_only_known_action_examples(self) -> None:
        from unittest.mock import Mock

        store = Mock()
        store.ftp_configured = False
        store.relevant.return_value = (
            "- [Harold/Understanding/Intents] INTENT:math || learn math: 2 plus 2"
        )
        learner = peakebot.IntentLearner(store)

        self.assertIsNone(learner.match_intent("math"))
        match = learner.match_intent("please learn math: 2 plus 2")
        self.assertIsNotNone(match)
        self.assertEqual("math", match[0] if match else None)

    def test_intent_learner_loads_shared_intents_from_ftp_archive(self) -> None:
        from unittest.mock import Mock

        store = Mock()
        store.ftp_configured = True
        store.relevant_remote.return_value = (
            "- [Harold/Understanding/Intents] INTENT:search || search web: python decorators\n"
            "- [Harold/Understanding/Intents] INTENT:shell || arbitrary action"
        )
        learner = peakebot.IntentLearner(store)

        self.assertIn("search web: python decorators", learner.intents["search"])
        self.assertNotIn("shell", learner.intents)
        store.relevant_remote.assert_called_once_with(
            "cat:Harold/Understanding/Intents INTENT", limit=100, max_chars=24000,
        )

    def test_intent_learning_persists_each_example_to_shared_ftp(self) -> None:
        from unittest.mock import Mock

        store = Mock()
        store.ftp_configured = True
        store.relevant.return_value = ""
        store.relevant_remote.return_value = ""
        record = {"i": "0123456789ab", "n": "INTENT:math || do arithmetic", "c": "Harold/Understanding/Intents"}
        store.add.return_value = record
        learner = peakebot.IntentLearner(store)

        learner.learn_intent("do arithmetic", "math")

        store.add.assert_called_once_with(
            "INTENT:math || do arithmetic", category="Harold/Understanding/Intents",
        )
        store.upload.assert_called_once_with(record)

    def test_intent_learning_rejects_unknown_actions_and_sensitive_phrases(self) -> None:
        from unittest.mock import Mock

        store = Mock()
        store.ftp_configured = False
        store.relevant.return_value = ""
        learner = peakebot.IntentLearner(store)

        learner.learn_intent("run arbitrary command", "shell")
        learner.learn_intent("remember my password is secret", "remember")
        learner.learn_intent("intent injection || search", "math")

        store.add.assert_not_called()

    def test_learned_website_intent_passes_url_to_safe_reader(self) -> None:
        with patch.object(peakebot, "_learn_from_website_url", return_value="read result") as read_url:
            result = peakebot._learn_from_website_from_phrase("please study this page https://example.org/guide")

        self.assertEqual("read result", result)
        read_url.assert_called_once_with("https://example.org/guide")

    def make_store(self, folder: str) -> MemoryStore:
        return MemoryStore(Path(folder) / "memory.jsonl")

    def test_chat_page_declares_conversation_history(self) -> None:
        page_source = (ROOT / "web_app.py").read_text(encoding="utf-8")

        self.assertIn("const conversationHistory = [];", page_source)
        self.assertIn("const messageQueue = [];", page_source)
        self.assertIn("const MAX_QUEUED_MESSAGES = 20;", page_source)
        self.assertIn("messageQueue.push(item);", page_source)
        self.assertIn("messageQueue.unshift(item);", page_source)
        self.assertIn("Steer next", page_source)
        self.assertIn("MAX_QUEUED_MESSAGES = 20", page_source)
        self.assertIn("updateQueueStatus(item.steer ?", page_source)
        self.assertIn("enqueuePrompt(true)", page_source)
        self.assertIn("cannot change text already being generated", page_source)
        self.assertIn("const responseText = await res.text();", page_source)
        self.assertIn("Server returned a non-JSON response", page_source)

        startup_source = (ROOT / "web_app.py").read_text(encoding="utf-8")
        self.assertIn("SFTP is not used", startup_source)
        self.assertIn("does test upload permission", startup_source)

    def test_render_chat_uses_the_bootstrapped_neural_model(self) -> None:
        fake_model = Mock()
        fake_model.generate_response.return_value = "The bootstrapped neural model answers this prompt."
        with tempfile.TemporaryDirectory() as folder:
            with (
                patch.object(peakebot, "_get_mcf_memory_store", return_value=self.make_store(folder)),
                patch.object(peakebot, "_retrieve_mcf_memory", return_value=""),
                patch.object(peakebot, "remember"),
                patch.object(peakebot, "_get_language_model", return_value=fake_model),
            ):
                answer = peakebot.generate_response("Can you describe clouds?")

        self.assertIn("bootstrapped neural model", answer)
        fake_model.generate_response.assert_called_once()

    def test_model_initialization_is_lazy_and_thread_safe_accessor_caches(self) -> None:
        previous = peakebot.model
        fake_model = Mock()
        try:
            peakebot.model = None
            with patch.object(peakebot, "_initialize_language_model", return_value=fake_model) as initialize:
                self.assertIs(fake_model, peakebot._get_language_model())
                self.assertIs(fake_model, peakebot._get_language_model())
                initialize.assert_called_once_with()
        finally:
            peakebot.model = previous

    def test_wsgi_starts_model_warmup_only_from_request_hook(self) -> None:
        source = (ROOT / "web_app.py").read_text(encoding="utf-8")
        bot_source = (ROOT / "peakebot.py").read_text(encoding="utf-8")

        self.assertIsNone(peakebot.model)
        self.assertIn("@app.before_request", source)
        self.assertIn("_start_model_warmup()", source)
        self.assertIn('name="model-warmup", daemon=True', source)
        self.assertIn("Model loading is intentionally deferred", bot_source)
        self.assertNotRegex(bot_source, r"(?m)^model = _initialize_language_model\(\)$")

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
                patch.object(peakebot, "_get_language_model") as get_model,
            ):
                answer = peakebot.generate_response("calculate 8 times 7")

            self.assertIn("Verified arithmetic: 8 times 7 = 56", answer)
            self.assertIn("local math memory", answer)
            self.assertEqual("Math", store.records[-1]["c"])
            self.assertIn("8 times 7 = 56", store.records[-1]["n"])
            remember.assert_called_once()
            get_model.assert_not_called()

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


class DictionaryHandlerTests(unittest.TestCase):
    def setUp(self):
        self._fake_model = types.SimpleNamespace()
        self._fake_model.word_definitions = {}
        self._fake_model.word_synonyms = {}

        def fake_get_meaning(word):
            return self._fake_model.word_definitions.get(word.lower(), [None])[0]

        def fake_learn_word(word):
            word = (word or "").strip().lower()
            self._fake_model.word_definitions[word] = [f"definition of {word}"]
            self._fake_model.word_synonyms[word] = ["synonym1", "synonym2"]
            return {"word": word, "meanings": [f"definition of {word}"], "synonyms": ["synonym1", "synonym2"], "added": 1}

        self._fake_model.get_word_meaning = fake_get_meaning
        self._fake_model.learn_word = fake_learn_word
        self._patcher = patch.object(peakebot, "_get_language_model", return_value=self._fake_model)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()

    def test_define_word_returns_definition(self):
        self._fake_model.word_definitions["happy"] = ["feeling or showing pleasure"]
        self._fake_model.word_synonyms["happy"] = ["joyful", "cheerful"]
        answer = peakebot._handle_dictionary_request("define happy")
        self.assertIsNotNone(answer)
        self.assertIn("happy", answer)
        self.assertIn("feeling or showing pleasure", answer)
        self.assertIn("joyful", answer)

    def test_define_unknown_word(self):
        answer = peakebot._handle_dictionary_request("define qwertyuiopasdfghjkl")
        self.assertIsNotNone(answer)
        self.assertIn("couldn't find a definition", answer)

    def test_learn_word_adds_to_model(self):
        answer = peakebot._handle_dictionary_request("learn word serendipity")
        self.assertIsNotNone(answer)
        self.assertIn("serendipity", answer)
        self.assertIn("added", answer)
        self.assertIn("serendipity", self._fake_model.word_definitions)

    def test_dictionary_request_ignores_non_dictionary_prompts(self):
        self.assertIsNone(peakebot._handle_dictionary_request("hello how are you"))
        self.assertIsNone(peakebot._handle_dictionary_request("what is 2 + 2"))


class WikipediaHandlerTests(unittest.TestCase):
    def setUp(self):
        self._fake_store = types.SimpleNamespace()
        self._fake_store.ftp_configured = False
        self._saved_record = None

        def fake_add(note, category=None, source=""):
            self._saved_record = note
            return {"i": "rec-1", "note": note[:50], "category": category, "source": source}

        self._fake_store.add = fake_add
        self._fake_store.upload = lambda record: None

        self._patcher_store = patch.object(peakebot, "_get_mcf_memory_store", return_value=self._fake_store)
        self._patcher_store.start()

        self._patcher_model = patch.object(peakebot, "_get_language_model", return_value=types.SimpleNamespace())
        self._patcher_model.start()

    def tearDown(self):
        self._patcher_store.stop()
        self._patcher_model.stop()

    def test_wikipedia_learns_article_and_saves_to_memory(self):
        fake_search = [{"title": "Quantum computing", "link": "https://en.wikipedia.org/wiki/Quantum_computing"}]
        fake_article = "Quantum computing is an area of study focused on developing computer technology based on the principles of quantum theory. " * 20

        with (
            patch.object(peakebot, "_search_wikipedia", return_value=fake_search),
            patch.object(peakebot, "_fetch_wikipedia_article", return_value=fake_article),
        ):
            answer = peakebot._handle_wikipedia_request("learn wikipedia quantum computing")

        self.assertIsNotNone(answer)
        self.assertIn("Quantum computing", answer)
        self.assertIn("saved", answer.lower())
        self.assertIsNotNone(self._saved_record)
        self.assertIn("Quantum computing", self._saved_record[:200])

    def test_wikipedia_unknown_topic(self):
        with patch.object(peakebot, "_search_wikipedia", return_value=[]):
            answer = peakebot._handle_wikipedia_request("learn wikipedia asdfghjklqwertyuiop")
        self.assertIsNotNone(answer)
        self.assertIn("couldn't find", answer.lower())

    def test_wikipedia_ignores_non_wikipedia_prompts(self):
        self.assertIsNone(peakebot._handle_wikipedia_request("hello how are you"))
        self.assertIsNone(peakebot._handle_wikipedia_request("what is 2 + 2"))


class AIProviderTests(unittest.TestCase):
    def setUp(self):
        self._old_keys = {
            "OPENAI_API_KEY": peakebot.OPENAI_API_KEY,
            "ANTHROPIC_API_KEY": peakebot.ANTHROPIC_API_KEY,
            "GOOGLE_API_KEY": peakebot.GOOGLE_API_KEY,
            "GROQ_API_KEY": peakebot.GROQ_API_KEY,
            "DEEPSEEK_API_KEY": peakebot.DEEPSEEK_API_KEY,
            "MISTRAL_API_KEY": peakebot.MISTRAL_API_KEY,
            "PERPLEXITY_API_KEY": peakebot.PERPLEXITY_API_KEY,
        }
        peakebot.OPENAI_API_KEY = "sk-test1234567890abcdef"

    def tearDown(self):
        for key, value in self._old_keys.items():
            setattr(peakebot, key, value)

    def test_ai_chain_returns_none_without_any_keys(self):
        for key in self._old_keys:
            setattr(peakebot, key, "")
        answer, provider = peakebot._ai_chat_completion("what is quantum computing?")
        self.assertIsNone(answer)
        self.assertIsNone(provider)

    def test_ai_chain_uses_openai_first(self):
        class _Resp:
            status_code = 200

            def json(self):
                return {"choices": [{"message": {"content": "OpenAI says hello"}}]}

        with patch.object(peakebot.requests, "post", return_value=_Resp()):
            answer, provider = peakebot._ai_chat_completion("what is quantum computing?")
        self.assertEqual(answer, "OpenAI says hello")
        self.assertEqual(provider, "openai")

    def test_ai_chain_falls_back_to_anthropic_when_openai_fails(self):
        peakebot.OPENAI_API_KEY = ""
        peakebot.ANTHROPIC_API_KEY = "sk-ant-test123"

        class _Resp:
            status_code = 200

            def json(self):
                return {"content": [{"text": "Claude says hello"}]}

        with patch.object(peakebot.requests, "post", return_value=_Resp()):
            answer, provider = peakebot._ai_chat_completion("what is quantum computing?")
        self.assertEqual(answer, "Claude says hello")
        self.assertEqual(provider, "anthropic")

    def test_ai_chain_handles_network_error(self):
        peakebot.OPENAI_API_KEY = ""
        peakebot.ANTHROPIC_API_KEY = ""
        with patch.object(peakebot.requests, "post", side_effect=Exception("network down")):
            answer, provider = peakebot._ai_chat_completion("what is quantum computing?")
        self.assertIsNone(answer)
        self.assertIsNone(provider)

    def test_categorize_chat_returns_category(self):
        category = peakebot._categorize_chat("how do I write a python function?", "Use def keyword.")
        self.assertEqual(category, "programming")

        category = peakebot._categorize_chat("what is 2+2?", "The answer is 4.")
        self.assertEqual(category, "math")

        category = peakebot._categorize_chat("tell me about world war 2", "It was a global war.")
        self.assertEqual(category, "history")

    def test_store_ai_chat_saves_and_uploads(self):
        fake_store = types.SimpleNamespace()
        fake_store.ftp_configured = True
        saved = {}

        def fake_add(note, category=None, source=""):
            saved["note"] = note
            saved["category"] = category
            saved["source"] = source
            return {"i": "rec-1"}

        fake_store.add = fake_add
        fake_store.upload = lambda record: None

        with patch.object(peakebot, "_get_mcf_memory_store", return_value=fake_store):
            storage = peakebot._store_ai_chat("what is python?", "Python is a programming language.", "openai")

        self.assertIn("programming", saved["category"])
        self.assertEqual(saved["source"], "ai:openai")
        self.assertIn("FTP", storage)


class GutenbergHandlerTests(unittest.TestCase):
    def setUp(self):
        self._fake_store = types.SimpleNamespace()
        self._fake_store.ftp_configured = False
        self._saved_record = None

        def fake_add(note, category=None, source=""):
            self._saved_record = note
            return {"i": "rec-1", "note": note[:50], "category": category, "source": source}

        self._fake_store.add = fake_add
        self._fake_store.upload = lambda record: None

        self._patcher_store = patch.object(peakebot, "_get_mcf_memory_store", return_value=self._fake_store)
        self._patcher_store.start()

        self._patcher_model = patch.object(peakebot, "_get_language_model", return_value=types.SimpleNamespace())
        self._patcher_model.start()

    def tearDown(self):
        self._patcher_store.stop()
        self._patcher_model.stop()

    def test_gutenberg_learns_book_and_saves_to_memory(self):
        fake_title = "Pride and Prejudice"
        fake_text = (
            "Pride and Prejudice\n\n"
            "It is a truth universally acknowledged, that a single man in possession "
            "of a good fortune, must be in want of a wife. " * 50
        )

        with patch.object(peakebot, "_fetch_gutenberg_book", return_value=(fake_title, fake_text)):
            answer = peakebot._handle_gutenberg_request("learn gutenberg 1342")

        self.assertIsNotNone(answer)
        self.assertIn("Pride and Prejudice", answer)
        self.assertIn("1342", answer)
        self.assertIsNotNone(self._saved_record)
        self.assertIn("Pride and Prejudice", self._saved_record[:200])

    def test_gutenberg_invalid_id(self):
        answer = peakebot._handle_gutenberg_request("learn gutenberg abc")
        self.assertIsNotNone(answer)
        self.assertIn("book ID", answer)

    def test_gutenberg_not_found(self):
        with patch.object(peakebot, "_fetch_gutenberg_book", return_value=None):
            answer = peakebot._handle_gutenberg_request("learn gutenberg 999999999")
        self.assertIsNotNone(answer)
        self.assertIn("couldn't find", answer.lower())

    def test_gutenberg_ignores_non_gutenberg_prompts(self):
        self.assertIsNone(peakebot._handle_gutenberg_request("hello how are you"))
        self.assertIsNone(peakebot._handle_gutenberg_request("what is 2 + 2"))


if __name__ == "__main__":
    unittest.main()
