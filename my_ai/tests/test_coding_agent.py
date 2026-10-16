from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from coding_agent import CodingWorkspace, run_coding_agent


class CodingWorkspaceTests(unittest.TestCase):
    def test_memory_recall_tool_uses_injected_ftp_retriever(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            workspace = CodingWorkspace(
                Path(folder),
                memory_recall=lambda query: f"remote notes for {query}",
                memory_categories=lambda: ["Projects/Agent", "Tools"],
            )

            recalled = workspace.call_tool("recall_memory", {"query": "cat:Projects Python"})
            categories = workspace.call_tool("memory_categories", {})

            self.assertEqual("remote notes for cat:Projects Python", recalled)
            self.assertEqual("Projects/Agent\nTools", categories)

    def test_read_file_stays_inside_project_and_blocks_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "main.py").write_text("print('ok')\n", encoding="utf-8")
            (root / ".env").write_text("TOKEN=secret\n", encoding="utf-8")
            (root / "config.txt").symlink_to(root / ".env")
            workspace = CodingWorkspace(root)

            self.assertEqual("print('ok')\n", workspace.read_file("main.py"))
            with self.assertRaisesRegex(ValueError, "secret"):
                workspace.read_file(".env")
            with self.assertRaisesRegex(ValueError, "secret"):
                workspace.read_file("config.txt")
            with self.assertRaisesRegex(ValueError, "traversal"):
                workspace.read_file("../outside.txt")

    def test_list_files_excludes_secrets_and_ignored_directories(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "main.py").write_text("pass\n", encoding="utf-8")
            (root / ".env").write_text("TOKEN=secret\n", encoding="utf-8")
            (root / "runtime").mkdir()
            (root / "runtime" / "model.bin").write_bytes(b"binary")
            listing = CodingWorkspace(root).list_files()

            self.assertIn("main.py", listing)
            self.assertNotIn(".env", listing)
            self.assertNotIn("runtime", listing)

    def test_proposed_edit_requires_approval(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = root / "main.py"
            target.write_text("old\n", encoding="utf-8")
            workspace = CodingWorkspace(root)

            with patch("builtins.input", return_value="no"):
                result = workspace.propose_edit("main.py", "new\n", "test")

            self.assertIn("declined", result)
            self.assertEqual("old\n", target.read_text(encoding="utf-8"))

    def test_approved_edit_is_written(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            workspace = CodingWorkspace(root)

            with patch("builtins.input", return_value="yes"):
                result = workspace.propose_edit("src/main.py", "print('ok')\n", "create file")

            self.assertIn("Applied", result)
            self.assertEqual("print('ok')\n", (root / "src" / "main.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()