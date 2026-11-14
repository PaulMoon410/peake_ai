import json
import threading
import unittest
from unittest.mock import Mock

from flask import Flask

from ollama_adapter import register_ollama_adapter


class OllamaAdapterTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.model = Mock()
        self.model.generate_response.return_value = "native reply"
        self.lock = threading.Lock()
        self.rate_limit = Mock(return_value=True)
        self.get_model = Mock(return_value=self.model)
        register_ollama_adapter(
            self.app, lambda: "test-key",
            self.rate_limit, self.lock, self.get_model,
        )
        self.client = self.app.test_client()
        self.headers = {"Authorization": "Bearer test-key"}

    def post(self, payload, route="chat"):
        return self.client.post("/ollama/api/" + route, json=payload, headers=self.headers)

    def test_native_chat_and_generate_translation(self):
        result = self.post({"model": "harold", "stream": False, "messages": [
            {"role": "system", "content": "Be brief"},
            {"role": "user", "content": "Earlier question"},
            {"role": "assistant", "content": "Earlier reply"},
            {"role": "user", "content": "Next question"},
        ], "options": {"temperature": 0.4, "num_predict": 12}})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["message"]["content"], "native reply")
        self.assertTrue(result.json["done"])
        self.model.generate_response.assert_called_once_with(
            "system: Be brief\nuser: Earlier question\nassistant: Earlier reply\nuser: Next question",
            max_length=12, temperature=0.4,
        )
        result = self.post({"model": "harold:latest", "prompt": "A prompt",
                            "system": "Be brief", "stream": False}, "generate")
        self.assertEqual(result.json["response"], "native reply")
        self.model.generate_response.assert_called_with(
            "system: Be brief\nuser: A prompt", max_length=50, temperature=0.7,
        )
        self.assertFalse(self.lock.locked())

    def test_default_stream_is_valid_ndjson_with_terminal_record(self):
        for route, field in (("chat", "message"), ("generate", "response")):
            payload = {"model": "harold", "messages": [{"role": "user", "content": "hi"}]}
            if route == "generate":
                payload = {"model": "harold", "prompt": "hi"}
            result = self.post(payload, route)
            self.assertEqual(result.mimetype, "application/x-ndjson")
            records = [json.loads(line) for line in result.data.splitlines()]
            self.assertEqual(len(records), 2)
            self.assertFalse(records[0]["done"])
            self.assertTrue(records[1]["done"])
            self.assertEqual(records[1]["done_reason"], "stop")
            self.assertIn(field, records[0])

    def test_auth_validation_and_unsupported_inputs_never_generate(self):
        self.assertEqual(self.client.get("/ollama/api/tags").status_code, 401)
        self.assertEqual(self.client.post("/ollama/api/chat", json={}).status_code, 401)
        valid = {"model": "harold", "messages": [{"role": "user", "content": "hi"}]}
        invalid = [
            [], {**valid, "model": "other"}, {**valid, "stream": "false"},
            {**valid, "tools": []}, {**valid, "options": {"temperature": 0}},
            {**valid, "options": {"temperature": float("nan")}},
            {**valid, "options": {"num_predict": True}},
            {**valid, "options": {"num_predict": 257}},
            {**valid, "options": {"num_ctx": 2048}},
            {**valid, "messages": [{"role": "user", "content": "hi", "images": []}]},
            {**valid, "messages": [{"role": "assistant", "content": "hi"}]},
            {**valid, "messages": [{"role": "user", "content": "x" * 100001}]},
        ]
        for payload in invalid:
            with self.subTest(payload=str(payload)[:80]):
                self.assertEqual(self.post(payload).status_code, 400)
        malformed = self.client.post("/ollama/api/chat", data="{",
                                     content_type="application/json", headers=self.headers)
        self.assertEqual(malformed.status_code, 400)
        self.assertEqual(self.client.post("/ollama/api/chat", data="x",
                                         headers=self.headers).status_code, 400)
        huge = self.client.post("/ollama/api/chat", data="x" * (1024 * 1024 + 1),
                                content_type="application/json", headers=self.headers)
        self.assertEqual(huge.status_code, 413)
        self.get_model.assert_not_called()

    def test_busy_rate_limited_and_failed_generation_are_explicit(self):
        payload = {"model": "harold", "prompt": "hi", "stream": False}
        self.rate_limit.return_value = False
        self.assertEqual(self.post(payload, "generate").status_code, 429)
        self.rate_limit.return_value = True
        with self.lock:
            self.assertEqual(self.post(payload, "generate").status_code, 503)
        self.get_model.assert_not_called()
        self.model.generate_response.side_effect = RuntimeError("failure")
        result = self.post(payload, "generate")
        self.assertEqual(result.status_code, 503)
        self.assertIn("failed", result.json["error"])
        self.assertFalse(self.lock.locked())
        self.model.generate_response.side_effect = None
        self.model.generate_response.return_value = ""
        self.assertEqual(self.post(payload, "generate").status_code, 503)
        self.assertFalse(self.lock.locked())


if __name__ == "__main__":
    unittest.main()
