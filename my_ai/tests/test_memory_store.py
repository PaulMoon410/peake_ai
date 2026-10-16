import os
import ftplib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

# Ensure project root is in sys.path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from memory_store import MemoryLanguage, MemoryStore


class FakeFtp:
    def __init__(self, initial: bytes = b"") -> None:
        self.files = {"pocket-ai-memory.jsonl": initial} if initial else {}

    @property
    def data(self) -> bytes:
        return self.files.get("pocket-ai-memory.jsonl", b"")

    def sendcmd(self, command: str) -> str:
        return "200 type set"

    def size(self, path: str) -> int:
        if path not in self.files:
            raise ftplib.error_perm("550 File not found")
        return len(self.files[path])

    def storbinary(self, command: str, stream: object) -> None:
        operation, path = command.split(" ", 1)
        payload = stream.read()  # type: ignore[attr-defined]
        if operation == "APPE":
            self.files[path] = self.files.get(path, b"") + payload
        else:
            self.files[path] = payload

    def retrbinary(self, command: str, callback: object) -> None:
        _, path = command.split(" ", 1)
        if path not in self.files:
            raise ftplib.error_perm("550 File not found")
        if self.files[path]:
            callback(self.files[path])  # type: ignore[operator]

    def delete(self, path: str) -> None:
        self.files.pop(path, None)

    def quit(self) -> None:
        pass

    def close(self) -> None:
        pass


