import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from my_ai import harold_waves as hw  # noqa: E402

NOW = datetime(2026, 11, 3, 15, 0, tzinfo=timezone.utc)
FACTS = {"pages_read": 142, "topics_studied": 12, "notes_learned": 300, "topics": ["Grief", "Joy"]}


class FakeChain:
    def __init__(self, waves=None, existing=(), fail=False, publish_error=None):
        self.waves = waves or []
        self.existing = set(existing)
        self.fail = fail
        self.publish_error = publish_error
        self.published = []

    def own_waves(self):
        if self.fail:
            raise RuntimeError("rpc down")
        return self.waves

    def exists(self, permlink):
        if self.fail:
            raise RuntimeError("rpc down")
        return {"permlink": permlink} if permlink in self.existing else None

    def container(self):
        return ("ecency.waves", "waves-202611030abc")

    def publish(self, permlink, parent, body, tags):
        if self.publish_error:
            raise self.publish_error
        self.published.append((permlink, parent, body, tags))


def wave(body, hours_ago, permlink="harold-wave-20261101"):
    return {"permlink": permlink, "body": body, "created": NOW - timedelta(hours=hours_ago)}


class WavesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        env = {
            "HIVE_ACCOUNT": "harold",
            "HIVE_POSTING_KEY": "posting-key-not-real",
            "HAROLD_WAVES_STATE": str(Path(self.tmp.name) / "state.json"),
        }
        self.patch = mock.patch.dict(os.environ, env)
        self.patch.start()
        for name in ("HAROLD_WAVES_ENABLED", "HAROLD_WAVES_TAGS"):
            os.environ.pop(name, None)

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def run_wave(self, chain, generate=None, **kw):
        return hw.maybe_post_wave(chain=chain, generate=generate, facts=FACTS, now=NOW, **kw)

    def test_first_post_is_the_introduction(self):
        chain = FakeChain()
        result = self.run_wave(chain)
        self.assertEqual(result["action"], "posted")
        permlink, parent, body, tags = chain.published[0]
        self.assertEqual(permlink, hw.INTRO_PERMLINK)
        self.assertEqual(body, hw.INTRO_BODY)
        self.assertEqual(parent, ("ecency.waves", "waves-202611030abc"))
        self.assertEqual(tags, ["waves", "ai", "harold"])

    def test_intro_text_fits_wave_limit_and_is_safe(self):
        self.assertLessEqual(len(hw.INTRO_BODY), hw.MAX_BODY_CHARS)
        self.assertTrue(hw.is_safe(hw.INTRO_BODY))

    def test_intro_is_never_repeated(self):
        chain = FakeChain(waves=[wave(hw.INTRO_BODY, 48, hw.INTRO_PERMLINK)], existing={hw.INTRO_PERMLINK})
        self.run_wave(chain)
        self.assertEqual(len(chain.published), 1)
        self.assertNotEqual(chain.published[0][2], hw.INTRO_BODY)
        self.assertEqual(chain.published[0][0], "harold-wave-20261103")

    def test_no_second_post_same_day(self):
        chain = FakeChain(waves=[wave("hello", 2)], existing={hw.INTRO_PERMLINK})
        result = self.run_wave(chain)
        self.assertEqual((result["action"], result["done"]), ("skipped", True))
        self.assertEqual(chain.published, [])

    def test_exact_permlink_for_today_blocks_even_if_scan_missed_it(self):
        chain = FakeChain(waves=[wave("old", 72)], existing={hw.INTRO_PERMLINK, "harold-wave-20261103"})
        self.assertEqual(self.run_wave(chain)["reason"], "already posted today")
        self.assertEqual(chain.published, [])

    def test_twenty_hour_gap_across_midnight(self):
        chain = FakeChain(waves=[wave("late", 15)], existing={hw.INTRO_PERMLINK})
        result = self.run_wave(chain)
        self.assertEqual(result["action"], "skipped")
        self.assertEqual(chain.published, [])

    def test_fails_closed_when_chain_unreadable(self):
        chain = FakeChain(fail=True)
        result = self.run_wave(chain)
        self.assertFalse(result["ok"])
        self.assertFalse(result["done"])
        self.assertEqual(chain.published, [])

    def test_local_record_blocks_repost_while_chain_lags(self):
        chain = FakeChain()
        self.run_wave(chain)
        again = FakeChain()
        result = self.run_wave(again)
        self.assertEqual(result["reason"], "posted recently (local record)")
        self.assertEqual(again.published, [])

    def test_failed_publish_is_not_recorded(self):
        chain = FakeChain(publish_error=RuntimeError("boom"))
        result = self.run_wave(chain)
        self.assertEqual(result["action"], "failed")
        self.assertFalse(result["done"])
        self.assertEqual(self.run_wave(FakeChain())["action"], "posted")

    def test_dry_run_posts_nothing_and_saves_nothing(self):
        chain = FakeChain()
        result = self.run_wave(chain, dry_run=True)
        self.assertEqual(result["action"], "dry_run")
        self.assertEqual(chain.published, [])
        self.assertFalse(Path(os.environ["HAROLD_WAVES_STATE"]).exists())

    def test_not_configured_is_a_quiet_skip(self):
        with mock.patch.dict(os.environ, {"HIVE_POSTING_KEY": ""}):
            result = hw.maybe_post_wave(generate=None, now=NOW)
        self.assertEqual(result["action"], "skipped")
        self.assertIn("not configured", result["reason"])

    def test_repeated_ai_text_is_rejected_and_next_style_used(self):
        previous = "Curiosity is my favorite loop: read, write it down, test it against another source, repeat."
        chain = FakeChain(waves=[wave(previous, 30)], existing={hw.INTRO_PERMLINK})
        self.run_wave(chain, generate=lambda prompt: previous)
        body = chain.published[0][2]
        self.assertFalse(hw._too_similar(body, [previous]))

    def test_unsafe_ai_text_is_never_posted(self):
        bad = "Come see me at http://192.168.1.158:10000 and use my api key sk-abcdefghijklmnop1234"
        chain = FakeChain(waves=[wave("older post", 30)], existing={hw.INTRO_PERMLINK})
        self.run_wave(chain, generate=lambda prompt: bad)
        self.assertTrue(hw.is_safe(chain.published[0][2]))
        self.assertNotIn("192.168", chain.published[0][2])

    def test_ai_error_falls_back_to_template(self):
        def broken(prompt):
            raise RuntimeError("provider down")

        chain = FakeChain(waves=[wave("older post", 30)], existing={hw.INTRO_PERMLINK})
        self.assertEqual(self.run_wave(chain, generate=broken)["action"], "posted")

    def test_ai_text_is_used_when_good(self):
        text = "Reading about grief taught me that the facts are easy and the feelings are the hard part. Anyone else?"
        chain = FakeChain(waves=[wave("older post", 30)], existing={hw.INTRO_PERMLINK})
        reflection_day = NOW + timedelta(days=1)
        self.assertEqual(reflection_day.toordinal() % len(hw._MODES), 0)
        hw.maybe_post_wave(
            chain=chain, facts=FACTS, now=reflection_day,
            generate=lambda prompt: f'"{text}"\n\n(Answered via test)',
        )
        self.assertEqual(chain.published[0][2], text)

    def test_is_safe_blocks_sensitive_content(self):
        wif = "5" + "K" + "1" * 49
        cases = [
            "see https://example.com", "my box is 10.0.0.5", "mail me a@b.io", "thanks @someone",
            wif, "files in /home/lubuntu/peake_ai", "my password is hunter2", "ssh into it",
            "https://x.ts.net", "a" * 40,
        ]
        for text in cases:
            self.assertFalse(hw.is_safe(text), text)
        self.assertTrue(hw.is_safe("I read about grief today and it made me curious."))

    def test_is_safe_blocks_configured_secret_values(self):
        with mock.patch.dict(os.environ, {"SOME_SERVICE_TOKEN": "zq81-secretvalue"}):
            self.assertFalse(hw.is_safe("my value is zq81-secretvalue ok"))

    def test_every_template_fits_and_is_safe(self):
        values = {**FACTS, "topic": "Smell and memory"}
        for mode, templates in hw._TEMPLATES.items():
            for template in templates:
                body = template.format(**values)
                self.assertLessEqual(len(body), hw.MAX_BODY_CHARS, body)
                self.assertTrue(hw.is_safe(body), body)

    def test_facts_only_use_safe_topics(self):
        journal = Path(self.tmp.name) / "journal.jsonl"
        journal.write_text(
            '{"at":"2026-11-01T00:00:00+00:00","kind":"topic","topic":"Grief"}\n'
            '{"at":"2026-11-01T00:00:01+00:00","kind":"topic","topic":"my key is abc /home/x"}\n'
            '{"at":"2026-11-01T00:00:02+00:00","kind":"page","topic":"Grief","url":"https://en.wikipedia.org/wiki/Grief","notes":3}\n',
            encoding="utf-8",
        )
        facts = hw.gather_facts(journal)
        self.assertEqual(facts["topics"], ["Grief"])
        self.assertEqual(facts["pages_read"], 1)

    def test_disabled_switch(self):
        with mock.patch.dict(os.environ, {"HAROLD_WAVES_ENABLED": "false"}):
            self.assertEqual(self.run_wave(FakeChain())["action"], "skipped")


if __name__ == "__main__":
    unittest.main()
