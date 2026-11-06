from pathlib import Path
import io
import json
import os
import re
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from my_ai import memory_store
import my_ai.memory_store as memory_store_module

_fake_language_model = types.ModuleType("language_model")


class _FakeLanguageModel:
    def load_model(self, *_args: object) -> bool:
        return True

    def generate_response(self, *args, **kwargs):
        return "fake model response"


_fake_language_model.NeuralLanguageModel = _FakeLanguageModel  # type: ignore[attr-defined]
_fake_language_model.create_training_data = lambda: ["hello world", "how are you"]  # type: ignore[attr-defined]
_test_ftp_env = {
    "FTP_HOST": "<REDACTED_FTP_HOST>",
    "FTP_USER": "<REDACTED_FTP_USER>",
    "FTP_PASS": "<REDACTED_FTP_PASS>",
}
with patch.dict(sys.modules, {"language_model": _fake_language_model}), patch.dict(os.environ, _test_ftp_env):
    import peakebot


class FakeFTP:
    """Minimal in-memory FTP double that records stored files."""

    def __init__(self, files=None):
        self.files = dict(files or {})
        self.stored = {}
        self.pasv = True
        self.fail_passive = False

    def connect(self, host=None, timeout=None):
        return "220 OK"

    def login(self, user, password):
        return "230 OK"

    def set_pasv(self, flag):
        self.pasv = flag

    def cwd(self, path):
        return path

    def mkd(self, path):
        return path

    def nlst(self):
        return sorted(self.files.keys())

    def quit(self):
        pass

    def close(self):
        pass

    def storbinary(self, command, data):
        name = command.split(" ", 1)[1]
        payload = data.read()
        if self.fail_passive and self.pasv:
            raise OSError("passive data channel refused")
        self.stored[name] = payload
        return len(payload)

    def retrbinary(self, command, callback):
        name = command.split(" ", 1)[1]
        if name not in self.files:
            raise peakebot.ftplib.error_perm("550 No such file")
        payload = self.files[name]
        callback(payload)
        return len(payload)


class FakeStore:
    """MCF3 store double for the startup sync."""

    def __init__(self, configured=True):
        self.ftp_configured = configured
        self.ftp_tls = False
        self.ftp_host = "ftp.example.invalid"
        self.sync_result = (3, 2)
        self.sync_calls = 0

    def sync(self):
        self.sync_calls += 1
        return self.sync_result


