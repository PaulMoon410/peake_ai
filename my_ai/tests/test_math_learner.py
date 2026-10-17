from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from math_learner import MathLearner
from memory_store import MemoryStore


class MathLearnerTests(unittest.TestCase):
    def test_learn_verifies_and_stores_arithmetic(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = MemoryStore(Path(folder) / "memory.jsonl")
            learner = MathLearner(store)
            fact = learner.learn("2 + 2")
            self.assertIsNotNone(fact)
            assert fact is not None
            self.assertTrue(fact.verified)
            self.assertEqual(fact.result, "4")
            facts = learner.facts()
            self.assertEqual(len(facts), 1)
            self.assertEqual(facts[0].expression, "2 + 2")

    def test_recall_queries_math_category(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = MemoryStore(Path(folder) / "memory.jsonl")
            learner = MathLearner(store)
            learner.learn("area of a circle is pi r squared")
            learner.learn("2 + 2 = 4")
            recalled = learner.recall("circle")
            self.assertIn("circle", recalled)

    def test_unverified_statement_is_stored_but_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = MemoryStore(Path(folder) / "memory.jsonl")
            learner = MathLearner(store)
            fact = learner.learn("love is patient")
            self.assertIsNotNone(fact)
            assert fact is not None
            self.assertFalse(fact.verified)
            facts = learner.facts()
            self.assertEqual(len(facts), 1)
            self.assertFalse(facts[0].verified)

    def test_evaluate_returns_result_for_valid_expression(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = MemoryStore(Path(folder) / "memory.jsonl")
            learner = MathLearner(store)
            self.assertEqual(learner.evaluate("10 / 2"), "5")
            self.assertIsNone(learner.evaluate("not math"))

    def test_natural_language_number_is_not_marked_as_verified_arithmetic(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            learner = MathLearner(MemoryStore(Path(folder) / "memory.jsonl"))

            fact = learner.learn("A triangle has 3 sides")

            self.assertIsNotNone(fact)
            assert fact is not None
            self.assertFalse(fact.verified)

    def test_evaluator_rejects_power_operator_without_computing_it(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            learner = MathLearner(MemoryStore(Path(folder) / "memory.jsonl"))

            self.assertIsNone(learner.evaluate("2 ** 1000000000"))

    def test_learn_persists_across_stores(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "memory.jsonl"
            learner = MathLearner(MemoryStore(path))
            learner.learn("3 * 3")
            # Reload: facts survive because they are stored as notes.
            learner2 = MathLearner(MemoryStore(path))
            self.assertEqual(len(learner2.facts()), 1)
            self.assertEqual(learner2.facts()[0].result, "9")


if __name__ == "__main__":
    unittest.main()
