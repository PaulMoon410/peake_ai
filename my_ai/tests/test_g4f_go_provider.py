import unittest
from contextlib import ExitStack
from unittest.mock import Mock, patch

import peakebot


class G4fGoProviderTests(unittest.TestCase):
    def test_is_disabled_without_base_url(self) -> None:
        with ExitStack() as stack:
            stack.enter_context(patch.object(peakebot, "G4F_GO_BASE_URL", ""))
            post = stack.enter_context(patch.object(peakebot.requests, "post"))

            self.assertIsNone(peakebot._ai_chat_g4f_go("hello"))

        post.assert_not_called()

    def test_uses_openai_compatible_endpoint_and_extracts_answer(self) -> None:
        response = Mock(status_code=200)
        response.json.return_value = {
            "choices": [{"message": {"content": " Hello from g4f-go "}}]
        }
        with ExitStack() as stack:
            stack.enter_context(
                patch.object(peakebot, "G4F_GO_BASE_URL", "http://192.168.1.158:10000/")
            )
            stack.enter_context(patch.object(peakebot, "G4F_GO_API_KEY", "test-token"))
            stack.enter_context(patch.object(peakebot, "G4F_GO_MODEL", "test-model"))
            post = stack.enter_context(
                patch.object(peakebot.requests, "post", return_value=response)
            )

            answer = peakebot._ai_chat_g4f_go("hello")

        self.assertEqual("Hello from g4f-go", answer)
        post.assert_called_once_with(
            "http://192.168.1.158:10000/v1/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer test-token",
            },
            json={
                "model": "test-model",
                "messages": [
                    {"role": "system", "content": peakebot._CONVERSATION_SYSTEM_PROMPT},
                    {"role": "user", "content": "hello"},
                ],
                "temperature": 0.7,
                "max_tokens": 120,
            },
            timeout=15,
        )

    def test_returns_none_for_non_success_status(self) -> None:
        response = Mock(status_code=503)
        with ExitStack() as stack:
            stack.enter_context(
                patch.object(peakebot, "G4F_GO_BASE_URL", "http://192.168.1.158:10000")
            )
            stack.enter_context(
                patch.object(peakebot.requests, "post", return_value=response)
            )

            self.assertIsNone(peakebot._ai_chat_g4f_go("hello"))


if __name__ == "__main__":
    unittest.main()
