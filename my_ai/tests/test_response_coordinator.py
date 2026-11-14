import json
import threading
import unittest
import uuid
from unittest.mock import Mock

from flask import Flask

from response_coordinator import SYSTEM, register_response_coordinator


class ResponseCoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.lock = threading.Lock()
        self.rate_limit = Mock(return_value=True)
        self.synthesize = Mock(return_value={"answer": "Harold evaluated the evidence.", "provider": "test-model"})
        register_response_coordinator(self.app, lambda: "test-key", self.rate_limit, self.lock, self.synthesize)
        self.client = self.app.test_client()
        self.payload = {
            "session_id": str(uuid.uuid4()), "prompt": "Compare these approaches.",
            "contributors": ["cline", "kilo", "codegeex"],
            "results": [
                {"name": "cline", "source": "operator-submitted", "answer": "Approach one."},
                {"name": "kilo", "source": "operator-submitted", "answer": "Approach two."},
                {"name": "codegeex", "source": "operator-submitted", "error": "Unavailable."},
            ],
        }

    def post(self, payload):
        return self.client.post("/api/extension/pool/synthesize", json=payload,
                                headers={"Authorization": "Bearer test-key"})

    def test_answers_and_failure_are_forwarded_without_fake_consensus(self):
        response = self.post(self.payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["session_id"], self.payload["session_id"])
        self.assertEqual(response.json["results"], self.payload["results"])
        self.assertEqual(response.json["successful_contributors"], 2)
        self.assertEqual(response.json["synthesizer"], "test-model")
        forwarded = json.loads(self.synthesize.call_args.args[0])
        self.assertEqual(forwarded, self.payload)
        self.assertEqual(self.synthesize.call_args.kwargs["system_prompt"], SYSTEM)
        self.assertIn("untrusted", SYSTEM)
        self.assertFalse(self.lock.locked())

    def test_malformed_and_incomplete_submissions_never_synthesize(self):
        self.assertEqual(self.client.post("/api/extension/pool/synthesize", json=self.payload).status_code, 401)
        mutations = [
            [], {**self.payload, "session_id": "not-a-session"},
            {**self.payload, "prompt": "x" * 4001},
            {**self.payload, "contributors": ["cline", "cline"]},
            {**self.payload, "results": self.payload["results"][:2]},
            {**self.payload, "results": [self.payload["results"][0]] * 3},
            {**self.payload, "results": [{**r, "source": "automatic"} for r in self.payload["results"]]},
            {**self.payload, "results": [{**r, "answer": "x" * 4001} for r in self.payload["results"]]},
        ]
        for payload in mutations:
            self.assertEqual(self.post(payload).status_code, 400)
        all_failed = {**self.payload, "results": [
            {"name": name, "source": "operator-submitted", "error": "failed"}
            for name in self.payload["contributors"]
        ]}
        self.assertEqual(self.post(all_failed).status_code, 409)
        response = self.client.post("/api/extension/pool/synthesize", data="x" * (128 * 1024 + 1),
                                    content_type="application/json", headers={"Authorization": "Bearer test-key"})
        self.assertEqual(response.status_code, 413)
        self.synthesize.assert_not_called()

    def test_busy_rate_limit_and_synthesis_failure_keep_non_success_status(self):
        with self.lock:
            self.assertEqual(self.post(self.payload).status_code, 503)
        self.rate_limit.return_value = False
        self.assertEqual(self.post(self.payload).status_code, 429)
        self.synthesize.assert_not_called()
        self.rate_limit.return_value = True
        self.synthesize.side_effect = RuntimeError("Unavailable")
        self.assertEqual(self.post(self.payload).status_code, 503)
        self.assertFalse(self.lock.locked())
        self.synthesize.side_effect = None
        self.synthesize.return_value = {"answer": None, "provider": None}
        self.assertEqual(self.post(self.payload).status_code, 503)
        self.assertFalse(self.lock.locked())


if __name__ == "__main__":
    unittest.main()
