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
        self.assertIn("does not support the local CLI commands", response)
        self.assertIsNone(peakebot._handle_help_request("What commands do Hive bots use?"))

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
