"""Tests for Harold's critic and truthfulness verification pipeline."""

import unittest
from unittest.mock import MagicMock
from my_ai.harold_critic import HaroldCognitivePipeline


class TestHaroldCriticPipeline(unittest.TestCase):
    def test_draft_harold_response(self):
        mock_model = MagicMock()
        mock_model.generate_response.return_value = "Harold: The sky is blue because Rayleigh scattering."
        pipeline = HaroldCognitivePipeline(language_model=mock_model)

        draft = pipeline.draft_harold_response("Why is the sky blue?", memory_context="light physics")
        self.assertEqual(draft, "The sky is blue because Rayleigh scattering.")
        mock_model.generate_response.assert_called_once()

    def test_verify_truthfulness(self):
        pipeline = HaroldCognitivePipeline()
        report = pipeline.verify_truthfulness("Python is an interpreted programming language.", "Python programming language interpreted syntax")
        self.assertTrue(report["is_truthful"])
        self.assertGreater(report["confidence"], 0.5)

    def test_polish_and_critique_calls_ai_critic(self):
        mock_ai = MagicMock()
        mock_ai.return_value = {
            "answer": "The sky appears blue due to Rayleigh scattering in Earth's atmosphere.",
            "provider": "openai"
        }
        pipeline = HaroldCognitivePipeline(ai_chat_func=mock_ai)

        polished, provider = pipeline.polish_and_critique(
            prompt="Why is the sky blue?",
            draft="Sky is blue cuz scatter light.",
            memory_context="Rayleigh scattering"
        )
        self.assertEqual(provider, "openai")
        self.assertIn("Rayleigh scattering", polished)
        mock_ai.assert_called_once()

    def test_record_online_learning(self):
        import tempfile, json
        with tempfile.NamedTemporaryFile(suffix=".json") as tmp:
            pipeline = HaroldCognitivePipeline(buffer_path=tmp.name)
            pipeline.record_online_learning(
                prompt="Say hello",
                raw_draft="helo there",
                polished="Hello there!",
                provider="critic"
            )
            with open(tmp.name, "r") as f:
                data = json.load(f)
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]["raw_draft"], "helo there")
            self.assertEqual(data[0]["polished"], "Hello there!")


if __name__ == "__main__":
    unittest.main()
