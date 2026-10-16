from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harold.agent import HaroldAgent, HaroldConfig, _Budget
from harold.curator import MemoryCandidate
from harold.discovery import Candidate
from harold.journal import Journal
from memory_store import MemoryStore


class FakeFetcher:
    def page(self, url: str):
        paragraph = (
            "People describe grief as a difficult emotional experience that affects sleep, "
            "memory, family relationships, and daily routines after a loss. "
        )
        html = f"<html><title>Grief</title><main><p>{paragraph * 6}</p></main></html>"
        return type("Fetched", (), {"url": url, "text": html})()


class FakeDiscovery:
    def __init__(self) -> None:
        self.seen: list[str] = []

    def for_url(self, url: str, title: str = "") -> list[Candidate]:
        return [Candidate(url=url, title=title, origin="direct")]

    def mark_seen(self, url: str) -> None:
        self.seen.append(url)


class FakeCurator:
    def distill(self, topic, page, source_url: str) -> list[MemoryCandidate]:
        return [MemoryCandidate(
            note="People describe grief as affecting sleep, memory, and ordinary routines after a loss.",
            topic=topic.name,
            source_url=source_url,
            generated_by="test",
        )]


class HaroldAgentTests(unittest.TestCase):
    def test_budget_enforces_session_and_per_host_caps(self) -> None:
        budget = _Budget(pages_left=2, pages_per_host=1)

        self.assertTrue(budget.take("example.org"))
        self.assertFalse(budget.take("EXAMPLE.ORG"))
        self.assertTrue(budget.take("other.org"))
        self.assertFalse(budget.take("third.org"))

    def test_learn_url_fetches_and_stores_curated_note(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = MemoryStore(Path(folder) / "memory.jsonl")
            journal = Journal(Path(folder) / "journal.jsonl")
            discovery = FakeDiscovery()
            agent = HaroldAgent(
                store,
                config=HaroldConfig(journal_path=Path(folder) / "journal.jsonl"),
                fetcher=FakeFetcher(),  # type: ignore[arg-type]
                discovery=discovery,  # type: ignore[arg-type]
                curator=FakeCurator(),  # type: ignore[arg-type]
                journal=journal,
            )

            report = agent.learn_url("https://example.org/grief", "Grief")

            self.assertEqual("Grief", report.topic)
            self.assertEqual(1, report.notes_added)
            self.assertEqual("Harold/Observations/Emotions", store.records[0]["c"])
            self.assertIn("grief", store.records[0]["n"].casefold())
            self.assertEqual(["https://example.org/grief"], discovery.seen)
            self.assertGreater(journal.stats()["pages_read"], 0)


if __name__ == "__main__":
    unittest.main()