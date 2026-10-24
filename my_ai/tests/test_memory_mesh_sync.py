"""Regression tests for archive-index recall, auto-mesh, and upload retries."""

from __future__ import annotations

import ftplib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from my_ai.memory_store import MemoryStore


class _ArchiveFTP:
    """In-memory FTP double supporting the calls the archive sync uses."""

    files: dict[str, bytes] = {}
    connects = 0
    fail_first_stor = False
    stor_attempts: list[str] = []

    def __init__(self, *_args, **_kwargs) -> None:
        type(self).connects += 1

    def connect(self, host=None, timeout=None):
        return "220 OK"

    def login(self, user, password):
        return "230 OK"

    def set_pasv(self, flag):
        return None

    def sendcmd(self, command):
        return "200 OK"

    def pwd(self):
        return "/"

    def cwd(self, path):
        return path

    def mkd(self, path):
        return path

    def nlst(self):
        return sorted(_ArchiveFTP.files)

    def quit(self):
        return None

    def close(self):
        return None

    def storbinary(self, command, data):
        _ArchiveFTP.stor_attempts.append(command)
        if _ArchiveFTP.fail_first_stor:
            _ArchiveFTP.fail_first_stor = False
            raise OSError("passive data port refused")
        name = command.split(" ", 1)[1]
        _ArchiveFTP.files[name] = data.read()

    def size(self, name):
        if name not in _ArchiveFTP.files:
            raise ftplib.error_perm("550 no such file")
        return len(_ArchiveFTP.files[name])

    def retrbinary(self, command, callback):
        name = command.split(" ", 1)[1]
        if name not in _ArchiveFTP.files:
            raise ftplib.error_perm("550 no such file")
        callback(_ArchiveFTP.files[name])


class ArchiveSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        _ArchiveFTP.files = {}
        _ArchiveFTP.connects = 0
        _ArchiveFTP.fail_first_stor = False
        _ArchiveFTP.stor_attempts = []
        self._folder = tempfile.TemporaryDirectory()
        self.addCleanup(self._folder.cleanup)

    def _store(self, folder: str = "", records: int = 50) -> MemoryStore:
        env = {
            "MEMORY_FTP_HOST": "ftp.example.test",
            "MEMORY_FTP_USER": "user",
            "MEMORY_FTP_PASSWORD": "password",
            "MEMORY_FTP_BASE_DIR": folder,
            "MEMORY_FTP_MAX_ATTEMPTS": "2",
            "MEMORY_FTP_BACKOFF_SECONDS": "0",
        }
        with patch.dict(os.environ, env, clear=False):
            return MemoryStore(Path(self._folder.name) / "memory.jsonl")

    def test_upload_writes_index_and_retries_transient_failure(self) -> None:
        store = self._store()
        with patch.object(store, "_connect", side_effect=_ArchiveFTP):
            note = store.add("Harold tracks FTP archive sync health", category="Tools")
            _ArchiveFTP.fail_first_stor = True
            uploaded, connections = store.upload_notes([note])
        self.assertEqual(uploaded, 1)
        self.assertEqual(connections, 1, "the data-channel fallback should recover in-session")
        # Two STOR attempts for the shard prove the refused transfer was retried.
        self.assertEqual(_ArchiveFTP.stor_attempts.count("STOR pocket-ai-memory.jsonl"), 2)
        stored_names = set(_ArchiveFTP.files)
        self.assertEqual([n for n in stored_names if n.startswith("pocket-ai-memory.jsonl")], ["pocket-ai-memory.jsonl"])
        archived_index = json.loads(_ArchiveFTP.files["harold-archive-index.jsonl"].decode("utf-8"))
        self.assertEqual(archived_index["i"], note["i"])

    def test_recall_uses_archived_index_without_reading_every_shard(self) -> None:
        store = self._store()
        with patch.object(store, "_connect", side_effect=_ArchiveFTP):
            note = store.add("Raspberry Pi deployment notes for Harold", category="Tools")
            store.upload(note)

        fresh = self._store()
        reads: list[str] = []
        original = MemoryStore._read_remote_shards

        def tracked(view, client):
            reads.append("shards")
            return original(view, client)

        with patch.object(fresh, "_connect", side_effect=_ArchiveFTP), \
                patch.object(MemoryStore, "_read_remote_shards", tracked):
            recalled = fresh.relevant_remote("raspberry deployment")

        self.assertIn("Raspberry Pi", recalled)
        self.assertEqual(reads, [], "recall must not download every note shard when an index exists")

    def test_saving_a_note_auto_links_related_notes(self) -> None:
        store = self._store()
        first = store.add("Harold stores learned facts about python scripting", category="Knowledge")
        second = store.add("Harold stores learned code examples for python scripting", category="Knowledge")
        third = store.add("The weather in Lisbon is mild in spring", category="Knowledge")
        self.assertIn(second["i"], store._edges.get(first["i"], {}))
        self.assertNotIn(third["i"], store._edges.get(first["i"], {}))

    def test_mesh_neighbour_is_recalled_alongside_the_match(self) -> None:
        store = self._store()
        first = store.add("Kelvin telemetry rollout plan", category="Projects")
        second = store.add("Telemetry ingestion benchmark results", category="Projects")
        store.link(first["i"], second["i"], "rel")
        # The query shares only one term with the neighbour, so it is the mesh
        # link (not the keyword search) that has to carry it into the answer.
        recalled = store.relevant("kelvin rollout plan")
        self.assertIn(first["n"], recalled)
        self.assertIn(second["n"], recalled)
        self.assertIn("RELATED mesh rel", recalled)


if __name__ == "__main__":
    unittest.main()
