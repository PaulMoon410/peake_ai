import json
import threading
import unittest
from unittest.mock import Mock, patch

from flask import Flask

import peakebot
from response_coordinator import register_response_coordinator
from server_api_pool import collect_server_api_pool


class AutomaticConsensusTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.lock = threading.Lock()
        self.rate = Mock(return_value=True)
        self.collect = Mock(return_value=[
            {"name": "google", "source": "server-api", "answer": "Independent answer A"},
            {"name": "groq", "source": "server-api", "answer": "Independent answer B"},
            {"name": "openrouter", "source": "server-api", "error": "Unavailable"},
        ])
        self.synthesize = Mock(return_value={"answer": "Final evaluation", "provider": "synthesis-provider"})
        register_response_coordinator(self.app, lambda: "test-key", self.rate, self.lock, self.synthesize, self.collect)
        self.client = self.app.test_client()

    def post(self, payload):
        return self.client.post("/api/extension/pool/query", json=payload,
                                headers={"Authorization": "Bearer test-key"})

    def test_queries_and_synthesizes_real_provider_labels_with_failures(self):
        response = self.post({"prompt": "Question"})
        self.assertEqual(response.status_code, 200)
        self.collect.assert_called_once_with("Question")
        self.assertEqual(response.json["source"], "server-api")
        self.assertEqual(response.json["successful_contributors"], 2)
        self.assertEqual(response.json["results"], self.collect.return_value)
        data = json.loads(self.synthesize.call_args.args[0])
        self.assertEqual(data["contributors"], ["google", "groq", "openrouter"])
        self.assertEqual(data["prompt"], "Question")
        self.assertNotIn("cline", data["contributors"])
        self.assertFalse(self.lock.locked())

    def test_auth_invalid_request_and_rate_limit_prevent_collection(self):
        self.assertEqual(self.client.post("/api/extension/pool/query", json={"prompt": "Question"}).status_code, 401)
        for payload in ({}, {"prompt": ""}, {"prompt": "x" * 4001}, {"prompt": "Q", "results": []}, []):
            self.assertEqual(self.post(payload).status_code, 400)
        self.rate.return_value = False
        self.assertEqual(self.post({"prompt": "Question"}).status_code, 429)
        self.collect.assert_not_called()

    def test_failed_or_recursive_sources_never_become_consensus(self):
        self.collect.return_value[1] = {"name": "groq", "source": "server-api", "error": "Failed"}
        self.assertEqual(self.post({"prompt": "Q"}).status_code, 409)
        self.synthesize.assert_not_called()
        self.collect.return_value[0]["name"] = "harold"
        self.assertEqual(self.post({"prompt": "Q"}).status_code, 503)
        self.synthesize.assert_not_called()

    def test_provider_calls_are_parallel_and_explicitly_fail_without_two_configs(self):
        barrier = threading.Barrier(2)
        def peer(system, prompt):
            barrier.wait(timeout=2)
            self.assertIn("independent", system)
            self.assertEqual(prompt, "Question")
            return "A peer answer"
        with patch.object(peakebot, "GOOGLE_API_KEY", "test-key"), \
                patch.object(peakebot, "GROQ_API_KEY", "test-key"), \
                patch.object(peakebot, "OPENROUTER_API_KEY", ""), \
                patch.object(peakebot, "_ai_chat_google", side_effect=peer), \
                patch.object(peakebot, "_ai_chat_groq", side_effect=peer):
            results = collect_server_api_pool("Question")
        self.assertEqual([r["name"] for r in results], ["google", "groq"])
        self.assertTrue(all(r["source"] == "server-api" and r["answer"] for r in results))
        with patch.object(peakebot, "GOOGLE_API_KEY", ""), \
                patch.object(peakebot, "GROQ_API_KEY", ""), \
                patch.object(peakebot, "OPENROUTER_API_KEY", ""):
            with self.assertRaisesRegex(RuntimeError, "at least two"):
                collect_server_api_pool("Question")


if __name__ == "__main__":
    unittest.main()
