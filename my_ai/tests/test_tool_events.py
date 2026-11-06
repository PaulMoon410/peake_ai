import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import tool_events


class ToolEventsTests(unittest.TestCase):
    def test_record_outside_capture_is_noop(self):
        tool_events.record("x", {"a": 1}, "r")

    def test_traced_records_only_handled_calls(self):
        @tool_events.traced("demo")
        def handler(prompt):
            return "done" if prompt == "yes" else None

        with tool_events.capture() as events:
            handler("no")
            handler("yes")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["name"], "demo")
        self.assertEqual(events[0]["args"], {"prompt": "yes"})
        self.assertEqual(events[0]["status"], "ok")

    def test_traced_records_errors_and_reraises(self):
        @tool_events.traced("boom")
        def handler(prompt):
            raise ValueError("bad")

        with tool_events.capture() as events:
            with self.assertRaises(ValueError):
                handler("x")
        self.assertEqual(events[0]["status"], "error")

    def test_markdown_and_clipping(self):
        with tool_events.capture() as events:
            tool_events.record("web_search", {"query": "q" * 500}, "s" * 900)
        self.assertLessEqual(len(events[0]["summary"]), 300)
        self.assertLessEqual(len(events[0]["args"]["query"]), 200)
        self.assertIn("web search", tool_events.format_markdown(events))
        self.assertEqual(tool_events.format_markdown([]), "")


if __name__ == "__main__":
    unittest.main()