class FtpArchiveTests(unittest.TestCase):
    def setUp(self):
        self._saved = (peakebot.FTP_HOST, peakebot.FTP_USER, peakebot.FTP_PASS, peakebot.FTP_BASE_DIR)
        peakebot.FTP_HOST = "ftp.example.invalid"
        peakebot.FTP_USER = "user"
        peakebot.FTP_PASS = "secret"
        peakebot.FTP_BASE_DIR = "/"
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._orig_tmp_path = peakebot._tmp_path
        peakebot._tmp_path = lambda name: os.path.join(self._tmp.name, name)
        self.addCleanup(lambda: setattr(peakebot, "_tmp_path", self._orig_tmp_path))

    def tearDown(self):
        peakebot.FTP_HOST, peakebot.FTP_USER, peakebot.FTP_PASS, peakebot.FTP_BASE_DIR = self._saved

    # -- credential readiness ----------------------------------------------
    def test_placeholder_credentials_are_rejected(self) -> None:
        peakebot.FTP_HOST = "<REDACTED_FTP_HOST>"
        peakebot.FTP_USER = "<REDACTED_FTP_USER>"
        peakebot.FTP_PASS = "<REDACTED_FTP_PASS>"
        ready, problem = peakebot._ftp_credentials_ready()
        self.assertFalse(ready)
        self.assertIn("FTP_HOST", problem)
        self.assertIn("FTP_PASS", problem)

    def test_real_credentials_are_accepted(self) -> None:
        ready, problem = peakebot._ftp_credentials_ready()
        self.assertTrue(ready)
        self.assertEqual(problem, "")

    def test_missing_credentials_are_reported(self) -> None:
        peakebot.FTP_PASS = ""
        ready, problem = peakebot._ftp_credentials_ready()
        self.assertFalse(ready)
        self.assertIn("FTP_PASS is empty", problem)

    def test_placeholder_base_dir_resolves_to_root(self) -> None:
        peakebot.FTP_BASE_DIR = "<REDACTED_FTP_BASE_DIR>"
        self.assertEqual(peakebot._resolved_ftp_base_dir(), "/")

    # -- session log discovery ---------------------------------------------
    def test_local_session_entries_merge_every_candidate_file(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            first = Path(folder) / "a.json"
            second = Path(folder) / "b.json"
            shared = {"timestamp": "2026-01-01T00:00:00", "prompt": "hi", "response": "hello"}
            first.write_text(json.dumps([shared]), encoding="utf-8")
            second.write_text(
                json.dumps([shared, {"timestamp": "2026-01-02T00:00:00", "prompt": "b", "response": "c"}]),
                encoding="utf-8",
            )
            with patch.object(peakebot, "_session_log_candidates", return_value=[str(first), str(second)]):
                entries = peakebot._load_local_session_entries()
        self.assertEqual(len(entries), 2)

    def test_remember_appends_to_an_existing_history_file(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "history.json"
            target.write_text(json.dumps([{"timestamp": "2026-01-01T00:00:00", "prompt": "old", "response": "kept"}]), encoding="utf-8")
            with (
                patch.object(peakebot, "_session_log_candidates", return_value=[str(target)]),
                patch.object(peakebot, "_SENSITIVE_MEMORY_RE", new=re.compile(r"(?!x)x")),
                patch.object(peakebot, "_queue_online_learning"),
                patch.object(peakebot, "_flush_pending_ftp_uploads"),
            ):
                peakebot.remember("hello", "hi there")
            saved = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(len(saved), 2)
        self.assertEqual(saved[-1]["prompt"], "hello")

    def test_missing_history_file_does_not_crash_remember(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "history.json"
            with (
                patch.object(peakebot, "_session_log_write_path", return_value=str(target)),
                patch.object(peakebot, "_SENSITIVE_MEMORY_RE", new=re.compile(r"(?!x)x")),
                patch.object(peakebot, "_queue_online_learning"),
                patch.object(peakebot, "_flush_pending_ftp_uploads"),
            ):
                peakebot.remember("hello", "hi there")
            saved = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["prompt"], "hello")

    # -- archive sync -------------------------------------------------------
    def test_sync_uploads_entries_under_their_original_day(self) -> None:
        entries = [
            {"timestamp": "2026-03-01T10:00:00", "prompt": "one", "response": "1"},
            {"timestamp": "2026-03-01T11:00:00", "prompt": "two", "response": "2"},
            {"timestamp": "2026-03-02T09:00:00", "prompt": "three", "response": "3"},
        ]
        uploaded: dict[str, list] = {}

        def fake_save(items, day_str=None):
            uploaded.setdefault(day_str, []).extend(items)
            return True

        with (
            patch.object(peakebot, "_load_local_session_entries", return_value=entries),
            patch.object(peakebot, "_remote_daily_entry_keys", return_value=set()),
            patch.object(peakebot, "save_to_geocities", side_effect=fake_save),
            patch.object(peakebot, "_get_mcf_memory_store", return_value=FakeStore()),
        ):
            report = peakebot.upload_missing_session_logs()

        self.assertTrue(report["ok"])
        self.assertEqual(report["conversation_entries"], 3)
        self.assertEqual(report["conversation_days"], 2)
        self.assertEqual(len(uploaded["20260301"]), 2)
        self.assertEqual(len(uploaded["20260302"]), 1)

    def test_sync_skips_entries_already_present_on_ftp(self) -> None:
        known = {"timestamp": "2026-03-01T10:00:00", "prompt": "one", "response": "1"}
        entries = [
            known,
            {"timestamp": "2026-03-01T11:00:00", "prompt": "two", "response": "2"},
        ]
        uploaded: dict[str, list] = {}

        def fake_save(items, day_str=None):
            uploaded.setdefault(day_str, []).extend(items)
            return True

        with (
            patch.object(peakebot, "_load_local_session_entries", return_value=entries),
            patch.object(peakebot, "_remote_daily_entry_keys", return_value={peakebot._entry_key(known)}),
            patch.object(peakebot, "save_to_geocities", side_effect=fake_save),
            patch.object(peakebot, "_get_mcf_memory_store", return_value=FakeStore()),
        ):
            report = peakebot.upload_missing_session_logs()

        self.assertTrue(report["ok"])
        self.assertEqual(report["conversation_entries"], 1)
        self.assertEqual(len(uploaded["20260301"]), 1)
        self.assertEqual(uploaded["20260301"][0]["prompt"], "two")

    def test_sync_is_skipped_when_credentials_are_placeholders(self) -> None:
        peakebot.FTP_HOST = "<REDACTED_FTP_HOST>"
        with patch.object(peakebot, "save_to_geocities") as save:
            report = peakebot.upload_missing_session_logs()
        self.assertFalse(report["ok"])
        self.assertTrue(report["errors"])
        save.assert_not_called()

    def test_sync_reports_note_upload_and_pull_counts(self) -> None:
        store = FakeStore()
        store.sync_result = (5, 4)
        with (
            patch.object(peakebot, "_load_local_session_entries", return_value=[]),
            patch.object(peakebot, "_get_mcf_memory_store", return_value=store),
        ):
            report = peakebot.upload_missing_session_logs()
        self.assertEqual(report["notes_uploaded"], 4)
        self.assertEqual(report["notes_pulled"], 5)
        self.assertEqual(store.sync_calls, 1)

    def test_sync_survives_a_failing_note_store(self) -> None:
        class BrokenStore(FakeStore):
            def sync(self):
                raise RuntimeError("shard unreachable")

        with (
            patch.object(peakebot, "_load_local_session_entries", return_value=[]),
            patch.object(peakebot, "_get_mcf_memory_store", return_value=BrokenStore()),
        ):
            report = peakebot.upload_missing_session_logs()
        self.assertFalse(report["ok"])
        self.assertTrue(any("note sync failed" in err for err in report["errors"]))

    # -- day aware writes ---------------------------------------------------
    def test_save_to_geocities_writes_into_the_pinned_day(self) -> None:
        ftp = FakeFTP()
        entries = [{"timestamp": "2026-03-01T10:00:00", "prompt": "one", "response": "1"}]
        with patch.object(peakebot, "FTP", return_value=ftp):
            ok = peakebot.save_to_geocities(entries, day_str="20260301")
        self.assertTrue(ok)
        self.assertIn("knowledge_20260301_part1.json", ftp.stored)
        self.assertNotIn("knowledge_20260301_part2.json", ftp.stored)
        stored = json.loads(ftp.stored["knowledge_20260301_part1.json"].decode("utf-8"))
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]["prompt"], "one")

    def test_save_to_geocities_reports_failure_instead_of_raising(self) -> None:
        class BrokenFTP(FakeFTP):
            def storbinary(self, command, data):
                raise OSError("disk full")

        with patch.object(peakebot, "FTP", return_value=BrokenFTP()):
            ok = peakebot.save_to_geocities(
                [{"timestamp": "2026-03-01T10:00:00", "prompt": "p", "response": "r"}]
            )
        self.assertFalse(ok)

    def test_save_refuses_to_replace_archive_when_directory_listing_fails(self) -> None:
        class BrokenListFTP(FakeFTP):
            def nlst(self):
                raise OSError("directory listing failed")

        ftp = BrokenListFTP(files={"knowledge_20260301_part1.json": b"existing"})
        with patch.object(peakebot, "FTP", return_value=ftp):
            ok = peakebot.save_to_geocities(
                [{"timestamp": "2026-03-01T10:00:00", "prompt": "new", "response": "entry"}],
                day_str="20260301",
            )
        self.assertFalse(ok)
        self.assertEqual(ftp.stored, {})

    def test_save_refuses_to_replace_unreadable_daily_archive(self) -> None:
        ftp = FakeFTP(files={"knowledge_20260301_part1.json": b"not valid JSON"})
        with patch.object(peakebot, "FTP", return_value=ftp):
            ok = peakebot.save_to_geocities(
                [{"timestamp": "2026-03-01T10:00:00", "prompt": "new", "response": "entry"}],
                day_str="20260301",
            )
        self.assertFalse(ok)
        self.assertEqual(ftp.stored, {})

    def test_save_to_geocities_appends_to_an_existing_day_part(self) -> None:
        existing = [{"timestamp": "2026-03-01T08:00:00", "prompt": "old", "response": "kept"}]
        ftp = FakeFTP(files={"knowledge_20260301_part1.json": json.dumps(existing).encode("utf-8")})
        with patch.object(peakebot, "FTP", return_value=ftp):
            ok = peakebot.save_to_geocities(
                [{"timestamp": "2026-03-01T10:00:00", "prompt": "new", "response": "added"}],
                day_str="20260301",
            )
        self.assertTrue(ok)
        stored = json.loads(ftp.stored["knowledge_20260301_part1.json"].decode("utf-8"))
        self.assertEqual([item["prompt"] for item in stored], ["old", "new"])

    # -- transport ----------------------------------------------------------
    def test_store_falls_back_to_active_mode_when_passive_fails(self) -> None:
        ftp = FakeFTP()
        ftp.fail_passive = True
        peakebot._ftp_store_binary(ftp, "notes.json", io.BytesIO(b"hello"))
        self.assertFalse(ftp.pasv)
        self.assertEqual(ftp.stored["notes.json"], b"hello")

    def test_store_never_retries_an_append(self) -> None:
        ftp = FakeFTP()
        ftp.fail_passive = True
        with self.assertRaises(OSError):
            memory_store_module._ftp_store_binary(ftp, "APPE notes.json", io.BytesIO(b"x"))
        self.assertTrue(ftp.pasv)

    def test_retrieve_does_not_retry_a_permission_error(self) -> None:
        ftp = FakeFTP(files={})
        with self.assertRaises(peakebot.ftplib.error_perm):
            peakebot._ftp_retr_binary(ftp, "missing.json", lambda chunk: None)
        self.assertTrue(ftp.pasv)

    def test_retrieve_falls_back_to_active_mode_when_passive_fails(self) -> None:
        class PassiveFailFTP(FakeFTP):
            def retrbinary(self, command, callback):
                if self.pasv:
                    callback(b"partial")
                    raise OSError("passive data channel refused")
                return super().retrbinary(command, callback)

        ftp = PassiveFailFTP(files={"memory.json": b"payload"})
        chunks: list[bytes] = []
        peakebot._ftp_retr_binary(ftp, "memory.json", chunks.append)
        self.assertFalse(ftp.pasv)
        self.assertEqual(b"".join(chunks), b"payload")

    def test_memory_store_retrieve_discards_partial_passive_data(self) -> None:
        class PassiveFailFTP(FakeFTP):
            def retrbinary(self, command, callback):
                if self.pasv:
                    callback(b"partial")
                    raise OSError("passive data channel refused")
                return super().retrbinary(command, callback)

        ftp = PassiveFailFTP(files={"memory.json": b"payload"})
        chunks: list[bytes] = []
        memory_store_module._ftp_retr_binary(ftp, "RETR memory.json", chunks.append)
        self.assertFalse(ftp.pasv)
        self.assertEqual(b"".join(chunks), b"payload")

    def test_memory_store_uses_plain_ftp_with_passive_mode(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = memory_store.MemoryStore(Path(folder) / "memory.jsonl")
            self.assertFalse(store.ftp_tls)
        self.assertFalse(peakebot.FTP_HOST.startswith("<REDACTED"))


if __name__ == "__main__":
    unittest.main()
