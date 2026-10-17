from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import ANY, patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from my_ai.harold.evidence import SourceResearcher
from my_ai.memory_store import MemoryStore


class FakeEvidenceFetcher:
    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages

    def page(self, url: str):
        return SimpleNamespace(url=url, text=self.pages[url])


class HaroldEvidenceTests(unittest.TestCase):
    def test_extracts_compares_all_sources_and_saves_each_source_url(self) -> None:
        passage = (
            "Sleep supports attention, learning, and memory, and regular sleep helps people "
            "recover from demanding daily activities."
        )
        html = f"<html><title>Sleep and memory</title><main><p>{passage}</p></main></html>"
        urls = [
            "https://one.example.com/sleep",
            "https://two.example.net/research",
            "https://three.example.org/guide",
        ]
        with tempfile.TemporaryDirectory() as folder:
            store = MemoryStore(Path(folder) / "memory.jsonl")
            researcher = SourceResearcher(store, FakeEvidenceFetcher({url: html for url in urls}))  # type: ignore[arg-type]

            report = researcher.learn("sleep memory", urls)

            self.assertEqual(3, report.notes_added)
            self.assertEqual(3, len(report.corroborations))
            self.assertEqual({*urls}, {record["s"] for record in store.records})
            self.assertTrue(all(record["c"].startswith("Harold/Research/") for record in store.records))

    def test_accepts_four_sources_but_rejects_more_than_four(self) -> None:
        passage = "Sleep supports attention, learning, and memory during demanding everyday activities."
        html = f"<main><p>{passage}</p></main>"
        urls = [
            "https://one.example.com/sleep",
            "https://two.example.net/sleep",
            "https://three.example.org/sleep",
            "https://four.example.edu/sleep",
        ]
        with tempfile.TemporaryDirectory() as folder:
            store = MemoryStore(Path(folder) / "memory.jsonl")
            researcher = SourceResearcher(store, FakeEvidenceFetcher({url: html for url in urls}))  # type: ignore[arg-type]

            report = researcher.learn("sleep", urls)

            self.assertEqual(4, len(report.pages))
            with self.assertRaisesRegex(ValueError, "two to 4"):
                researcher.learn("sleep", urls + ["https://five.example.info/sleep"])

    def test_uploads_all_source_excerpts_in_one_batch(self) -> None:
        passage = "Sleep supports attention, learning, and memory during demanding everyday activities."
        html = f"<main><p>{passage}</p></main>"
        urls = ["https://one.example.com/sleep", "https://two.example.net/sleep"]
        with tempfile.TemporaryDirectory() as folder:
            store = MemoryStore(Path(folder) / "memory.jsonl")
            store.ftp_host = "ftp.example.test"
            store.ftp_user = "test-user"
            store.ftp_password = "test-password"
            researcher = SourceResearcher(store, FakeEvidenceFetcher({url: html for url in urls}))  # type: ignore[arg-type]

            with patch.object(store, "upload_many", return_value=2) as upload_many:
                report = researcher.learn("sleep", urls)

            upload_many.assert_called_once_with(ANY, timeout=5.0)
            records = upload_many.call_args.args[0]
            self.assertEqual({*urls}, {record["s"] for record in records})
            self.assertEqual(2, report.notes_uploaded)

    def test_refuses_two_sources_from_the_same_registrable_domain(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = MemoryStore(Path(folder) / "memory.jsonl")
            researcher = SourceResearcher(store, FakeEvidenceFetcher({}))  # type: ignore[arg-type]

            with self.assertRaisesRegex(ValueError, "distinct registrable domains"):
                researcher.learn("sleep", [
                    "https://one.example.com/article",
                    "https://two.example.com/report",
                ])

    def test_nonmatching_passages_are_not_reported_as_corroborated(self) -> None:
        first = "Sleep supports attention, learning, and memory during ordinary daily activities."
        second = "Sleep research describes patterns and schedules observed in controlled laboratory settings."
        urls = ["https://one.example.com/sleep", "https://two.example.net/research"]
        html_pages = {
            urls[0]: f"<main><p>{first}</p></main>",
            urls[1]: f"<main><p>{second}</p></main>",
        }
        with tempfile.TemporaryDirectory() as folder:
            researcher = SourceResearcher(
                MemoryStore(Path(folder) / "memory.jsonl"), FakeEvidenceFetcher(html_pages),  # type: ignore[arg-type]
            )

            report = researcher.learn("sleep", urls)

        self.assertEqual(2, report.notes_added)
        self.assertEqual((), report.corroborations)


if __name__ == "__main__":
    unittest.main()