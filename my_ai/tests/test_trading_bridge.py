from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from my_ai.memory_store import MemoryStore
from my_ai.trading_bridge import TradingBridge


class TradingBridgeTests(unittest.TestCase):
    def make_bridge(self, folder: str, responder=None) -> TradingBridge:
        store = MemoryStore(Path(folder) / "memory.jsonl")
        return TradingBridge(store, responder=responder)

    def test_learn_mechanism_stores_under_trading_category(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            bridge = self.make_bridge(folder)
            bridge.learn_mechanism(
                "btc-rsi-bounce", "Buy oversold RSI bounces in BTC 1h",
                market="BTC/USDT", timeframe="1h", tags=["rsi", "mean-reversion"],
            )
            categories = {record["c"] for record in bridge.store.records}
            self.assertEqual({"Trading/Mechanisms"}, categories)

    def test_outcomes_aggregate_into_win_rate(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            bridge = self.make_bridge(folder)
            bridge.learn_mechanism("btc-rsi-bounce", "Oversold bounce", market="BTC/USDT", timeframe="1h")
            bridge.record_outcome("btc-rsi-bounce", "target hit", pnl=2.0)
            bridge.record_outcome("btc-rsi-bounce", "target hit", pnl=1.5)
            bridge.record_outcome("btc-rsi-bounce", "stopped out", pnl=-1.0)

            stats = bridge.mechanism_stats("btc-rsi-bounce")
            self.assertEqual(2, stats["wins"])
            self.assertEqual(1, stats["losses"])
            self.assertEqual(3, stats["observations"])
            self.assertAlmostEqual(2 / 3, stats["win_rate"], places=3)
            self.assertAlmostEqual(2.5, stats["total_pnl"], places=3)

    def test_lesson_is_attached_to_mechanism(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            bridge = self.make_bridge(folder)
            bridge.learn_mechanism("btc-rsi-bounce", "Oversold bounce", market="BTC/USDT")
            bridge.record_lesson("btc-rsi-bounce", "Filter for an uptrending higher timeframe.")

            stats = bridge.mechanism_stats("btc-rsi-bounce")
            self.assertEqual(1, len(stats["lessons"]))
            self.assertIn("uptrending", stats["lessons"][0])

    def test_advise_uses_responder_with_learned_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            captured = {}

            def responder(prompt: str) -> str:
                captured["prompt"] = prompt
                return "Hold and wait for the higher-timeframe trend to confirm."

            bridge = self.make_bridge(folder, responder=responder)
            bridge.learn_mechanism("btc-rsi-bounce", "Oversold bounce", market="BTC/USDT", timeframe="1h")
            bridge.record_outcome("btc-rsi-bounce", "target hit", pnl=2.0)

            advice = bridge.advise({"market": "BTC/USDT", "timeframe": "1h"}, "RSI at 27, hold or exit?")
            self.assertIn("higher-timeframe trend", advice.advice)
            self.assertIn("btc-rsi-bounce", captured["prompt"])
            self.assertEqual(1, len(advice.mechanisms))
            self.assertGreater(advice.confidence, 0.0)

    def test_advise_without_matching_mechanism_refuses_to_steer(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            bridge = self.make_bridge(folder, responder=lambda prompt: "should not be used")
            advice = bridge.advise({"market": "ETH/USDT", "timeframe": "4h"}, "what now?")
            self.assertEqual(0, len(advice.mechanisms))
            self.assertEqual(0.0, advice.confidence)
            self.assertIn("not learned any trading mechanism", advice.advice)

    def test_recall_ranks_matching_market_first(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            bridge = self.make_bridge(folder)
            bridge.learn_mechanism("btc-bounce", "BTC oversold bounce", market="BTC/USDT", timeframe="1h")
            bridge.learn_mechanism("eth-breakout", "ETH breakout continuation", market="ETH/USDT", timeframe="1h")

            results = bridge.recall_mechanisms(query="bounce", market="BTC/USDT", timeframe="1h")
            self.assertTrue(results)
            self.assertEqual("btc-bounce", results[0].key)

    def test_summary_reports_aggregate_stats(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            bridge = self.make_bridge(folder)
            bridge.learn_mechanism("m1", "First mechanism")
            bridge.record_outcome("m1", "target hit", pnl=1.0)
            summary = bridge.summary()
            self.assertEqual(1, summary["mechanisms"])
            self.assertEqual(1, summary["observations"])
            self.assertEqual(1, summary["wins"])


if __name__ == "__main__":
    unittest.main()