class MemoryStoreTests(unittest.TestCase):
    def test_add_deduplicates_and_recalls_matching_note(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = MemoryStore(Path(folder) / "memory.jsonl")
            first = store.add("I prefer concise Python examples")

            self.assertIsNotNone(first)
            self.assertIsNone(store.add("  I prefer concise Python examples  "))
            self.assertIn("concise Python examples", store.relevant("Please show Python examples"))
            self.assertEqual("", store.relevant("What is the weather today?"))
            self.assertEqual("user_reported_unverified", first["v"])

    def test_legacy_markdown_is_imported(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            legacy = root / "memory.md"
            legacy.write_text("- Prefers small code examples\n- Uses Python\n", encoding="utf-8")

            store = MemoryStore(root / "memory.jsonl", legacy)

            self.assertEqual(2, len(store.records))
            self.assertTrue((root / "memory.jsonl").is_file())
            self.assertIn("small code examples", store.relevant("code examples"))

    def test_note_size_is_limited(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = MemoryStore(Path(folder) / "memory.jsonl")
            with self.assertRaises(ValueError):
                store.add("x" * 501)

    def test_invalid_source_and_category_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = MemoryStore(Path(folder) / "memory.jsonl")

            with self.assertRaises(ValueError):
                store.add("A note", source="ftp://example.org/file")
            with self.assertRaises(ValueError):
                store.add("A note", category="Projects/../Secrets")

    def test_upload_does_not_exceed_configured_file_cap(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = MemoryStore(Path(folder) / "memory.jsonl")
            record = store.add("A small test note")
            assert record is not None
            payload_size = len(store._encode_record(record))
            store.max_remote_bytes = payload_size - 1
            ftp = FakeFtp()

            with patch.object(store, "_connect", return_value=ftp):
                with self.assertRaisesRegex(RuntimeError, "limit|exceed"):
                    store.upload(record)

            self.assertEqual(b"", ftp.data)

    def test_sync_preflights_all_uploads_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = MemoryStore(Path(folder) / "memory.jsonl")
            store.add("A small test note")
            store.max_remote_bytes = 10
            ftp = FakeFtp()

            with patch.object(store, "_connect", return_value=ftp):
                with self.assertRaisesRegex(RuntimeError, "limit|exceed"):
                    store.sync()

            self.assertEqual(b"", ftp.data)

    def test_porter_stemmer_matches_morphological_variants(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = MemoryStore(Path(folder) / "memory.jsonl")
            store.add("I prefer concise Python code")

            # "preferences" should match "prefer" via Porter stemming
            recalled = store.relevant("What are my coding preferences?")
            self.assertIn("concise Python code", recalled)

    def test_stopword_filter_avoids_false_positives(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = MemoryStore(Path(folder) / "memory.jsonl")
            store.add("I love it when it rains in April")

            # Common pronouns and verbs ("is", "it", "true") should not match
            recalled = store.relevant("Is it true?")
            self.assertEqual("", recalled)

    def test_memory_language_directives_and_tags(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = MemoryStore(Path(folder) / "memory.jsonl")

            # Directive @pref
            rec1 = store.add("@pref Always use type hints #python #style")
            self.assertIsNotNone(rec1)
            assert rec1 is not None
            self.assertEqual("Preferences", rec1["c"])
            self.assertIn("python", rec1["k"])
            self.assertIn("style", rec1["k"])

            # Directive @proj:Website
            rec2 = store.add("@proj:Website The site uses dark mode rel:Preferences")
            self.assertIsNotNone(rec2)
            assert rec2 is not None
            self.assertEqual("Projects/Website", rec2["c"])
            self.assertIn("preferences", rec2["k"])

            # Query with category filter cat:Preferences
            cat_query = store.relevant("cat:Preferences type hints")
            self.assertIn("Always use type hints", cat_query)
            self.assertNotIn("The site uses dark mode", cat_query)

    def test_remove_memory_by_id_and_text(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = MemoryStore(Path(folder) / "memory.jsonl")
            rec = store.add("Test note to be forgotten")
            assert rec is not None
            self.assertEqual(1, len(store.records))

            # Remove by text
            removed = store.remove("forgotten")
            self.assertIsNotNone(removed)
            assert removed is not None
            self.assertEqual(rec["i"], removed["i"])
            self.assertEqual(0, len(store.records))
            self.assertEqual("", store.relevant("forgotten"))

    def test_import_text_and_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = MemoryStore(Path(folder) / "memory.jsonl")
            sample_md = """# Architecture
Pocket AI uses local llama.cpp for inference.

# Memory
Notes are stored in compact JSON Lines format.
"""
            count = store.import_text(sample_md, category_prefix="Docs", source_name="Guide")
            self.assertEqual(2, count)
            self.assertEqual(2, len(store.records))
            self.assertIn("Docs/Architecture", [r["c"] for r in store.records])
            self.assertIn("Docs/Memory", [r["c"] for r in store.records])

    def test_recall_details_structure(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = MemoryStore(Path(folder) / "memory.jsonl")
            store.add("Build CLI tools with Python")
            details = store.recall_details("Python CLI")

            self.assertEqual("Python CLI", details["query"])
            self.assertIn("python", details["terms"])
            self.assertIn("cli", details["terms"])
            self.assertEqual(1, len(details["direct"]))  # type: ignore[arg-type]

    def test_remote_recall_reads_multiple_capped_shards_without_expanding_local_cache(self) -> None:
        env = {
            "MEMORY_FTP_HOST": "example.invalid",
            "MEMORY_FTP_USER": "test-user",
            "MEMORY_FTP_PASSWORD": "test-password",
            "MEMORY_LOCAL_CACHE_RECORDS": "1",
        }
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, env):
            store = MemoryStore(Path(folder) / "memory.jsonl")
            first = store.add("Python coding integration", category="Projects/Agent")
            second = store.add("Ollama tooling rel:Projects/Agent", category="Tools")
            assert first is not None and second is not None
            payloads = [store._encode_record(first), store._encode_record(second)]
            store.max_remote_bytes = max(map(len, payloads))
            self.assertEqual(1, len(store.records))

            ftp = FakeFtp()
            with patch.object(store, "_connect", return_value=ftp):
                store.upload(first)
                store.upload(second)
                remote_result = store.relevant_remote("Python coding")
                categories = store.remote_categories()

            self.assertIn("Python coding integration", remote_result)
            self.assertIn("Ollama tooling", remote_result)
            self.assertIn("RELATED", remote_result)
            self.assertEqual(["Projects/Agent", "Tools"], categories)
            self.assertEqual(1, len(store.records))
            self.assertEqual(1, len((Path(folder) / "memory.jsonl").read_text(encoding="utf-8").splitlines()))
            self.assertEqual(2, len([name for name in ftp.files if name.startswith("pocket-ai-memory.jsonl")]))

    def test_sync_keeps_local_cache_bounded_while_reading_sharded_archive(self) -> None:
        env = {
            "MEMORY_FTP_HOST": "example.invalid",
            "MEMORY_FTP_USER": "test-user",
            "MEMORY_FTP_PASSWORD": "test-password",
            "MEMORY_LOCAL_CACHE_RECORDS": "1",
        }
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, env):
            store = MemoryStore(Path(folder) / "memory.jsonl")
            remote_records = [
                {"i": "aaaaaaaaaaaa", "d": "2026-01-01", "c": "A", "k": "one", "n": "first remote note", "s": "", "v": "user_reported_unverified"},
                {"i": "bbbbbbbbbbbb", "d": "2026-01-02", "c": "B", "k": "two", "n": "second remote note", "s": "", "v": "user_reported_unverified"},
            ]
            payloads = [store._encode_record(record) for record in remote_records]
            store.max_remote_bytes = max(map(len, payloads))
            ftp = FakeFtp(payloads[0])
            ftp.files["pocket-ai-memory.jsonl.000001"] = payloads[1]

            with patch.object(store, "_connect", return_value=ftp):
                remote_added, uploaded = store.sync()

            self.assertEqual(2, remote_added)
            self.assertEqual(0, uploaded)
            self.assertEqual(1, len(store.records))
            self.assertEqual("second remote note", store.records[0]["n"])

    def test_remove_can_delete_remote_only_note_after_local_eviction(self) -> None:
        env = {
            "MEMORY_FTP_HOST": "example.invalid",
            "MEMORY_FTP_USER": "test-user",
            "MEMORY_FTP_PASSWORD": "test-password",
            "MEMORY_LOCAL_CACHE_RECORDS": "1",
        }
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, env):
            store = MemoryStore(Path(folder) / "memory.jsonl")
            records = [
                {"i": "aaaaaaaaaaaa", "d": "2026-01-01", "c": "A", "k": "one", "n": "first remote note", "s": "", "v": "user_reported_unverified"},
                {"i": "bbbbbbbbbbbb", "d": "2026-01-02", "c": "B", "k": "two", "n": "second remote note", "s": "", "v": "user_reported_unverified"},
            ]
            payloads = [store._encode_record(record) for record in records]
            store.max_remote_bytes = max(map(len, payloads))
            ftp = FakeFtp(payloads[0])
            ftp.files["pocket-ai-memory.jsonl.000001"] = payloads[1]

            with patch.object(store, "_connect", return_value=ftp):
                self.assertEqual(2, len(store._read_remote_records()))
                removed = store.remove("aaaaaaaaaaaa")
                remaining = store._read_remote_records()

            self.assertIsNotNone(removed)
            self.assertEqual(["bbbbbbbbbbbb"], [record["i"] for record in remaining])
            self.assertNotIn("pocket-ai-memory.jsonl.000001", ftp.files)


if __name__ == "__main__":
    unittest.main()
