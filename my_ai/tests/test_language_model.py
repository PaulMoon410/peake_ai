from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

try:
    import numpy as np
except ImportError:
    np = None  # type: ignore[assignment]

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if np is not None:
    from language_model import NeuralLanguageModel
else:
    NeuralLanguageModel = None  # type: ignore[assignment,misc]


def _fake_dictionary_response(meanings, synonyms):
    """Return a mock requests.Response for the Dictionary API."""
    class _Response:
        status_code = 200
        def json(self):
            return [{"meanings": [{"definitions": [{"definition": d} for d in meanings], "synonyms": synonyms}]}]
    return _Response()


@unittest.skipIf(np is None, "NumPy is required to exercise the neural model")
class NeuralLanguageModelTests(unittest.TestCase):
    def make_model(self) -> NeuralLanguageModel:
        assert NeuralLanguageModel is not None
        model = NeuralLanguageModel(embedding_dim=4, hidden_dim=8, learning_rate=0.01)
        model.build_vocabulary([
            "hello friend how are you",
            "hello friend I am learning",
            "how are you friend",
        ])
        return model

    def test_safe_npz_round_trip_preserves_weights_and_generates(self) -> None:
        model = self.make_model()
        model.train_on_text(["hello friend how are you", "hello friend I am learning"], epochs=1)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "brain.npz"
            model.save_model(path)
            loaded = NeuralLanguageModel()

            self.assertTrue(loaded.load_model(path))
            self.assertEqual(model.vocab, loaded.vocab)
            self.assertTrue((model.W_output == loaded.W_output).all())
            self.assertEqual(4, loaded.embedding_dim)
            self.assertEqual(8, loaded.hidden_dim)
            self.assertIsInstance(loaded.generate_response("hello friend"), str)

    def test_pickle_file_is_not_loaded_as_a_model_archive(self) -> None:
        assert NeuralLanguageModel is not None
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "legacy.pkl"
            path.write_bytes(b"not a safe NPZ archive")

            self.assertFalse(NeuralLanguageModel().load_model(path))

    def test_rejects_oversized_checkpoint_before_loading(self) -> None:
        assert NeuralLanguageModel is not None
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "oversized.npz"
            with path.open("wb") as output:
                output.truncate(64 * 1024 * 1024 + 1)

            self.assertFalse(NeuralLanguageModel().load_model(path))

    def test_empty_context_uses_unknown_token_without_nan(self) -> None:
        assert NeuralLanguageModel is not None and np is not None
        model = self.make_model()

        probabilities, _ = model.forward([])

        self.assertTrue(bool(np.isfinite(probabilities).all()))
        self.assertAlmostEqual(1.0, float(probabilities.sum()), places=5)

    def test_learn_word_adds_word_and_synonyms_to_vocab(self) -> None:
        assert NeuralLanguageModel is not None
        model = self.make_model()
        before_size = model.vocab_size

        fake_response = _fake_dictionary_response(
            meanings=["A happy emotional state."],
            synonyms=["joyful", "cheerful", "glad"],
        )
        with patch("language_model.requests.get", return_value=fake_response):
            result = model.learn_word("happy")

        self.assertEqual(result["word"], "happy")
        self.assertEqual(result["meanings"], ["A happy emotional state."])
        self.assertEqual(result["synonyms"], ["cheerful", "glad", "joyful"])
        self.assertGreater(result["added"], 0)
        self.assertIn("happy", model.vocab)
        self.assertIn("joyful", model.vocab)
        self.assertIn("cheerful", model.vocab)
        self.assertIn("glad", model.vocab)
        self.assertGreater(model.vocab_size, before_size)
        self.assertEqual(model.word_definitions["happy"], ["A happy emotional state."])

    def test_learn_word_returns_empty_when_api_fails(self) -> None:
        assert NeuralLanguageModel is not None
        model = self.make_model()
        before_size = model.vocab_size

        with patch("language_model.requests.get", side_effect=Exception("network down")):
            result = model.learn_word("nonexistentxyz")

        self.assertEqual(result["added"], 0)
        self.assertEqual(result["synonyms"], [])
        self.assertEqual(model.vocab_size, before_size)

    def test_get_word_meaning_fetches_from_api_when_not_cached(self) -> None:
        assert NeuralLanguageModel is not None
        model = self.make_model()

        fake_response = _fake_dictionary_response(
            meanings=["A large body of water."],
            synonyms=["sea", "ocean"],
        )
        with patch("language_model.requests.get", return_value=fake_response):
            definition = model.get_word_meaning("lake")

        self.assertEqual(definition, "A large body of water.")
        self.assertEqual(model.word_definitions["lake"], ["A large body of water."])
        self.assertEqual(model.word_synonyms["lake"], ["ocean", "sea"])

    def test_expand_with_synonyms_replaces_tokens(self) -> None:
        assert NeuralLanguageModel is not None
        model = self.make_model()
        model.word_synonyms["friend"] = ["pal", "buddy", "companion"]

        expanded = model.expand_with_synonyms("hello friend how are you")
        tokens = expanded.split()
        self.assertIn(tokens[1], ["pal", "buddy", "companion"])
        self.assertEqual(tokens[0], "hello")


@unittest.skipIf(np is None, "NumPy is required to exercise the neural model")
class DictionaryPreloadTests(unittest.TestCase):
    def test_load_dictionary_data_calls_api_for_each_common_word(self) -> None:
        assert NeuralLanguageModel is not None
        model = NeuralLanguageModel(embedding_dim=4, hidden_dim=8, learning_rate=0.01)

        call_words: list[str] = []

        def fake_get(url, **kwargs):
            call_words.append(url.rsplit("/", 1)[-1])
            return _fake_dictionary_response(meanings=["a definition"], synonyms=["a synonym"])

        with patch("language_model.requests.get", side_effect=fake_get):
            model.load_dictionary_data()

        self.assertGreater(len(call_words), 0)
        self.assertGreater(len(model.word_definitions), 0)
        self.assertEqual(model.word_definitions["hello"], ["a definition"])
        self.assertEqual(model.word_synonyms["hello"], ["a synonym"])


if __name__ == "__main__":
    unittest.main()
