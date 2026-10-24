"""Pinned thresholds for recall quality, learned vocabulary, and lineage.

These tests exist to catch *regressions in behaviour that is easy to get
subtly wrong*: a ranking change that lets one common word dominate, an alias
rule that starts wiring unrelated ideas together, or a synthesis that loses
track of what it summarised.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import recall_benchmark
from memory_store import MemoryStore


class RecallBenchmarkTests(unittest.TestCase):
    def setUp(self) -> None:
        self._folder = tempfile.TemporaryDirectory()
        self.addCleanup(self._folder.cleanup)
        self.store, self.ids = recall_benchmark.build_store(self._folder.name)

    def test_precision_and_recall_meet_the_pinned_floor(self) -> None:
        report = recall_benchmark.evaluate(self.store, self.ids, k=3)
        self.assertGreaterEqual(report["precision@3"], 0.8, "a loosely related note is outranking a good one")
        self.assertGreaterEqual(report["recall@3"], 0.75, "relevant notes are being missed")
        self.assertEqual(report["false_associations"], 0, "shared category/common words are creating fake links")

    def test_archive_index_is_smaller_than_the_notes_it_covers(self) -> None:
        storage = recall_benchmark.measure_storage(self.store, self._folder.name)
        self.assertEqual(storage["notes"], len(recall_benchmark.CORPUS))
        self.assertGreater(storage["saved_bytes"], 0)
        # The index must stay well under the raw notes, or remote recall would
        # trade indexing cost for transfer cost without a win.
        self.assertLess(storage["index_bytes"], storage["raw_bytes"] * 0.95)


class RankingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._folder = tempfile.TemporaryDirectory()
        self.addCleanup(self._folder.cleanup)
        self.store = MemoryStore(Path(self._folder.name) / "memory.jsonl")

    def test_a_rare_shared_term_beats_repeated_common_words(self) -> None:
        common = "note about the project status update "
        self.store.add(common + "everything is on track", category="Work")
        self.store.add(common + "the team met again", category="Work")
        self.store.add(common + "budget review pending", category="Work")
        specific = self.store.add("Kelvin dashboard migration checklist", category="Projects")
        results = self.store.recall_details("kelvin migration", limit=3)["direct"]
        self.assertEqual(results[0]["id"], specific["i"])

    def test_connective_vocabulary_cannot_rank_a_note(self) -> None:
        consolidation = self.store.add(
            "Consolidated understanding from 2 note(s) (2 source id(s)): tea and sleep",
            category="Harold/Understanding/Consolidated",
        )
        unrelated = self.store.add("We bought a dining table", category="Personal")
        results = self.store.recall_details("consolidated understanding", limit=5)["related"]
        returned = [item["id"] for item in results]
        self.assertNotIn(unrelated["i"], returned)
        # The synthesis itself is a note, but it must not be *promoted* by the
        # words the system wrote for it.
        direct = [item["id"] for item in self.store.recall_details("consolidated understanding", limit=5)["direct"]]
        self.assertNotIn(consolidation["i"], direct)


class LearnedVocabularyTests(unittest.TestCase):
    def setUp(self) -> None:
        self._folder = tempfile.TemporaryDirectory()
        self.addCleanup(self._folder.cleanup)
        self.store = MemoryStore(Path(self._folder.name) / "memory.jsonl")

    def _learn(self, latest_only: bool = False) -> list[str]:
        """Learn from all notes, or just the newest (as the bot does per turn)."""
        learned: list[str] = []
        records = self.store.records[-1:] if latest_only else list(self.store.records)
        for record in records:
            learned += self.store._learn_aliases(record)
        return learned

    def test_repeated_restatement_is_learned_and_persisted(self) -> None:
        self.store.add("python scripting automates report cleanup", category="Knowledge")
        self.store.add("python scripting rewrites the nightly templates", category="Projects")
        self._learn(latest_only=True)
        # A third note names the same idea with "python" and no "scripting";
        # that is the restatement that makes the pair meaningful.
        self.store.add("python automates the dashboard export", category="Projects")
        learned = self._learn(latest_only=True)
        self.assertEqual(learned, ["ALIAS python => scripting"])
        # Evidence is ordinary notes, so a fresh process rebuilds the table.
        stub = MemoryStore(Path(self._folder.name) / "memory.jsonl")
        table = stub.alias_table(min_count=2)
        self.assertIn("scripting", table)
        self.assertIn("python", table["scripting"])

    def test_relearning_never_duplicates_evidence(self) -> None:
        self.store.add("python scripting automates report cleanup", category="Knowledge")
        self.store.add("python scripting rewrites the nightly templates", category="Projects")
        self._learn(latest_only=True)
        first = len(self.store.records)
        for _ in range(3):
            self.assertEqual(self._learn(latest_only=True), [])
        self.assertEqual(len(self.store.records), first, "the same pair must not be learned again")

    def test_one_mention_is_not_enough_to_learn_an_alias(self) -> None:
        # A single restatement is a guess; it must not change recall yet.
        self.store.add("python scripting automates report cleanup", category="Knowledge")
        self.store.add("python scripting rewrites the nightly templates", category="Projects")
        self.assertEqual(self._learn(), [])
        self.assertEqual(self.store.alias_table(min_count=1), {})

    def test_unrelated_notes_never_form_an_alias(self) -> None:
        self.store.add("python scripting automates report cleanup", category="Knowledge")
        self.store.add("The kitchen renovation quote arrived", category="Personal")
        self.assertEqual(self._learn(), [])
        self.assertEqual(self.store.alias_table(min_count=1), {})

    def test_validated_alias_is_used_by_recall(self) -> None:
        self.store.add("python scripting automates report cleanup", category="Knowledge")
        self.store.add("python scripting rewrites the nightly templates", category="Projects")
        self._learn(latest_only=True)
        python_only = self.store.add("python automates the reporting pipeline", category="Knowledge")
        self._learn(latest_only=True)
        # "scripting" is now a learned alias of "python", so this query reaches
        # a note that never uses the word "scripting".
        results = self.store.recall_details("scripting", limit=5)["direct"]
        self.assertIn(python_only["i"], [item["id"] for item in results])


class ConsolidationLineageTests(unittest.TestCase):
    def setUp(self) -> None:
        self._folder = tempfile.TemporaryDirectory()
        self.addCleanup(self._folder.cleanup)
        self.store = MemoryStore(Path(self._folder.name) / "memory.jsonl")

    def _three_related(self) -> list[dict]:
        return [
            self.store.add("sleep quality improves with consistent bedtime", category="Knowledge"),
            self.store.add("sleep schedule drifts on travel days", category="Personal"),
            self.store.add("bedtime routine helps sleep quality", category="Knowledge"),
        ]

    def test_synthesis_records_its_source_ids(self) -> None:
        sources = self._three_related()
        record = self.store.consolidate()
        self.assertIsNotNone(record)
        lineage = self.store.consolidation_sources(record["i"])
        self.assertEqual(set(lineage), {item["i"] for item in sources})
        self.assertIn("source id", record["n"])

    def test_recomputation_replaces_instead_of_piling_up(self) -> None:
        sources = self._three_related()
        first = self.store.consolidate()
        self.assertIsNotNone(first)
        second = self.store.consolidate()
        syntheses = [r for r in self.store.records if r.get("c") == "Harold/Understanding/Consolidated"]
        self.assertEqual(len(syntheses), 1, "re-running must not create a second synthesis")
        self.assertTrue(second.get("replaced"), "the second pass should report that it replaced the first")
        # The surviving synthesis must still name the real sources, not itself.
        self.assertEqual(
            set(self.store.consolidation_sources(second["i"])),
            {item["i"] for item in sources},
        )

    def test_synthesis_is_not_used_as_a_source_of_the_next_synthesis(self) -> None:
        sources = self._three_related()
        first = self.store.consolidate()
        second = self.store.consolidate()
        lineage = set(self.store.consolidation_sources(second["i"]))
        self.assertNotIn(first["i"], lineage)
        self.assertEqual(lineage, {item["i"] for item in sources})

    def test_removing_all_sources_prunes_the_synthesis(self) -> None:
        sources = self._three_related()
        record = self.store.consolidate()
        for source in sources:
            self.store.remove(source["i"])
        self.store.consolidate()
        remaining = [r for r in self.store.records if r["i"] == record["i"]]
        self.assertEqual(remaining, [])


if __name__ == "__main__":
    unittest.main()
