from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot_builder import generate_bot, list_templates


class BotBuilderTests(unittest.TestCase):
    def test_list_templates_returns_expected_types(self) -> None:
        templates = list_templates()
        types = {t["type"] for t in templates}
        self.assertIn("curation", types)
        self.assertIn("posting", types)
        self.assertIn("transfers", types)
        self.assertIn("engine_trader", types)

    def test_generate_bot_creates_complete_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            dest = generate_bot("curation", "test_curator", target_dir=Path(tmp_dir))
            self.assertTrue(dest.is_dir())
            self.assertTrue((dest / "curation_bot.py").is_file())
            self.assertTrue((dest / ".env.example").is_file())
            self.assertTrue((dest / "requirements.txt").is_file())
            self.assertTrue((dest / "README.md").is_file())

            code = (dest / "curation_bot.py").read_text(encoding="utf-8")
            self.assertIn("beem", code)
            self.assertIn("HIVE_POSTING_KEY", code)

    def test_generate_bot_invalid_type_raises_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with self.assertRaises(ValueError):
                generate_bot("nonexistent_type", "my_bot", target_dir=Path(tmp_dir))


if __name__ == "__main__":
    unittest.main()

