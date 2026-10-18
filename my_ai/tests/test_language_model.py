from pathlib import Path
import sys
import tempfile
import unittest

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


if __name__ == "__main__":
    unittest.main()
