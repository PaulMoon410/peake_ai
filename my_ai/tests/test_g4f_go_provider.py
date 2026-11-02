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

    def test_g4f_space_disabled_without_key(self) -> None:
        with ExitStack() as stack:
            stack.enter_context(patch.object(peakebot, "G4F_SPACE_API_KEY", ""))
            post = stack.enter_context(patch.object(peakebot.requests, "post"))
            self.assertIsNone(peakebot._ai_chat_g4f_space("sys", "hi"))
        post.assert_not_called()

    def test_g4f_space_request(self) -> None:
        response = Mock(status_code=200)
        response.json.return_value = {"choices": [{"message": {"content": " ok "}}]}
        with ExitStack() as stack:
            stack.enter_context(patch.object(peakebot, "G4F_SPACE_API_KEY", "k"))
            post = stack.enter_context(
                patch.object(peakebot.requests, "post", return_value=response)
            )
            self.assertEqual("ok", peakebot._ai_chat_g4f_space("sys", "hi"))
        self.assertEqual("https://g4f.space/v1/chat/completions", post.call_args[0][0])

    def test_self_talk_skips_provider_junk(self) -> None:
        with ExitStack() as stack:
            stack.enter_context(
                patch.object(peakebot, "_AI_PROVIDERS", [("g4f", "_ai_chat_g4f"), ("g4f-go", "_ai_chat_g4f_go")])
            )
            stack.enter_context(patch.object(peakebot, "_PROVIDER_ORDER_PREFERENCE", []))
            stack.enter_context(patch.object(peakebot, "G4F_GO_BASE_URL", "http://x"))
            stack.enter_context(
                patch.dict(peakebot.__dict__, {"_ai_chat_g4f": lambda s, u: "Sign up and repeat your request."})
            )
            stack.enter_context(
                patch.dict(peakebot.__dict__, {"_ai_chat_g4f_go": lambda s, u: "Real answer."})
            )
            result = peakebot._query_ai_providers_for_self_talk("hi")
        self.assertEqual({"g4f-go": "Real answer."}, result["answers"])

    def test_junk_filter(self) -> None:
        self.assertTrue(peakebot._looks_like_provider_junk("Sign up and repeat your request."))
        self.assertTrue(peakebot._looks_like_provider_junk(""))
        self.assertTrue(peakebot._looks_like_provider_junk("[Install now](https://unifiedlink.svc.cloud.microsoft/app)"))
        self.assertFalse(peakebot._looks_like_provider_junk("3"))
        self.assertFalse(peakebot._looks_like_provider_junk("Sure, I can walk you through nmap basics."))


if __name__ == "__main__":
    unittest.main()
