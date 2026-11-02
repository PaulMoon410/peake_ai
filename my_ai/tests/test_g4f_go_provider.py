import unittest
from contextlib import ExitStack
from unittest.mock import Mock, patch

import peakebot


class G4fGoProviderTests(unittest.TestCase):
    def test_is_disabled_without_base_url(self) -> None:
        with ExitStack() as stack:
            stack.enter_context(patch.object(peakebot, "G4F_GO_BASE_URL", ""))
            post = stack.enter_context(patch.object(peakebot.requests, "post"))

            self.assertIsNone(peakebot._ai_chat_g4f_go("sys", "hello"))

        post.assert_not_called()

    def test_uses_openai_compatible_endpoint_and_extracts_answer(self) -> None:
        response = Mock(status_code=200)
        response.json.return_value = {
            "choices": [{"message": {"content": " Hello from g4f-go "}}]
        }
        with ExitStack() as stack:
            stack.enter_context(patch.object(peakebot, "G4F_GO_BASE_URL", "http://127.0.0.1:8080/"))
            stack.enter_context(patch.object(peakebot, "G4F_GO_API_KEY", "test-token"))
            stack.enter_context(patch.object(peakebot, "G4F_GO_MODEL", "auto"))
            post = stack.enter_context(
                patch.object(peakebot.requests, "post", return_value=response)
            )

            answer = peakebot._ai_chat_g4f_go("sys", "hello")

        self.assertEqual("Hello from g4f-go", answer)
        args, kwargs = post.call_args
        self.assertEqual("http://127.0.0.1:8080/v1/chat/completions", args[0])
        self.assertEqual("Bearer test-token", kwargs["headers"]["Authorization"])
        self.assertEqual("auto", kwargs["json"]["model"])

    def test_raises_for_non_success_status(self) -> None:
        response = Mock(status_code=503)
        with ExitStack() as stack:
            stack.enter_context(patch.object(peakebot, "G4F_GO_BASE_URL", "http://127.0.0.1:8080"))
            stack.enter_context(patch.object(peakebot.requests, "post", return_value=response))

            with self.assertRaises(RuntimeError):
                peakebot._ai_chat_g4f_go("sys", "hello")

    def test_is_last_provider(self) -> None:
        self.assertEqual("g4f-go", peakebot._AI_PROVIDERS[-1][0])


if __name__ == "__main__":
    unittest.main()
