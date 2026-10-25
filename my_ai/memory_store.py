#!/usr/bin/env python3
"""MCF3 notes with a bounded local cache and size-limited FTP/FTPS archive shards."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timezone
import ftplib
import io
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import ssl
import tempfile
import threading
import time
from urllib.parse import urlsplit
import uuid


_WORDS = re.compile(r"[^\W_]+", re.UNICODE)
_TAG_RE = re.compile(r"#([a-zA-Z0-9_\-]+)")
_REL_RE = re.compile(r"(?:rel:|->\s*)([a-zA-Z0-9_/.\-]+)")
_SOURCE_URL_RE = re.compile(r"\^(https?://[a-zA-Z0-9_\-./?&=%#]+)")


def _ftp_store_binary(client: ftplib.FTP, command: str, data) -> None:
    """Store remote bytes, using passive mode when the server allows it.

    Some servers advertise PASV but refuse the data channel. Fall back to an
    active connection before giving up on the upload. Appending is never
    retried, because a partial append would be duplicated by a second try.
    """
    try:
        client.storbinary(command, data)
    except ftplib.all_errors:
        if command.strip().upper().startswith("APPE"):
            raise
        client.set_pasv(False)
        try:
            data.seek(0)
        except Exception:
            pass
        client.storbinary(command, data)


def _ftp_retr_binary(client: ftplib.FTP, command: str, callback) -> None:
    """Retrieve safely, retrying in active mode without replaying partial bytes."""
    with tempfile.SpooledTemporaryFile(max_size=1024 * 1024) as downloaded:
        try:
            client.retrbinary(command, downloaded.write)
        except ftplib.all_errors as exc:
            if isinstance(exc, ftplib.error_perm):
                # A permission reply (for example 550 missing file) is not a
                # transport problem, so do not retry over another data channel.
                raise
            client.set_pasv(False)
            downloaded.seek(0)
            downloaded.truncate()
            client.retrbinary(command, downloaded.write)

        downloaded.seek(0)
        while chunk := downloaded.read(64 * 1024):
            callback(chunk)

_STOP_WORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and", "any", "are",
    "aren't", "as", "at", "be", "because", "been", "before", "being", "below", "between", "both",
    "but", "by", "can", "cannot", "could", "couldn't", "did", "didn't", "do", "does", "doesn't",
    "doing", "don't", "down", "during", "each", "few", "for", "from", "further", "had", "hadn't",
    "has", "hasn't", "have", "haven't", "having", "he", "her", "here", "hers", "herself", "him",
    "himself", "his", "how", "i", "if", "in", "into", "is", "isn't", "it", "its", "itself", "just",
    "me", "more", "most", "my", "myself", "no", "nor", "not", "of", "off", "on", "once", "only",
    "or", "other", "our", "ours", "ourselves", "out", "over", "own", "please", "same", "she",
    "should", "shouldn't", "so", "some", "such", "than", "that", "the", "their", "theirs", "them",
    "themselves", "then", "there", "these", "they", "this", "those", "through", "to", "too",
    "under", "until", "up", "very", "was", "wasn't", "we", "were", "weren't", "what", "when",
    "where", "which", "while", "who", "whom", "why", "will", "with", "won't", "would", "wouldn't",
    "you", "your", "yours", "yourself", "yourselves",
}

# Curated synonym / related-term map. Expanding query terms with these lets a
# recall surface conceptually related notes even when the wording differs.
# Aliases learned at runtime are persisted by the MemoryStore, never added here.
_SYNONYMS: dict[str, frozenset[str]] = {
    "python": frozenset({"coding", "program", "programming", "script", "code"}),
    "coding": frozenset({"python", "program", "programming", "script", "code"}),
    "program": frozenset({"coding", "python", "programming", "script", "code"}),
    "programming": frozenset({"coding", "python", "program", "script", "code"}),
    "script": frozenset({"coding", "python", "program", "programming", "code"}),
    "code": frozenset({"coding", "python", "program", "programming", "script"}),
    "happy": frozenset({"joy", "delight", "pleasure", "glad", "cheerful"}),
    "joy": frozenset({"happy", "delight", "pleasure"}),
    "delight": frozenset({"happy", "joy", "pleasure"}),
    "sad": frozenset({"sorrow", "grief", "unhappy", "mourn", "gloomy"}),
    "grief": frozenset({"sad", "sorrow", "mourn", "bereavement"}),
    "sorrow": frozenset({"sad", "grief", "mourn"}),
    "fear": frozenset({"anxiety", "dread", "panic", "worry", "afraid"}),
    "anxiety": frozenset({"fear", "worry", "dread", "panic"}),
    "worry": frozenset({"anxiety", "fear", "stress"}),
    "stress": frozenset({"worry", "anxiety", "pressure", "burnout"}),
    "burnout": frozenset({"stress", "exhaustion", "fatigue"}),
    "tired": frozenset({"exhaust", "exhaustion", "fatigue", "weary"}),
    "exhaust": frozenset({"tired", "exhaustion", "fatigue"}),
    "love": frozenset({"care", "like", "affection", "cherish"}),
    "like": frozenset({"love", "care", "prefer", "enjoy"}),
    "prefer": frozenset({"like", "preference", "preferences", "favor"}),
    "preference": frozenset({"prefer", "preferences", "like", "favor"}),
    "preferences": frozenset({"prefer", "preference", "like"}),
    "remember": frozenset({"recall", "recollect", "memories", "reminisce"}),
    "memory": frozenset({"memories", "remember", "recollection"}),
    "memories": frozenset({"memory", "remember", "recollection"}),
    "learn": frozenset({"study", "understand", "grasp", "master"}),
    "understand": frozenset({"learn", "comprehend", "grasp"}),
    "help": frozenset({"assist", "aid", "support"}),
    "use": frozenset({"utilize", "employ", "apply"}),
    "make": frozenset({"create", "build", "produce", "craft"}),
    "build": frozenset({"make", "create", "construct"}),
    "create": frozenset({"make", "build", "produce"}),
    "write": frozenset({"compose", "draft", "author"}),
    "read": frozenset({"peruse", "study", "review"}),
    "see": frozenset({"view", "watch", "observe", "notice"}),
    "hear": frozenset({"listen", "sound"}),
    "feel": frozenset({"sense", "experience", "sensation"}),
    "think": frozenset({"believe", "consider", "reckon", "ponder"}),
    "believe": frozenset({"think", "trust", "faith"}),
    "trust": frozenset({"believe", "rely", "confidence"}),
    "friend": frozenset({"companion", "pal", "buddy"}),
    "family": frozenset({"relatives", "kin", "kinfolk"}),
    "home": frozenset({"house", "dwelling", "residence"}),
    "work": frozenset({"job", "employment", "career", "labor"}),
    "job": frozenset({"work", "career", "employment"}),
    "money": frozenset({"cash", "funds", "finance", "currency"}),
    "time": frozenset({"moment", "hour", "day", "period"}),
    "life": frozenset({"existence", "living", "lifetime"}),
    "health": frozenset({"wellness", "fitness", "wellbeing"}),
    "illness": frozenset({"sickness", "disease", "ailment"}),
    "pain": frozenset({"ache", "hurt", "soreness"}),
    "sleep": frozenset({"rest", "dream", "nap"}),
    "dream": frozenset({"sleep", "vision", "aspiration"}),
    "food": frozenset({"meal", "eating", "cooking", "cuisine"}),
    "eat": frozenset({"food", "dine", "consume", "feed"}),
    "travel": frozenset({"trip", "journey", "voyage", "tour"}),
    "city": frozenset({"town", "urban", "metropolis"}),
    "country": frozenset({"nation", "land", "state"}),
    "world": frozenset({"earth", "globe", "planet"}),
    "water": frozenset({"drink", "liquid", "ocean", "sea"}),
    "fire": frozenset({"flame", "heat", "burn"}),
    "light": frozenset({"brightness", "glow", "shine"}),
    "dark": frozenset({"shadow", "dim", "night"}),
    "night": frozenset({"dark", "evening", "sleep"}),
    "day": frozenset({"morning", "afternoon", "daylight"}),
    "morning": frozenset({"day", "dawn", "sunrise"}),
}

# Common suffixes, longest first. Stripping is only a bonus signal on top of
# exact/keyword overlap: exact matches are never changed by stemming.
_STEM_SUFFIXES: tuple[tuple[str, str], ...] = (
    ("sses", "ss"), ("ies", "y"), ("ied", "y"), ("ingly", "ing"),
    ("edly", "ed"), ("ening", "en"), ("ations", "ation"), ("sions", "sion"),
    ("tions", "tion"), ("ments", "ment"), ("nesses", "ness"), ("ences", "ence"),
    ("ances", "ance"), ("ings", "ing"), ("ers", "er"), ("ests", "est"),
    ("ables", "able"), ("ibles", "ible"), ("ingly", "ing"), ("ingly", "ing"),
    ("lly", "ly"), ("ingly", "ing"),
    ("ing", ""), ("ed", ""), ("es", ""), ("s", ""), ("ly", ""), ("er", ""),
    ("est", ""), ("ment", ""), ("tion", ""), ("sion", ""), ("ness", ""),
    ("ance", ""), ("ence", ""), ("able", ""), ("ible", ""), ("ive", ""),
    ("ful", ""), ("ous", ""), ("al", ""),
)


def _stem(word: str) -> str:
    """Very light stemming used as a bonus recall signal.

    Strips at most one common suffix and never reduces a word below three
    letters, so exact keyword overlap remains the authoritative match.
    """
    w = word.casefold()
    for suffix, replacement in _STEM_SUFFIXES:
        if w.endswith(suffix) and len(w) - len(suffix) >= 3:
            return w[: len(w) - len(suffix)] + replacement
    return w


# Penalty applied to a synonym/stem-only match. It still surfaces related notes
# but can no longer climb above a note that shares the user's actual words.
_SEMANTIC_ONLY_WEIGHT = 0.6
# A lexical "related" link needs this many shared distinctive terms.
_MIN_LEXICAL_BRIDGE_TERMS = 2
# Terms in more than this share of notes describe everything, so they connect
# nothing: they are excluded from associative links.
_MAX_BRIDGE_DOCUMENT_RATIO = 0.2
_MIN_BRIDGE_DOCUMENT_FREQUENCY = 2
# Words that describe activity, not identity. A note saying "python automates
# reports" shares "automates" with any other work note, so it can never be
# learned as another name for "python".






# Consolidation writes one synthesis per cluster, naming the notes it came from.
# Learned vocabulary. An alias note reads: "ALIAS <head> => <alias>".
# Evidence is ordinary memory notes, so it syncs with the same FTP archive and
# is rebuilt on every startup; no sidecar file can drift from the notes.
_ALIAS_CATEGORY = "Vocab/Aliases"
_ALIAS_STORED_RE = re.compile(r"^ALIAS\s+(\S+)\s*=>\s*(\S+)$", re.IGNORECASE)
# How many distinct notes must support a pair before recall trusts it.
_ALIAS_MIN_COUNT = 2
_ALIAS_BOILERPLATE = frozenset({"note", "notes", "thing", "things", "stuff"})
# Verbs are never names for a thing, however often they co-occur.
_ALIAS_VERB_STEMS = frozenset((
    "automat", "rewrit", "build", "creat", "export", "improv", "track",
    "fetch", "stor", "record", "learn", "report", "help", "work", "run",
    "send", "read", "writ", "check", "updat", "sync", "keep",
))
_CONSOLIDATED_CATEGORY = "Harold/Understanding/Consolidated"
# Lineage is stored in the record's optional "l" field.
_MAX_LINEAGE_CHARS = 2000
# A lexical "related" link needs this many shared distinctive terms.
_MIN_LEXICAL_BRIDGE_TERMS = 2
# Terms in more than this share of notes describe everything, so they connect
# nothing: they are excluded from associative links.
_MAX_BRIDGE_DOCUMENT_RATIO = 0.2
_MIN_BRIDGE_DOCUMENT_FREQUENCY = 2


def _stem_term(term: str) -> str:
    """Stem an already-lowercased term, applying the plural a second time.

    The generic ``_stem`` strips one suffix only, so "automates" becomes
    "automat" while "automate" stays "automate". Vocabulary checks use this so
    a word and its plural are treated alike.
    """
    stem = _stem(term)
    return _stem(stem) if stem == term else stem


# Vocabulary the system itself writes when it links and consolidates notes.
# These words describe the machinery ("related", "consolidated"), not what a
# note is about, so they must never count as recall evidence.
_CONNECTIVE_STEMS = frozenset(
    _stem_term(term) for term in (
        "related", "link", "linked", "connection", "connected", "similar",
        "consolidated", "consolidation", "synthesis", "note", "notes",
        "source", "sources", "derived", "legacy", "auto", "mesh",
    )
)


def _split_connective_terms(terms: set[str]) -> tuple[set[str], set[str]]:
    """Return (evidence, connective) terms; connective ones never rank a note."""
    connective = {term for term in terms if _stem_term(term) in _CONNECTIVE_STEMS}
    return terms - connective, connective


def _expand_terms(terms: set[str]) -> set[str]:
    """Return terms plus their curated synonyms (query-side expansion)."""
    expanded: set[str] = set(terms)
    for term in terms:
        expanded.update(_SYNONYMS.get(term, ()))
    return expanded

def _is_real_term(term: str) -> bool:
    """True for words that carry meaning for recall and meshing.

    Two-letter function words such as "is" or "it" are dropped so a match on
    them can never make two unrelated notes look related.
    """
    if "'" in term:
        return False
    return (len(term) > 2 and not term.isdigit()) and term not in _STOP_WORDS


_MAX_NOTE_CHARS = 500
_MAX_RECORD_BYTES = 4096
_HARD_REMOTE_MAX_BYTES = 64 * 1024
_DEFAULT_REMOTE_MAX_BYTES = 32 * 1024
_DEFAULT_LOCAL_CACHE_RECORDS = 50
_MAX_REMOTE_SHARDS = 10_000
# A durable lookup index and mesh are archived with the notes, so recall and mesh
# navigation are fast again after any redeploy (Render's disk is ephemeral).
# Auto-mesh tuning. Every saved note links itself to its closest existing notes
# so a recall surfaces the whole cluster instead of one isolated line.
_MESH_AUTOLINK_ENABLED = os.environ.get("MEMORY_MESH_AUTOLINK", "true").lower() in {"1", "true", "yes", "on"}
_MESH_AUTOLINK_MAX_LINKS = 4
_MESH_AUTOLINK_MIN_WEIGHT = 1.5
_MESH_RECALL_DEPTH = 2
_MESH_MAX_REMOTE_BYTES = 2 * 1024 * 1024
_SYNC_MAX_ATTEMPTS = int(os.environ.get("MEMORY_FTP_MAX_ATTEMPTS", "4"))
_SYNC_BACKOFF_SECONDS = float(os.environ.get("MEMORY_FTP_BACKOFF_SECONDS", "1.0"))


class MemoryLanguage:
    """Parser and vocabulary extractor for the Memory Compact Format (MCF3)."""

    PREFIX_RULES: tuple[tuple[re.Pattern[str], str | None], ...] = (
        (re.compile(r"^@pref(?:erence)?s?[:\s]+", re.IGNORECASE), "Preferences"),
        (re.compile(r"^@proj(?:ect)?:([a-zA-Z0-9_\-]+)[:\s]*", re.IGNORECASE), "Projects/{}"),
        (re.compile(r"^@proj(?:ect)?s?[:\s]+", re.IGNORECASE), "Projects"),
        (re.compile(r"^@work[:\s]+", re.IGNORECASE), "Work"),
        (re.compile(r"^@tool(?:s)?[:\s]+", re.IGNORECASE), "Tools"),
        (re.compile(r"^@finance[:\s]+", re.IGNORECASE), "Finance"),
        (re.compile(r"^@fact[:\s]+", re.IGNORECASE), "Knowledge"),
        (re.compile(r"^@note[:\s]+", re.IGNORECASE), "Knowledge"),
        (re.compile(r"^\*\s+", re.IGNORECASE), "Preferences"),
    )

    @classmethod
    def parse_note(cls, note: str) -> tuple[str | None, list[str], list[str], str, str]:
        """Extract category directive, tags, explicit relations, source, and clean text."""
        category = None
        cleaned = note.strip()

        for pattern, cat_target in cls.PREFIX_RULES:
            match = pattern.search(cleaned)
            if match:
                if cat_target and "{}" in cat_target:
                    category = cat_target.format(match.group(1))
                else:
                    category = cat_target
                cleaned = cleaned[match.end():].strip()
                break

        tags = [tag.casefold() for tag in _TAG_RE.findall(cleaned)]
        relations = [rel.strip() for rel in _REL_RE.findall(cleaned)]

        source = ""
        source_match = _SOURCE_URL_RE.search(cleaned)
        if source_match:
            cand = source_match.group(1)
            if not any(c.isspace() for c in cand):
                source = cand

        return category, tags, relations, source, cleaned

    @classmethod
    def parse_query(cls, query: str) -> tuple[str | None, list[str], list[str], str]:
        """Extract query directives like cat:Category, in:Category, #tags."""
        cat_match = re.search(r"\b(?:cat|in):([a-zA-Z0-9_/-]+)", query, re.IGNORECASE)
        category_filter = cat_match.group(1) if cat_match else None
        clean_query = re.sub(r"\b(?:cat|in):[a-zA-Z0-9_/-]+", "", query, flags=re.IGNORECASE).strip()

        tags = [tag.casefold() for tag in _TAG_RE.findall(clean_query)]
        relations = [rel.strip() for rel in _REL_RE.findall(clean_query)]
        return category_filter, tags, relations, clean_query


class MemoryStore:
    """Manage an MCF3 cache/index and a sharded FTP archive with FTS5 recall."""

    def __init__(self, path: Path, legacy_path: Path | None = None) -> None:
        self.path = path
        self.legacy_path = legacy_path
        self.ftp_host = (os.environ.get("MEMORY_FTP_HOST", "") or os.environ.get("FTP_HOST", "")).strip()
        self.ftp_user = os.environ.get("MEMORY_FTP_USER", "") or os.environ.get("FTP_USER", "")
        self.ftp_password = os.environ.get("MEMORY_FTP_PASSWORD", "") or os.environ.get("FTP_PASS", "")
        self.ftp_base_dir = (
            os.environ.get("MEMORY_FTP_BASE_DIR", "") or os.environ.get("FTP_BASE_DIR", "")
        ).strip().strip("/")
        self.remote_path = os.environ.get("MEMORY_FTP_PATH", "pocket-ai-memory.jsonl").strip()
        self.ftp_tls = os.environ.get("MEMORY_FTP_TLS", "").strip().lower() in {"1", "true", "yes"}
        try:
            self.max_remote_bytes = int(os.environ.get("MEMORY_FTP_MAX_BYTES", str(_DEFAULT_REMOTE_MAX_BYTES)))
        except ValueError as exc:
            raise ValueError("MEMORY_FTP_MAX_BYTES must be an integer.") from exc
        if not 1 <= self.max_remote_bytes <= _HARD_REMOTE_MAX_BYTES:
            raise ValueError(f"MEMORY_FTP_MAX_BYTES must be between 1 and {_HARD_REMOTE_MAX_BYTES}.")
        try:
            self.max_local_records = int(os.environ.get(
                "MEMORY_LOCAL_CACHE_RECORDS", str(_DEFAULT_LOCAL_CACHE_RECORDS),
            ))
        except ValueError as exc:
            raise ValueError("MEMORY_LOCAL_CACHE_RECORDS must be an integer.") from exc
        if not 1 <= self.max_local_records <= 10_000:
            raise ValueError("MEMORY_LOCAL_CACHE_RECORDS must be between 1 and 10000.")
        if (not re.fullmatch(r"/?[A-Za-z0-9._/-]+", self.remote_path)
            or any(part == ".." for part in self.remote_path.split("/"))):
            raise ValueError("MEMORY_FTP_PATH must be a safe remote file path without '..' segments.")
        if any(part in {".", ".."} for part in self.ftp_base_dir.split("/") if part):
            raise ValueError("MEMORY_FTP_BASE_DIR must not contain relative path segments.")
        # Chat threads may recall while another thread saves; serialise writes.
        self._lock = threading.RLock()
        self._mesh_lock = threading.RLock()
        # Archives written by older versions keep their index/mesh beside the
        # notes (pocket-ai-memory.jsonl.index.jsonl). Archives that also carry an
        # FTP index keep everything together under the "harold" folder, so no
        # new top-level folders appear on the FTP host.
        folder, _, _name = self.remote_path.rpartition("/")
        prefix = f"{folder}/" if folder else ""
        archived_index = os.environ.get("MEMORY_FTP_ARCHIVE_INDEX", "").strip()
        self.remote_index_path = archived_index or f"{prefix}harold-archive-index.jsonl"
        self.remote_mesh_path = f"{prefix}harold/mesh.json"
        self._remote_index: dict[str, dict[str, str]] | None = None
        self._remote_records_cache: tuple[tuple[int, ...], list[dict[str, str]]] | None = None
        loaded_records = self._read_local()
        self.records = loaded_records[-self.max_local_records:]
        if len(self.records) != len(loaded_records):
            self._write_local()
        if not self.records and legacy_path and legacy_path.is_file():
            self._import_legacy()
        self._index_path = self.path.with_suffix(".index.sqlite3")
        self._edges_path = self.path.with_suffix(".mesh.json")
        self._edges: dict[str, dict[str, str]] = {}
        self._index: sqlite3.Connection | None = None
        # learned vocabulary: head term -> {alias term: supporting notes}
        self._alias_counts: dict[str, dict[str, int]] = {}
        self._alias_written: set[str] = set()
        # term -> {candidate term: number of distinct notes supporting it}
        self._load_edges()
        self._migrate_mesh_file_once()
        self._open_index()
        self._load_aliases()

    def _open_index(self) -> None:
        """Build or update a persistent full-text index with Porter stemming."""
        try:
            self._index_path.parent.mkdir(parents=True, exist_ok=True)
            self._index = sqlite3.connect(self._index_path, check_same_thread=False)

            # Check if existing table needs upgrade to porter stemmer
            needs_recreate = False
            existing_sql = self._index.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='memories'"
            ).fetchone()
            if existing_sql is not None and "porter" not in existing_sql[0].lower():
                needs_recreate = True

            if needs_recreate:
                self._index.execute("DROP TABLE memories")

            self._index.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS memories USING fts5"
                "(id UNINDEXED, category, keywords, note, tokenize='porter unicode61')"
            )
            self._index.execute("CREATE TABLE IF NOT EXISTS index_meta (key TEXT PRIMARY KEY, value TEXT)")
            signature = self._source_signature()
            saved = self._index.execute("SELECT value FROM index_meta WHERE key='source'").fetchone()
            if saved is None or saved[0] != signature:
                self._rebuild_index()
        except sqlite3.Error:
            if self._index is not None:
                self._index.close()
            self._index = None

    def close(self) -> None:
        """Close SQLite database connection cleanly."""
        if self._index is not None:
            try:
                self._index.close()
            except sqlite3.Error:
                pass
            self._index = None

    def __del__(self) -> None:
        self.close()

    def _rebuild_index(self) -> None:
        if self._index is None:
            return
        with self._index:
            self._index.execute("DELETE FROM memories")
            self._index.executemany(
                "INSERT INTO memories(id, category, keywords, note) VALUES (?, ?, ?, ?)",
                [(r["i"], r.get("c", "Knowledge"), r.get("k", ""), r["n"]) for r in self.records],
            )
            self._index.execute(
                "INSERT OR REPLACE INTO index_meta(key, value) VALUES ('source', ?)",
                (self._source_signature(),),
            )
        # Cache eviction must reclaim disk pages too, not merely delete old FTS rows.
        try:
            self._index.execute("VACUUM")
        except sqlite3.Error:
            pass

    def _source_signature(self) -> str:
        try:
            stat = self.path.stat()
            return f"mcf3:{stat.st_size}:{stat.st_mtime_ns}"
        except OSError:
            return "mcf3:missing"

    @staticmethod
    def _source_status(source: str) -> str:
        return "source_attached_unverified" if source else "user_reported_unverified"

    @property
    def ftp_configured(self) -> bool:
        values = (self.ftp_host, self.ftp_user, self.ftp_password)
        return all(value and not re.fullmatch(r"<REDACTED[^>]*>", value) for value in values)

    @property
    def ftp_partially_configured(self) -> bool:
        return any((self.ftp_host, self.ftp_user, self.ftp_password)) and not self.ftp_configured

    @staticmethod
    def _normalize_note(note: str) -> str:
        return " ".join(note.split())

    @staticmethod
    def _valid_record(value: object) -> bool:
        if not isinstance(value, dict):
            return False
        record_id = value.get("i")
        note = value.get("n")
        category = value.get("c", "Knowledge")
        source = value.get("s", "")
        if (not isinstance(record_id, str) or not re.fullmatch(r"[a-fA-F0-9]{12}", record_id)
                or not isinstance(note, str) or not note.strip() or len(note) > _MAX_NOTE_CHARS
                or not isinstance(category, str) or len(category) > 80
                or any(part in {"", ".", ".."} for part in category.split("/"))
                or not isinstance(source, str) or len(source) > 500
                or not isinstance(value.get("l", ""), str) or len(value.get("l", "")) > _MAX_LINEAGE_CHARS):
            return False
        if source:
            if any(character.isspace() for character in source):
                return False
            try:
                parsed = urlsplit(source)
                if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                    return False
            except ValueError:
                return False
        return True

    def _read_local(self) -> list[dict[str, str]]:
        if not self.path.is_file():
            return []
        records: list[dict[str, str]] = []
        try:
            with self.path.open("r", encoding="utf-8") as source:
                for line in source:
                    try:
                        value = json.loads(line)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        continue
                    if self._valid_record(value):
                        note = self._normalize_note(value["n"])
                        category = str(value.get("c", "Knowledge"))
                        source_url = str(value.get("s", ""))
                        if len(source_url) > 500 or not source_url.startswith(("https://", "http://")):
                            source_url = ""
                        records.append(self._normalize_record({
                            "i": value["i"], "d": str(value.get("d", "")), "c": category,
                            "k": str(value.get("k", self._keywords(note, category))), "n": note,
                            "s": source_url, "l": str(value.get("l", "")),
                        }))
        except OSError:
            return []
        return self._deduplicate(records)

    @classmethod
    def _normalize_record(cls, record: dict[str, str]) -> dict[str, str]:
        """Fill in the derived fields every consumer expects (k, v, d, c, s)."""
        note = cls._normalize_note(str(record.get("n", "")))
        category = str(record.get("c") or "Knowledge")
        source = str(record.get("s", ""))
        normalized = {
            "i": record["i"], "d": str(record.get("d", "")), "c": category,
            "k": str(record.get("k") or cls._keywords(note, category)), "n": note,
            "s": source, "v": cls._source_status(source),
        }
        if record.get("l"):
            normalized["l"] = str(record["l"])
        return normalized

    @staticmethod
    def _deduplicate(records: list[dict[str, str]]) -> list[dict[str, str]]:
        by_id: dict[str, dict[str, str]] = {}
        seen_notes: set[tuple[str, str]] = set()
        result: list[dict[str, str]] = []
        for record in records:
            note = record["n"]
            source = record.get("s", "")
            note_key = (note.casefold(), source)
            if record["i"] in by_id or note_key in seen_notes:
                continue
            # Route through _normalize_record so metadata such as consolidation
            # lineage ("l") survives deduplication instead of silently vanishing.
            clean = MemoryStore._normalize_record({
                "i": record["i"], "d": record.get("d", ""), "c": record.get("c", "Knowledge"),
                "k": record.get("k", ""), "n": note, "s": source, "l": record.get("l", ""),
            })
            by_id[clean["i"]] = clean
            seen_notes.add(note_key)
            result.append(clean)
        return result

    def _write_local(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_name(self.path.name + ".tmp")
            with temporary.open("w", encoding="utf-8", newline="\n") as output:
                for record in self.records:
                    output.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            os.replace(temporary, self.path)

    def _add_to_index(self, record: dict[str, str]) -> None:
        """Add or replace one note in the persistent FTS index without a full rebuild."""
        if self._index is None:
            return
        try:
            with self._index:
                self._index.execute("DELETE FROM memories WHERE id = ?", (record["i"],))
                self._index.execute(
                    "INSERT INTO memories(id, category, keywords, note) VALUES (?, ?, ?)",
                    (record["i"], record.get("c", "Knowledge"), record.get("k", ""), record["n"]),
                )
                self._index.execute(
                    "INSERT OR REPLACE INTO index_meta(key, value) VALUES ('source', ?)",
                    (self._source_signature(),),
                )
        except sqlite3.Error:
            pass

    def _trim_local_cache(self) -> None:
        """Retain only the newest configured number of notes in local storage."""
        if len(self.records) > self.max_local_records:
            self.records = self.records[-self.max_local_records:]

    def _import_legacy(self) -> None:
        assert self.legacy_path is not None
        try:
            lines = self.legacy_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        for line in lines:
            note = self._normalize_note(line.removeprefix("-").strip())
            if note and len(note) <= _MAX_NOTE_CHARS:
                self.records.append(self._normalize_record(
                    {"i": uuid.uuid4().hex[:12], "d": "", "c": "Knowledge", "n": note}
                ))
        self.records = self._deduplicate(self.records)
        self._trim_local_cache()
        if self.records:
            self._write_local()

    @staticmethod
    def categorize(note: str) -> str:
        text = note.casefold()
        rules = (
            ("Preferences", ("i prefer", "i like", "i dislike", "please use", "my preference", "always use", "never use", "i want")),
            ("Projects", ("project", "working on", "building", "my app", "my bot", "portfolio", "codebase", "repository")),
            ("Personal", ("my name", "i live", "my family", "my birthday", "i am allergic", "my hobby", "my age")),
            ("Work", ("my job", "i work", "my manager", "my company", "my office", "my team")),
            ("Finance", ("stock", "market", "invest", "portfolio", "crypto", "dividend", "financial")),
            ("Tools", ("tool", "linux", "git", "terminal", "editor", "vscode", "docker", "server")),
        )
        for category, phrases in rules:
            if any(phrase in text for phrase in phrases):
                return category
        return "Knowledge"

    @staticmethod
    def _keywords(note: str, category: str = "") -> str:
        """Create a normalized recall vocabulary capturing concepts, tags, and category terms."""
        terms: list[str] = []
        seen: set[str] = set()

        # High priority: tags and explicit relations
        tags = _TAG_RE.findall(note)
        rels = _REL_RE.findall(note)
        for item in tags + rels:
            for word in _WORDS.findall(item):
                t = word.casefold()
                if len(t) > 1 and t not in _STOP_WORDS and t not in seen:
                    seen.add(t)
                    terms.append(t)

        # Category path terms
        if category:
            for word in _WORDS.findall(category):
                t = word.casefold()
                if len(t) > 1 and t not in _STOP_WORDS and t not in seen:
                    seen.add(t)
                    terms.append(t)

        # Content words (up to 40 terms to ensure full note coverage)
        for word in _WORDS.findall(note):
            term = word.casefold()
            if len(term) <= 1 or term in _STOP_WORDS or term in seen:
                continue
            seen.add(term)
            terms.append(term)
            if len(terms) >= 40:
                break
        return " ".join(terms)

    def add(
        self, note: str, category: str | None = None, source: str = "",
    ) -> dict[str, str] | None:
        cleaned = self._normalize_note(note)
        if not cleaned:
            raise ValueError("Memory note cannot be empty.")
        if len(cleaned) > _MAX_NOTE_CHARS:
            raise ValueError(f"Keep memory notes to {_MAX_NOTE_CHARS} characters or fewer.")

        # Parse memory language syntax
        lang_cat, _, _, lang_source, clean_note = MemoryLanguage.parse_note(cleaned)

        final_cat = (category or lang_cat or self.categorize(cleaned)).strip(" /\\") or "Knowledge"
        if len(final_cat) > 80 or any(part in {"", ".", ".."} for part in final_cat.split("/")):
            raise ValueError("Use a short category path such as Projects/Website.")

        final_note = clean_note if clean_note else cleaned

        final_source = (source or lang_source).strip()
        if final_source:
            if any(character.isspace() for character in final_source):
                raise ValueError("A source URL cannot contain whitespace.")
            try:
                parsed_source = urlsplit(final_source)
            except ValueError as exc:
                raise ValueError("A source must be a valid http:// or https:// URL under 500 characters.") from exc
            if (len(final_source) > 500 or parsed_source.scheme not in {"http", "https"}
                    or not parsed_source.hostname):
                raise ValueError("A source must be a valid http:// or https:// URL under 500 characters.")

        if any(
            item["n"].casefold() == final_note.casefold()
            and item.get("s", "") == final_source
            for item in self.records
        ):
            return None

        record = {
            "i": uuid.uuid4().hex[:12], "d": date.today().isoformat(), "c": final_cat,
            "k": self._keywords(final_note, final_cat), "n": final_note,
            "s": final_source, "v": self._source_status(final_source),
        }
        with self._lock:
            self.records.append(record)
            self._trim_local_cache()
            self._write_local()
            self._add_to_index(record)
        # Wire explicit mesh edges from any rel:<note-id> references in the note.
        linked = False
        for rel in _REL_RE.findall(final_note):
            rel = rel.strip()
            if re.fullmatch(r"[a-fA-F0-9]{12}", rel):
                self.link(record["i"], rel, "rel")
                linked = True
        # Mesh the new note into whatever it already relates to, so a later
        # recall can walk from it to the rest of the cluster.
        if not linked:
            self._mesh_autolink(record)
        return record

    def remove(self, target: str) -> dict[str, str] | None:
        """Remove a memory by its 12-char ID or matching text."""
        target = target.strip()
        if not target:
            return None

        match_idx = -1
        for idx, record in enumerate(self.records):
            if record["i"].lower() == target.lower():
                match_idx = idx
                break
        if match_idx == -1:
            target_cf = target.casefold()
            for idx, record in enumerate(self.records):
                if target_cf in record["n"].casefold():
                    match_idx = idx
                    break

        if match_idx == -1:
            if not self.ftp_configured:
                return None
            target_cf = target.casefold()
            for record in self._read_remote_records():
                if record["i"].casefold() == target_cf or target_cf in record["n"].casefold():
                    self._rewrite_remote(record["i"])
                    return record
            return None

        with self._lock:
            removed = self.records.pop(match_idx)
            self._write_local()
        # Drop mesh edges touching the removed note.
        with self._mesh_lock:
            if removed["i"] in self._edges:
                for other in list(self._edges[removed["i"]].keys()):
                    self._edges[other].pop(removed["i"], None)
                del self._edges[removed["i"]]
                self._save_edges()
        self._rebuild_index()
        if self.ftp_configured:
            try:
                self._rewrite_remote(removed["i"])
            except Exception:
                pass
        return removed

    def _rewrite_remote(self, removed_id: str) -> None:
        if not self.ftp_configured:
            return
        remote_records = [record for record in self._read_remote_records() if record["i"] != removed_id]
        payloads = [self._encode_record(record) for record in remote_records]
        client = self._connect()
        try:
            old_sizes = self._remote_shard_sizes(client)
            grouped: list[bytes] = []
            current = bytearray()
            for payload in payloads:
                if len(payload) > self.max_remote_bytes:
                    raise RuntimeError("A memory record is larger than the configured FTP file limit.")
                if current and len(current) + len(payload) > self.max_remote_bytes:
                    grouped.append(bytes(current))
                    current.clear()
                current.extend(payload)
            if current or not grouped:
                grouped.append(bytes(current))
            for index, contents in enumerate(grouped):
                _ftp_store_binary(client, "STOR " + self._remote_shard_path(index), io.BytesIO(contents))
            for index in range(len(grouped), len(old_sizes)):
                try:
                    client.delete(self._remote_shard_path(index))
                except ftplib.all_errors:
                    pass
            # Keep the archived lookup index in step with the rewritten archive.
            remote_index = self._read_remote_index(client)
            if remote_index is not None and remote_index.pop(removed_id, None) is not None:
                try:
                    self._store_remote_index(client, remote_index)
                except ftplib.all_errors:
                    pass
        finally:
            try:
                client.quit()
            except ftplib.all_errors:
                client.close()

    def import_file(self, file_path: Path, category_prefix: str = "Docs") -> int:
        """Import a markdown or text file into memory notes."""
        if not file_path.is_file():
            raise FileNotFoundError(f"File not found: {file_path}")
        content = file_path.read_text(encoding="utf-8", errors="replace")
        return self.import_text(content, category_prefix=category_prefix, source_name=file_path.stem)

    def import_text(self, content: str, category_prefix: str = "Docs", source_name: str = "") -> int:
        """Parse text/markdown into atomic chunked memory notes."""
        lines = content.splitlines()
        chunks: list[tuple[str, str]] = []
        current_section = source_name or "General"
        current_paras: list[str] = []

        def flush():
            if current_paras:
                text = " ".join(" ".join(p.split()) for p in current_paras if p.strip())
                if text:
                    while len(text) > _MAX_NOTE_CHARS:
                        split_pt = text.rfind(". ", 0, _MAX_NOTE_CHARS)
                        if split_pt == -1:
                            split_pt = text.rfind(" ", 0, _MAX_NOTE_CHARS)
                        if split_pt == -1:
                            split_pt = _MAX_NOTE_CHARS
                        chunks.append((f"{category_prefix}/{current_section}".strip("/"), text[:split_pt].strip()))
                        text = text[split_pt:].strip(". ")
                    if text:
                        chunks.append((f"{category_prefix}/{current_section}".strip("/"), text))
                current_paras.clear()

        for line in lines:
            line_str = line.strip()
            if line_str.startswith("#"):
                flush()
                header = re.sub(r"[^a-zA-Z0-9_\-]+", "", line_str.lstrip("#").strip().replace(" ", "_"))[:30]
                current_section = header or "General"
            elif not line_str:
                flush()
            else:
                current_paras.append(line_str)
        flush()

        added = 0
        for cat, note in chunks:
            if note and len(note) >= 5:
                res = self.add(note, category=cat)
                if res is not None:
                    added += 1
        return added

    def relevant(self, query: str, limit: int = 8, max_chars: int = 1800) -> str:
        direct, related = self._effective_matches(query, limit=limit)
        return self._render_matches(direct, related, max_chars=max_chars)

    def _effective_matches(
        self, query: str, limit: int = 8,
    ) -> tuple[list[dict[str, str]], list[tuple[str, dict[str, str], list[str]]]]:
        """Return direct matches plus mesh-aware related notes for one query."""
        cat_filter, tags, _, clean_query = MemoryLanguage.parse_query(query)
        query_terms = {
            word.casefold() for word in _WORDS.findall(clean_query)
            if len(word) > 1 and word.casefold() not in _STOP_WORDS
        }
        for tag in tags:
            query_terms.add(tag)

        if not query_terms:
            return [], []

        ranked = self._find_records(query_terms, limit * 4, clean_query, category_filter=cat_filter)
        direct = ranked[:limit]

        # Mesh first: neighbours of a direct hit are the strongest association
        # signal, because they were linked for a reason. Walking two hops means
        # a recalled note brings a few companions instead of one lonely line.
        related: list[tuple[str, dict[str, str], list[str]]] = []
        direct_ids = {record["i"] for record in direct}
        by_id = {record["i"]: record for record in self.records}
        seen: set[str] = set()
        for node_id in self._mesh_bfs([record["i"] for record in direct], depth=_MESH_RECALL_DEPTH):
            neighbor = by_id.get(node_id)
            if neighbor is None or node_id in direct_ids or node_id in seen:
                continue
            seen.add(node_id)
            relation = next(
                (rel for seed in direct for nid, rel in self.neighbors(seed["i"]) if nid == node_id),
                "linked",
            )
            related.append((f"mesh {relation}", neighbor, []))

        # Then the lexical bridge: notes that share a *distinctive* term with a
        # hit. Category names such as "Personal" appear on many unrelated notes,
        # so a shared category (or any very common word) is not evidence of a
        # relationship and is filtered out here.
        linked_terms: set[str] = set()
        for record in direct:
            linked_terms.update(record.get("k", "").split())
        bridge_terms = {
            term for term in linked_terms - query_terms
            if self._is_distinctive(term)
        }
        related_candidates = self._find_records(bridge_terms, limit * 3, category_filter=cat_filter) if bridge_terms else []
        lexical: list[tuple[str, dict[str, str], list[str]]] = []
        for record in related_candidates:
            if record["i"] in direct_ids or record["i"] in seen:
                continue
            overlap = sorted(bridge_terms & set(record.get("k", "").split()))
            if len(overlap) >= _MIN_LEXICAL_BRIDGE_TERMS:
                lexical.append((f"via {', '.join(overlap[:3])}", record, overlap))
        lexical.sort(key=lambda item: (len(item[2]), item[1].get("d", "")), reverse=True)
        return direct, related + lexical

    @staticmethod
    def _content_terms(record: dict[str, str]) -> set[str]:
        """Meaningful words a note is about, minus system-written vocabulary."""
        terms = {
            word.casefold() for word in _WORDS.findall(record.get("n", ""))
            if len(word) > 2 and word.casefold() not in _STOP_WORDS
        }
        _, connective = _split_connective_terms(terms)
        return terms - connective

    def _is_distinctive(self, term: str) -> bool:
        """True when a term narrows the collection rather than tag-everything.

        A word in more than _MAX_BRIDGE_DOCUMENT_RATIO of notes (a category
        name, "the", "note") cannot connect two notes into a meaningful
        association, however often it co-occurs.
        """
        total = max(1, len(self.records))
        # Categories are stored as words in ``k``, so exclude them outright.
        if term in self._category_vocabulary():
            return False
        frequency = self._term_document_frequencies({term}).get(term, 1)
        return frequency < max(_MIN_BRIDGE_DOCUMENT_FREQUENCY, int(total * _MAX_BRIDGE_DOCUMENT_RATIO))

    def _category_vocabulary(self) -> set[str]:
        """Words that merely name a folder, never a note's subject."""
        words: set[str] = set()
        for record in self.records:
            for word in _WORDS.findall(record.get("c", "")):
                words.add(word.casefold())
        return words
    def _render_matches(
        self,
        direct: list[dict[str, str]],
        related: list[tuple[str, dict[str, str], list[str]]],
        max_chars: int,
    ) -> str:
        selected: list[str] = []
        used = 0
        def add(reason: str, record: dict[str, str]) -> None:
            nonlocal used
            provenance = f"; saved {record.get('d', 'date unknown')}; {record.get('v', '')}"
            provenance += f"; source {record['s']}" if record.get("s") else ""
            if reason:
                label = f"RELATED {reason}; {record.get('c', 'Knowledge')}"
            else:
                label = str(record.get('c', 'Knowledge'))
            line = f"- [{label}{provenance}] {record['n']}"
            extra = len(line) + (1 if selected else 0)
            if used + extra > max_chars:
                return
            selected.append(line)
            used += extra
        for record in direct:
            add("", record)
        for reason, record, _ in related[:2]:
            add(reason, record)
        return "\n".join(selected)

    def _remote_shard_path(self, index: int) -> str:
        """Name a sequential archive file; shard zero preserves the legacy path."""
        return self.remote_path if index == 0 else f"{self.remote_path}.{index:06d}"

    def _read_remote_shards(self, client: ftplib.FTP) -> tuple[list[dict[str, str]], list[int]]:
        """Read consecutive capped files, stopping at the first missing shard."""
        remote_records: list[dict[str, str]] = []
        shard_sizes: list[int] = []
        for index in range(_MAX_REMOTE_SHARDS):
            chunks: list[bytes] = []
            file_size = 0

            def collect(chunk: bytes) -> None:
                nonlocal file_size
                file_size += len(chunk)
                if file_size > self.max_remote_bytes:
                    raise RuntimeError(
                        f"FTP memory file {self._remote_shard_path(index)} exceeds its "
                        f"{self.max_remote_bytes}-byte per-file limit."
                    )
                chunks.append(chunk)

            try:
                _ftp_retr_binary(client, "RETR " + self._remote_shard_path(index), collect)
            except ftplib.error_perm as exc:
                if str(exc).startswith("550"):
                    break
                raise

            shard_sizes.append(file_size)
            for raw_line in b"".join(chunks).splitlines():
                if len(raw_line) > _MAX_RECORD_BYTES:
                    continue
                try:
                    value = json.loads(raw_line.decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
                if not self._valid_record(value):
                    continue
                note = self._normalize_note(value["n"])
                category = str(value.get("c", "Knowledge"))
                source_url = str(value.get("s", ""))
                if len(source_url) > 500 or not source_url.startswith(("https://", "http://")):
                    source_url = ""
                remote_records.append(self._normalize_record({
                    "i": value["i"], "d": str(value.get("d", "")), "c": category,
                    "k": str(value.get("k", self._keywords(note, category))), "n": note,
                    "s": source_url, "l": str(value.get("l", "")),
                }))
        else:
            raise RuntimeError(f"FTP memory contains at least {_MAX_REMOTE_SHARDS} files; refusing an unbounded scan.")
        return self._deduplicate(remote_records), shard_sizes

    def _read_remote_records(self) -> list[dict[str, str]]:
        """Read and validate FTP notes in memory without changing the local cache."""
        if not self.ftp_configured:
            return []
        client = self._connect()
        try:
            with self._lock:
                cached = self._remote_records_cache
            try:
                sizes = tuple(self._remote_shard_sizes(client))
            except Exception:
                sizes = None
            if cached is not None and sizes is not None and sizes == cached[0]:
                return cached[1]
            records, shard_sizes = self._read_remote_shards(client)
            with self._lock:
                self._remote_records_cache = (tuple(shard_sizes), records)
            return records
        finally:
            try:
                client.quit()
            except ftplib.all_errors:
                client.close()

    def remote_categories(self) -> list[str]:
        """List categories currently stored on FTP without syncing locally."""
        return sorted({record.get("c", "Knowledge") for record in self._read_remote_records()})

    def all_records(self) -> list[dict[str, str]]:
        """Return local plus FTP-hosted records, deduped by id, for cross-store analysis."""
        records = list(self.records)
        if self.ftp_configured:
            try:
                known = {record["i"] for record in records}
                for record in self._read_remote_records():
                    if record["i"] not in known:
                        known.add(record["i"])
                        records.append(record)
            except Exception:
                pass
        return records

    @staticmethod
    def _ephemeral_view(
        records: list[dict[str, str]], recall_mesh: "MemoryStore | None" = None,
    ) -> MemoryStore:
        """Build an FTS5 index in RAM only, for query quality without growing Render storage."""
        remote_view = object.__new__(MemoryStore)
        remote_view.records = records
        # Recall on this view also walks the mesh, so it needs the shared state
        # the constructor normally installs.
        remote_view._edges = getattr(recall_mesh, "_edges", {}) if recall_mesh is not None else {}
        remote_view._lock = threading.RLock()
        remote_view._mesh_lock = threading.RLock()
        remote_view._remote_index = None
        # The archive view ranks exactly like its parent, learned vocabulary included.
        remote_view._alias_counts = getattr(recall_mesh, "_alias_counts", {}) if recall_mesh is not None else {}
        # Learned vocabulary and consolidation lineage from the containing store,
        # so the archive view ranks exactly like the local store does.
        try:
            remote_view._index = sqlite3.connect(":memory:")
            remote_view._index.execute(
                "CREATE VIRTUAL TABLE memories USING fts5"
                "(id UNINDEXED, category, keywords, note, tokenize='porter unicode61')"
            )
            remote_view._index.executemany(
                "INSERT INTO memories(id, category, keywords, note) VALUES (?, ?, ?, ?)",
                [(r["i"], r.get("c", "Knowledge"), r.get("k", ""), r["n"]) for r in records],
            )
        except sqlite3.Error:
            if getattr(remote_view, "_index", None) is not None:
                remote_view._index.close()
            remote_view._index = None
        return remote_view

    def relevant_remote(self, query: str, limit: int = 8, max_chars: int = 1800) -> str:
        """Recall and associate FTP notes using MCF3 vocabulary, tags, and categories."""
        try:
            records, _ = self._remote_recall_data()
        except Exception:
            return ""
        if not records:
            return ""
        return self._ephemeral_view(records, recall_mesh=self).relevant(
            query, limit=limit, max_chars=max_chars
        )

    def _remote_recall_data(self) -> tuple[list[dict[str, str]], dict[str, dict[str, str]]]:
        """Return the best available archive: the memory index, else FTP notes.

        The index is the point of this path. Downloading every archive shard on
        each question made recall wait on FTP; the index is one bounded file
        that already holds categories and keywords, so a recall becomes a local
        search plus at most one download.
        """
        with self._lock:
            if self._remote_index:
                return list(self._remote_index.values()), self._remote_index
            if self._remote_index is not None:
                return [], {}
        try:
            remote_index = self._load_remote_index_cached()
        except Exception:
            return self._read_remote_records(), {}
        if remote_index:
            return list(remote_index.values()), remote_index
        # No usable index yet: fall back to the shards themselves, which
        # _read_remote_records caches for the rest of the process.
        return self._read_remote_records(), {}

    def recall_details_remote(self, query: str, limit: int = 8) -> dict[str, object]:
        """Return structured direct and associative matches from FTP-only memory."""
        try:
            records, _ = self._remote_recall_data()
        except Exception:
            records = []
        return self._ephemeral_view(records, recall_mesh=self).recall_details(query, limit=limit)

    def recall_details(self, query: str, limit: int = 8) -> dict[str, object]:
        """Return rich diagnostic details about recall for a given query."""
        cat_filter, tags, _, clean_query = MemoryLanguage.parse_query(query)
        query_terms = {
            word.casefold() for word in _WORDS.findall(clean_query)
            if len(word) > 1 and word.casefold() not in _STOP_WORDS
        }
        for tag in tags:
            query_terms.add(tag)

        direct, related = self._effective_matches(query, limit=limit)

        return {
            "query": query,
            "category_filter": cat_filter,
            "terms": sorted(query_terms),
            "direct": [
                {
                    "id": r["i"],
                    "category": r.get("c", "Knowledge"),
                    "note": r["n"],
                    "date": r.get("d", ""),
                    "provenance": r.get("v", ""),
                    "source": r.get("s", ""),
                }
                for r in direct
            ],
            "related": [
                {
                    "id": record["i"],
                    "category": record.get("c", "Knowledge"),
                    "note": record["n"],
                    "via": reason,
                }
                for reason, record, _ in related[:3]
            ],
            "total_records": len(self.records),
        }

    def _find_records(
        self, terms: set[str], limit: int, original_query: str = "", category_filter: str | None = None,
    ) -> list[dict[str, str]]:
        if not terms and not category_filter:
            return []

        scored_records: list[tuple[float, int, dict[str, str]]] = []
        by_id = {record["i"]: (idx, record) for idx, record in enumerate(self.records)}

        # FTS5's own BM25 rank, normalised, plus a document-frequency table.
        # Counting FTS as a flat +1.5 bonus let loosely related notes outrank
        # tight matches, so its real rank now contributes and common words are
        # weighted down by how many notes contain them.
        expanded_terms = _expand_terms(terms)
        # Learned aliases are query evidence too: asking for one name must reach
        # notes that only use the other.
        evidence_terms, connective_terms = _split_connective_terms(expanded_terms)
        alias_terms = self._alias_group_terms(evidence_terms)
        evidence_terms |= alias_terms
        search_terms = terms | alias_terms

        fts_scores: dict[str, float] = {}
        frequencies = self._term_document_frequencies(search_terms)
        if self._index is not None and terms:
            match_terms = ["\"" + term.replace("\"", "\"\"") + "\"" for term in sorted(search_terms)]
            match_clause = " OR ".join(match_terms)
            try:
                rows = self._index.execute(
                    "SELECT id, bm25(memories, 2.0, 1.5, 1.0) FROM memories WHERE memories MATCH ? LIMIT ?",
                    (match_clause, limit * 4),
                ).fetchall()
                # bm25() returns negative numbers where more negative is better;
                # the best hit becomes 1.0 and the rest scale against it.
                best = min((float(score) for row_id, score in rows if row_id in by_id), default=0.0)
                for row_id, bm25_score in rows:
                    if row_id in by_id and best < 0:
                        fts_scores[row_id] = float(bm25_score) / best
            except sqlite3.Error:
                pass

        # Query-side expansions are identical for every note, so compute them
        # once per search instead of once per record. System-written terms
        # ("related", "consolidated") are excluded from scoring below.
        stemmed_terms = {_stem(term) for term in evidence_terms}
        match_base = 0.0
        for term in evidence_terms:
            frequency = frequencies.get(term, 1)
            if frequency:
                match_base += math.log(1.0 + len(self.records) / frequency)
        match_base = max(match_base, 1.0)
        category_cf = category_filter.casefold() if category_filter else ""
        query_cf = original_query.casefold() if original_query else ""
        # Whole words only: a substring test would let "project" match inside a
        # note's "project status" and, worse, "tea" inside "team".
        query_words = {word.casefold() for word in _WORDS.findall(query_cf)} if query_cf else set()
        for index, record in enumerate(self.records):
            if record.get("c") == _ALIAS_CATEGORY:
                continue  # vocabulary bookkeeping, never knowledge
            if category_cf:
                rec_cat = record.get("c", "").casefold()
                if not (rec_cat == category_cf or rec_cat.startswith(category_cf + "/")):
                    continue

            keywords = set(record.get("k", "").split())
            note_terms = {word.casefold() for word in _WORDS.findall(record["n"])}
            record_terms = keywords | note_terms
            # Mesh edges and consolidation notes were added by the system, not
            # by the user, so their vocabulary is a lead rather than evidence.
            record_terms -= connective_terms

            # IDF-weighted overlap: a rare shared word proves far more than one
            # every note contains. Exact matching still wins over fuzzy, and a
            # synonym or stem match only counts when nothing exact was found.
            matched = evidence_terms & record_terms
            semantic = 0.0
            if matched:
                semantic = 1.0
            else:
                fuzzy = stemmed_terms & {_stem(word) for word in record_terms}
                if fuzzy:
                    semantic = _SEMANTIC_ONLY_WEIGHT

            # A word the system wrote itself (or a stem-only coincidence that
            # FTS also only matched through such a word) is not evidence: the
            # note drops out instead of being ranked on connective vocabulary.
            if record.get("c") == _CONSOLIDATED_CATEGORY:
                # A synthesis is a reading aid over its sources. It is shown
                # through them (see relevant / mesh_recall), never ranked as
                # though what the system wrote were the user's own statement.
                continue
            if not matched and not category_cf:
                continue

            overlap = len(matched)
            idf = sum(
                math.log(1.0 + len(self.records) / max(1, frequencies.get(term, 1)))
                for term in matched
            )
            score = semantic * (idf / match_base) * 10.0 + overlap * 0.5
            if record["i"] in fts_scores:
                score += max(0.0, fts_scores[record["i"]]) * 4.0
            if query_cf and record["n"].casefold() in query_cf:
                score += 4.0
            elif query_words & record_terms:
                score += 1.0
            if category_filter:
                score += 3.0
            # Recency boost: notes appended later (higher index) surface first.
            score += index * 0.02

            scored_records.append((score, index, record))

        scored_records.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [item[2] for item in scored_records[:limit]]

    def _term_document_frequencies(self, terms: set[str]) -> dict[str, int]:
        """Count how many notes contain each query term (IDF signal)."""
        if not terms or self._index is None:
            return {term: 1 for term in terms}
        frequencies: dict[str, int] = {}
        for term in terms:
            quoted = "\"" + term.replace("\"", "\"\"") + "\""
            try:
                row = self._index.execute(
                    "SELECT COUNT(*) FROM memories WHERE memories MATCH ?", (quoted,)
                ).fetchone()
                frequencies[term] = int(row[0]) if row else 1
            except sqlite3.Error:
                frequencies[term] = 1
        return frequencies

    def tree(self) -> str:
        """Render categorized notes as a readable virtual folder tree."""
        root: dict[str, object] = {}
        for record in self.records:
            node = root
            for part in record.get("c", "Knowledge").split("/"):
                node = node.setdefault(part, {})  # type: ignore[assignment]
            node.setdefault("_notes", []).append(record)  # type: ignore[union-attr]

        lines = ["Memory/"]
        def render(node: dict[str, object], depth: int) -> None:
            for key in sorted(k for k in node if k != "_notes"):
                lines.append("  " * depth + f"{key}/")
                render(node[key], depth + 1)  # type: ignore[arg-type]
            for record in node.get("_notes", []):  # type: ignore[union-attr]
                rec_id = record.get("i", "")
                note_str = record.get("n", "")
                id_tag = f"[{rec_id}] " if rec_id else ""
                lines.append("  " * depth + f"- {id_tag}{note_str}")
        render(root, 1)
        return "\n".join(lines)

    def consolidate(self, limit: int = 5) -> dict[str, str] | None:
        """Compress related clusters into notes that name their sources.

        Each synthesis is written under Harold/Understanding/Consolidated with
        its source ids in the record's ``l`` field, so a later reader can see
        exactly which notes it summarises and that it is a *summary*, not
        independently verified knowledge. Source notes are left intact.

        Syntheses are a derived layer: they are never inputs, so one synthesis
        can never become the "source" of the next, and re-running replaces a
        cluster's synthesis instead of duplicating it. Syntheses whose sources
        have vanished are pruned. ``limit`` bounds how many of the largest
        clusters are written.

        Returns the first synthesis written or refreshed, or ``None`` when
        nothing changed. A refreshed entry carries ``"replaced": True``.
        """
        with self._lock:
            source_records = [r for r in self.records if r.get("c") != _CONSOLIDATED_CATEGORY]
            existing = [r for r in self.records if r.get("c") == _CONSOLIDATED_CATEGORY]
        if len(source_records) < 2:
            self._prune_consolidations({r["i"] for r in source_records})
            return None

        # Adjacency via shared, meaningful vocabulary between source notes.
        adjacency: dict[str, set[str]] = {r["i"]: set() for r in source_records}
        term_index: dict[str, set[str]] = {}
        for record in source_records:
            terms = self._content_terms(record) | set(record.get("k", "").split())
            terms -= _split_connective_terms(terms)[1]
            for term in terms:
                term_index.setdefault(term, set()).add(record["i"])
        for ids in term_index.values():
            ids = list(ids)
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    adjacency[ids[i]].add(ids[j])
                    adjacency[ids[j]].add(ids[i])

        components: list[list[str]] = []
        seen: set[str] = set()
        for start_node in adjacency:
            if start_node in seen:
                continue
            stack = [start_node]
            component: list[str] = []
            seen.add(start_node)
            while stack:
                node = stack.pop()
                component.append(node)
                for neighbor in adjacency[node]:
                    if neighbor not in seen:
                        seen.add(neighbor)
                        stack.append(neighbor)
            if len(component) >= 2:
                components.append(component)
        components.sort(key=len, reverse=True)

        by_id = {r["i"]: r for r in source_records}
        created: dict[str, str] | None = None
        handled: set[str] = set()
        for component in components[:max(1, limit)]:
            members = [by_id[node] for node in component if node in by_id]
            if len(members) < 2:
                continue
            lineage = ",".join(sorted(r["i"] for r in members))
            if lineage in handled:
                continue
            handled.add(lineage)
            record = self._write_consolidation(members, lineage, existing)
            if record is not None:
                created = created or record

        self._prune_consolidations({r["i"] for r in source_records})
        return created

    def _write_consolidation(
        self,
        members: list[dict[str, str]],
        lineage: str,
        existing: list[dict[str, str]],
    ) -> dict[str, str] | None:
        """Write or replace the synthesis note for one cluster of notes."""
        if len(lineage) > _MAX_LINEAGE_CHARS:
            return None
        members = sorted(members, key=lambda r: r.get("d", ""))

        # Replace this cluster's previous synthesis rather than duplicating it.
        replaced = False
        for record in existing:
            if record.get("l") == lineage:
                if self.remove(record["i"]) is not None:
                    replaced = True

        joined = " ".join(record["n"] for record in members)
        collapsed = " ".join(joined.split())
        # The prefix states plainly what this note is and how many notes (each
        # carrying at least one source id) it was built from.
        header = f"Consolidated understanding from {len(members)} note(s) (source ids recorded): "
        budget = _MAX_NOTE_CHARS - len(header) - 1
        if len(collapsed) > budget:
            clipped = collapsed[:budget]
            if "" in clipped:
                clipped = clipped[: clipped.rfind(" ")]
            collapsed = clipped.rstrip(" ,;:-") + "…"
        try:
            record = self.add(header + collapsed, category=_CONSOLIDATED_CATEGORY)
        except ValueError:
            return None
        if record is None:
            return None

        # Lineage is metadata, not note text: it gets its own field so it never
        # eats the 500-character note budget or pollutes the keyword vocabulary.
        record["l"] = lineage
        self._write_local()
        self._add_to_index(record)
        for source_id in lineage.split(","):
            self.link(record["i"], source_id, "derived")
        return {**record, "replaced": True} if replaced else record

    def _prune_consolidations(self, live_ids: set[str]) -> int:
        """Delete syntheses whose every source note has gone away."""
        removed = 0
        for record in list(self.records):
            if record.get("c") != _CONSOLIDATED_CATEGORY:
                continue
            sources = [item for item in record.get("l", "").split(",") if item]
            if sources and not (set(sources) & live_ids):
                if self.remove(record["i"]) is not None:
                    removed += 1
        return removed

    def consolidation_sources(self, record_id: str) -> list[str]:
        """Return the source note ids a synthesis was built from."""
        for record in self.records:
            if record["i"] == record_id:
                return [item for item in record.get("l", "").split(",") if item]
        return []

    # -- mesh net -----------------------------------------------------------
    def _load_edges(self) -> None:
        """Load the compact mesh adjacency from the sidecar JSON file."""
        self._edges: dict[str, dict[str, str]] = {}
        try:
            raw = self._edges_path.read_text(encoding="utf-8")
        except OSError:
            return
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return
        if not isinstance(data, dict):
            return
        for source, targets in data.items():
            if not isinstance(targets, dict):
                continue
            self._edges[str(source)] = {str(t): str(r) for t, r in targets.items()}

    def _save_edges(self) -> None:
        """Persist the mesh adjacency as compact JSON."""
        self._edges_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._edges_path.with_name(f"{self._edges_path.name}.{os.getpid()}.tmp")
        with temporary.open("w", encoding="utf-8", newline="\n") as output:
            json.dump(self._edges, output, ensure_ascii=False, separators=(",", ":"))
        os.replace(temporary, self._edges_path)

    def _mesh_autolink(
        self, record: dict[str, str], known_ids: set[str] | None = None,
    ) -> int:
        """Link a new note to its closest existing notes so mesh recall can expand.

        Without this, notes only joined the mesh when someone wrote an explicit
        ``rel:<id>`` link, so mesh recall had almost no graph to walk. Shared
        terms are weighted by rarity so one common word cannot fake a relation.
        """
        if not _MESH_AUTOLINK_ENABLED:
            return 0
        by_id = {item["i"]: item for item in self.records}
        candidate_ids = known_ids if known_ids is not None else set(by_id)
        term_freq: dict[str, int] = {}
        doc_terms: dict[str, set[str]] = {}
        for node_id in candidate_ids:
            if node_id == record["i"]:
                continue
            other = by_id.get(node_id)
            if other is None:
                continue
            terms = set(other.get("k", "").split())
            doc_terms[node_id] = terms
            for term in terms:
                term_freq[term] = term_freq.get(term, 0) + 1
        new_terms = set(record.get("k", "").split())
        if not new_terms:
            return 0
        scored: list[tuple[float, str]] = []
        for node_id, terms in doc_terms.items():
            shared = new_terms & terms
            if not shared:
                continue
            weight = sum(1.0 / (1.0 + term_freq.get(term, 1)) for term in shared)
            if len(shared) >= 2 or weight >= _MESH_AUTOLINK_MIN_WEIGHT:
                scored.append((weight, node_id))
        scored.sort(reverse=True)

        linked = 0
        for _, node_id in scored[:_MESH_AUTOLINK_MAX_LINKS]:
            if node_id not in self._edges.get(record["i"], {}):
                self._edges.setdefault(record["i"], {})[node_id] = "auto"
                self._edges.setdefault(node_id, {})[record["i"]] = "auto"
                linked += 1
        if linked:
            self._save_edges()
        return linked
    def link(self, source_id: str, target_id: str, relation: str = "related") -> None:
        """Create a bidirectional mesh edge between two notes."""
        source_id = source_id.strip()
        target_id = target_id.strip()
        if not source_id or not target_id or source_id == target_id:
            return
        with self._mesh_lock:
            self._edges.setdefault(source_id, {})[target_id] = relation
            self._edges.setdefault(target_id, {})[source_id] = relation
            self._save_edges()

    def unlink(self, source_id: str, target_id: str) -> None:
        """Remove a mesh edge between two notes."""
        with self._mesh_lock:
            for side, other in ((source_id, target_id), (target_id, source_id)):
                targets = self._edges.get(side)
                if targets and other in targets:
                    del targets[other]
            self._save_edges()

    def neighbors(self, node_id: str) -> list[tuple[str, str]]:
        """Return (neighbor_id, relation) pairs for a mesh node."""
        return [(nid, rel) for nid, rel in self._edges.get(node_id, {}).items()]

    def mesh_stats(self) -> dict[str, int]:
        """Count mesh nodes and undirected edges for status reporting."""
        return {
            "nodes": len(self._edges),
            "edges": sum(len(targets) for targets in self._edges.values()) // 2,
        }

    def _mesh_bfs(self, seeds: list[str], depth: int = 2) -> list[str]:
        """Traverse the mesh from seed node ids, breadth-first, up to depth."""
        seen: set[str] = set(seeds)
        frontier = list(seeds)
        ordered: list[str] = []
        for _ in range(max(0, depth)):
            next_frontier: list[str] = []
            for node in frontier:
                for neighbor, _ in self.neighbors(node):
                    if neighbor not in seen:
                        seen.add(neighbor)
                        next_frontier.append(neighbor)
                        ordered.append(neighbor)
            if not next_frontier:
                break
            frontier = next_frontier
        return ordered

    def mesh_recall(
        self, query: str, limit: int = 8, max_chars: int = 1800,
    ) -> str:
        """Recall notes by keyword, then expand through the mesh graph.

        Seed notes come from keyword/FTS recall; the mesh then pulls in
        directly linked notes so a cluster of related facts surfaces together.
        """
        cat_filter, tags, _, clean_query = MemoryLanguage.parse_query(query)
        query_terms = {
            word.casefold() for word in _WORDS.findall(clean_query)
            if len(word) > 1 and word.casefold() not in _STOP_WORDS
        }
        for tag in tags:
            query_terms.add(tag)
        if not query_terms:
            return ""

        seeds = [r["i"] for r in self._find_records(query_terms, limit, clean_query, category_filter=cat_filter)]
        if not seeds:
            return ""

        mesh_order = self._mesh_bfs(seeds, depth=2)
        ordered_ids = seeds + [nid for nid in mesh_order if nid not in seeds]
        by_id = {record["i"]: record for record in self.records}
        # Notes pulled in by the mesh may live in the synced archive rather
        # than the bounded local cache.
        missing = [node_id for node_id in ordered_ids if node_id not in by_id]
        if missing:
            with self._lock:
                archived = self._remote_index or {}
            for node_id in missing:
                if node_id in archived:
                    by_id[node_id] = archived[node_id]

        selected: list[str] = []
        used = 0
        for node_id in ordered_ids:
            record = by_id.get(node_id)
            if record is None:
                continue
            provenance = f"; saved {record.get('d', 'date unknown')}; {record['v']}"
            provenance += f"; source {record['s']}" if record.get("s") else ""
            line = f"- [{record.get('c', 'Knowledge')}{provenance}] {record['n']}"
            extra = len(line) + (1 if selected else 0)
            if used + extra > max_chars:
                continue
            selected.append(line)
            used += extra
        return "\n".join(selected)

    def _connect(
        self,
        timeout: float = 20.0,
        stage_callback: Callable[[str], None] | None = None,
    ) -> ftplib.FTP:
        if not self.ftp_configured:
            if self.ftp_partially_configured:
                raise RuntimeError("Set MEMORY_FTP_HOST, MEMORY_FTP_USER, and MEMORY_FTP_PASSWORD to enable sync.")
            raise RuntimeError("FTP sync is not configured.")
        if self.ftp_tls:
            client: ftplib.FTP = ftplib.FTP_TLS(context=ssl.create_default_context())
        else:
            client = ftplib.FTP()
        if stage_callback:
            stage_callback("connecting")
        client.connect(self.ftp_host, timeout=timeout)
        if stage_callback:
            stage_callback("authenticating")
        client.login(self.ftp_user, self.ftp_password)
        if self.ftp_base_dir:
            if stage_callback:
                stage_callback("opening configured directory")
            client.cwd(self.ftp_base_dir)
        if self.ftp_tls and isinstance(client, ftplib.FTP_TLS):
            if stage_callback:
                stage_callback("enabling FTPS data protection")
            client.prot_p()
        if hasattr(client, "set_pasv"):
            if stage_callback:
                stage_callback("enabling passive mode")
            try:
                client.set_pasv(True)
            except Exception:
                pass
        return client

    def verify_ftp(self, timeout: float = 8.0) -> tuple[bool, str]:
        """Verify FTP login and directory listing without writing remote data."""
        if not self.ftp_configured:
            return False, "not configured"
        client: ftplib.FTP | None = None
        stage = "connecting"

        def update_stage(value: str) -> None:
            nonlocal stage
            stage = value

        try:
            client = self._connect(timeout=timeout, stage_callback=update_stage)
            stage = "checking current directory"
            client.pwd()
            stage = "listing remote directory"
            visible_entries = client.nlst()
            return True, (
                f"connected; login/list OK; {len(visible_entries)} directory entries visible; "
                "write permission not tested"
            )
        except Exception as exc:
            message = str(exc)
            for secret in (self.ftp_password, self.ftp_user):
                if secret:
                    message = message.replace(secret, "[redacted]")
            if self.ftp_host:
                message = message.replace(self.ftp_host, "[host]")
            hints = {
                "connecting": (
                    "No FTP control connection was established. Check the hostname, port 21, "
                    "server availability, and whether Render outbound connections are allowed."
                ),
                "authenticating": "The server answered, but login failed; check the FTP username and password.",
                "opening configured directory": "Login succeeded; check the configured FTP base directory and access rights.",
                "enabling FTPS data protection": "The server may not support explicit FTPS; check MEMORY_FTP_TLS.",
                "checking current directory": "Login succeeded, but the server rejected PWD.",
                "listing remote directory": (
                    "Login succeeded, but directory listing failed; check LIST/NLST permission and passive FTP data ports."
                ),
            }
            hint = hints.get(stage, "Check the FTP server settings and connectivity.")
            return False, f"{stage}: {type(exc).__name__}: {message[:180]}. {hint}"
        finally:
            if client is not None:
                try:
                    client.quit()
                except ftplib.all_errors:
                    client.close()

    @staticmethod
    def _encode_record(record: dict[str, str]) -> bytes:
        payload = (json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        if len(payload) > _MAX_RECORD_BYTES:
            raise RuntimeError(f"Memory record exceeds the {_MAX_RECORD_BYTES}-byte upload limit.")
        return payload

    def _remote_shard_sizes(self, client: ftplib.FTP) -> list[int]:
        """Return sizes of consecutive archive files using FTP SIZE, without downloading them."""
        try:
            client.sendcmd("TYPE I")
        except ftplib.all_errors:
            pass
        sizes: list[int] = []
        for index in range(_MAX_REMOTE_SHARDS):
            try:
                size = client.size(self._remote_shard_path(index))
            except ftplib.error_perm as exc:
                if str(exc).startswith("550"):
                    break
                raise
            except ftplib.all_errors as exc:
                raise RuntimeError("FTP server must support SIZE for safe capped-file uploads.") from exc
            if size is None:
                raise RuntimeError("FTP server must support SIZE for safe capped-file uploads.")
            if size > self.max_remote_bytes:
                raise RuntimeError(
                    f"FTP memory file {self._remote_shard_path(index)} is {size} bytes, "
                    f"above the configured per-file cap of {self.max_remote_bytes}."
                )
            sizes.append(size)
        else:
            raise RuntimeError(f"FTP memory contains at least {_MAX_REMOTE_SHARDS} files.")
        return sizes

    def _append_payloads(
        self, client: ftplib.FTP, payloads: list[bytes], shard_sizes: list[int] | None = None,
    ) -> None:
        """Preflight and append records, rotating to new files at the per-file cap."""
        if not payloads:
            return
        if shard_sizes is None:
            shard_sizes = self._remote_shard_sizes(client)
        original_count = len(shard_sizes)
        sizes = list(shard_sizes)
        groups: list[tuple[int, list[bytes]]] = []
        for payload in payloads:
            if len(payload) > self.max_remote_bytes:
                raise RuntimeError(
                    f"A memory record is larger than the configured {self.max_remote_bytes}-byte FTP file limit."
                )
            index = max(0, len(sizes) - 1)
            size = sizes[index] if sizes else 0
            if sizes and size + len(payload) > self.max_remote_bytes:
                index += 1
                size = 0
            if index >= _MAX_REMOTE_SHARDS:
                raise RuntimeError("FTP memory has reached the maximum supported shard count.")
            if groups and groups[-1][0] == index:
                groups[-1][1].append(payload)
            else:
                groups.append((index, [payload]))
            if index == len(sizes):
                sizes.append(0)
            sizes[index] = size + len(payload)

        # All records fit before the first remote write is attempted.
        for index, group in groups:
            command = "APPE " if index < original_count else "STOR "
            payload_bytes = b"".join(group)
            shard_path = self._remote_shard_path(index)
            try:
                _ftp_store_binary(client, command + shard_path, io.BytesIO(payload_bytes))
            except ftplib.all_errors as exc:
                if not command.strip().upper().startswith("APPE"):
                    raise
                # Some FTP servers (e.g. Geocities) reject APPE with
                # "451 Append/Restart not permitted". Fall back to downloading
                # the existing shard, appending locally, and STORing it back.
                existing = self._download_shard_bytes(client, shard_path)
                _ftp_store_binary(client, "STOR " + shard_path, io.BytesIO(existing + payload_bytes))

    def _download_shard_bytes(self, client: ftplib.FTP, path: str) -> bytes:
        """Download an entire remote shard into memory for append-then-upload fallback."""
        buf: list[bytes] = []
        _ftp_retr_binary(client, "RETR " + path, buf.append)
        return b"".join(buf)

    def upload(self, record: dict[str, str]) -> None:
        """Append one note to the current capped FTP shard or create the next shard."""
        self.upload_many([record])

    def upload_many(self, records: list[dict[str, str]], timeout: float = 20.0) -> int:
        """Append several notes in one FTP session, with retry and an index refresh."""
        uploaded, _ = self.upload_notes(records, timeout=timeout)
        return uploaded

    def sync(self) -> tuple[int, int]:
        """Merge capped FTP shards with the bounded local cache and upload local-only notes."""
        client = self._connect()
        try:
            remote_records = self._archive_records(client)
            shard_sizes = self._remote_shard_sizes(client)

            remote_ids = {record["i"] for record in remote_records}
            merged = self._deduplicate(remote_records + self.records)
            remote_added = sum(record["i"] not in {item["i"] for item in self.records} for record in remote_records)
            pending = [record for record in merged if record["i"] not in remote_ids]
            payloads = [self._encode_record(record) for record in pending]
            self._append_payloads(client, payloads, shard_sizes)
            index = self._build_index_map(merged)
            # The archive index and mesh are accelerators. If either upload fails
            # the notes are already safe, so never fail the whole sync over them.
            try:
                self._store_remote_index(client, index)
            except Exception as exc:
                print(f"⚠️ FTP archive index upload failed: {type(exc).__name__}")
            # Mesh links are a convenience: recall with the keyword index still
            # works without them, and older archive layouts may have no mesh
            # folder, so a failure here is intentionally quiet.
            try:
                self._store_remote_mesh(client, self._build_mesh_map(merged))
            except Exception:
                pass
            with self._lock:
                self._remote_index = index
            self.records = merged[-self.max_local_records:]
            self._write_local()
            self._rebuild_index()
            return remote_added, len(payloads)
        finally:
            try:
                client.quit()
            except ftplib.all_errors:
                client.close()

    def upload_notes(
        self, records: list[dict[str, str]], timeout: float = 20.0,
    ) -> tuple[int, int]:
        """Upload notes and refresh the archived index on the same FTP session.

        Returns ``(notes_uploaded, connections_used)``. Transient transport
        failures get a fresh login, so one dropped data port does not silently
        lose a note; permanent replies (bad credentials, quota) raise at once.
        """
        payloads = [self._encode_record(record) for record in records]
        if not payloads:
            return 0, 0
        attempts = max(1, _SYNC_MAX_ATTEMPTS)
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                client = self._connect(timeout=timeout)
                try:
                    self._append_payloads(client, payloads)
                    # Refresh the archive lookup index in the same session, or a
                    # freshly deployed instance would re-download every shard it
                    # was just handed before it could answer a question.
                    with self._lock:
                        index = dict(self._remote_index) if self._remote_index else {}
                    for record in records:
                        index[record["i"]] = record
                    refreshed = self._build_index_map(list(index.values()))
                    try:
                        self._store_remote_index(client, refreshed)
                    except Exception as exc:
                        print(f"⚠️ FTP archive index refresh failed: {type(exc).__name__}")
                finally:
                    try:
                        client.quit()
                    except ftplib.all_errors:
                        client.close()
                with self._lock:
                    self._remote_records_cache = None
                    if self._remote_index is None:
                        self._remote_index = refreshed
                    else:
                        for record in records:
                            self._remote_index[record["i"]] = record
                return len(payloads), attempt + 1
            except ftplib.error_perm:
                raise
            except (OSError, EOFError, ftplib.error_temp) as exc:
                last_error = exc
                if attempt + 1 < attempts:
                    time.sleep(_SYNC_BACKOFF_SECONDS * (2 ** attempt))
        raise RuntimeError(
            f"FTP upload failed after {attempts} attempt(s): {type(last_error).__name__}: {last_error}"
        ) from last_error

    def _archive_records_view(self) -> list[dict[str, str]]:
        """Notes from the archive index, when one is already loaded. No I/O."""
        with self._lock:
            return list(self._remote_index.values()) if self._remote_index else []

    # -- learned vocabulary --------------------------------------------------
    def _load_aliases(self) -> None:
        """Rebuild the alias table from stored evidence notes."""
        self._alias_counts = {}
        for record in self.records:
            if record.get("c") != _ALIAS_CATEGORY:
                continue
            match = _ALIAS_STORED_RE.match(record.get("n", "").strip())
            if not match:
                continue
            head, alias = match.group(1).casefold(), match.group(2).casefold()
            if head == alias:
                continue
            # One row is already a validated pair: a row is only written once
            # two distinct notes agree. Record that as the minimum evidence so
            # a consumer asking for "well-supported" aliases sees this one.
            # Aliases are bidirectional: either name should reach the other.
            for left, right in ((head, alias), (alias, head)):
                entry = self._alias_counts.setdefault(left, {})
                entry[right] = max(entry.get(right, 0), _ALIAS_MIN_COUNT)

    @staticmethod
    def _phrase_words(record: dict[str, str]) -> list[str]:
        """Content words of a note, in order, with system vocabulary removed."""
        words = [
            word.casefold() for word in _WORDS.findall(record.get("n", ""))
            if len(word) > 2 and word.casefold() not in _STOP_WORDS
        ]
        _, connective = _split_connective_terms(set(words))
        return [word for word in words if word not in connective]

    @classmethod
    def _alias_terms(cls, record: dict[str, str]) -> list[str]:
        """Words of a note that could name a subject (no verbs, no boilerplate)."""
        return [
            word for word in cls._phrase_words(record)
            if _stem_term(word) not in _ALIAS_VERB_STEMS and word not in _ALIAS_BOILERPLATE
        ]

    def _learn_aliases(
        self, record: dict[str, str], extra_records: list[dict[str, str]] | None = None,
    ) -> list[str]:
        """Learn a second name for a recurring subject, and return notes written.

        The rule is deliberately strict: compare this note with each earlier
        note, and if both share a subject that recurs across the store *and*
        both open on it ("python scripting ..." / "python automates ..."), then
        the word this note adds after that subject is a second name for it.

        A pair is only recorded once two distinct notes agree. One restatement
        is a guess, so it changes nothing; a repeated one is evidence.
        """
        if record.get("c") == _ALIAS_CATEGORY:
            return []
        self._load_aliases()
        words = self._alias_terms(record)
        if len(words) < 2:
            return []

        pool = {item["i"]: item for item in (extra_records or [])}
        pool.update({item["i"]: item for item in self.records})
        pool.pop(record["i"], None)
        others = list(pool.values())
        if not others:
            return []

        # A subject recurs across the store. Ties go to the word said first.
        support: dict[str, int] = {}
        for word in words:
            support[word] = sum(1 for other in others if word in self._alias_terms(other))
        if not support:
            return []
        strongest = max(support.values())
        candidates = {word for word, count in support.items() if count == strongest}
        subject = next(word for word in words if word in candidates)

        supporters = [other for other in others if subject in self._alias_terms(other)]
        if len(supporters) < _ALIAS_MIN_COUNT:
            return []
        # The second name is a word this note raises *besides* the subject and
        # that an earlier note already paired with the subject. "python
        # scripting" repeats; "dashboard" appears once and is a topic, not a
        # name for python. This is what makes "seen twice" mean something.
        # The name is what the *earlier* notes say next to the subject. The
        # current note only establishes the subject ("python automates ...");
        # earlier notes supply the second word ("python scripting ...").
        remainder, votes = "", 0
        for other in supporters:
            other_words = self._alias_terms(other)
            if subject not in other_words:
                continue
            index = other_words.index(subject)
            for word in other_words[index + 1:]:
                if word in candidates or word in _ALIAS_BOILERPLATE:
                    continue
                paired = sum(
                    1 for peer in supporters
                    if word in self._alias_terms(peer) and subject in self._alias_terms(peer)
                )
                if paired > votes:
                    remainder, votes = word, paired
        # One earlier note naming the pair, plus this restatement, is two
        # distinct sightings -- the point at which the pair stops being a guess.
        if not remainder or votes < 1:
            return []

        # Evidence lives in the notes, so the count is rebuilt from them: a
        # pair already written stays learned, and re-learning writes nothing.
        if self._alias_counts.get(subject, {}).get(remainder, 0):
            return []
        note = f"ALIAS {subject} => {remainder}"
        if self.add(note, category=_ALIAS_CATEGORY) is None:
            return []
        self._load_aliases()
        return [note]

    def _alias_group_terms(self, terms: set[str]) -> set[str]:
        """Expand query terms with every alias whose evidence has enough notes."""
        expanded: set[str] = set()
        for term in terms:
            for alias, count in self._alias_counts.get(term, {}).items():
                if count >= 1:
                    expanded.add(alias)
        return expanded - terms

    def alias_table(self, min_count: int = 1) -> dict[str, dict[str, int]]:
        """Learned vocabulary and its evidence, for the admin panel and tests."""
        return {
            head: {alias: count for alias, count in aliases.items() if count >= min_count}
            for head, aliases in self._alias_counts.items()
            if any(count >= min_count for count in aliases.values())
        }

    def _archive_records(self, client: ftplib.FTP) -> list[dict[str, str]]:
        """Prefer the small archived index over downloading every note shard."""
        if hasattr(client, "set_pasv"):
            try:
                client.set_pasv(True)
            except ftplib.all_errors:
                pass
        try:
            index = self._read_remote_index(client)
        except Exception as exc:
            print(f"⚠️ FTP archive index read failed: {type(exc).__name__}; reading shards instead.")
            index = None
        if index:
            return list(index.values())
        records, _ = self._read_remote_shards(client)
        return records

    # -- archived index and mesh -------------------------------------------
    @staticmethod
    def _build_index_map(records: list[dict[str, str]]) -> dict[str, dict[str, str]]:
        """Project notes down to the fields recall needs."""
        index: dict[str, dict[str, str]] = {}
        for record in records:
            entry = {"i": record["i"], "c": record.get("c", "Knowledge"), "n": record["n"]}
            for field in ("k", "d", "s", "l"):
                if record.get(field):
                    entry[field] = record[field]
            index[record["i"]] = entry
        return index

    def _build_mesh_map(
        self, records: list[dict[str, str]], edges: dict[str, dict[str, str]] | None = None,
    ) -> dict[str, dict[str, str]]:
        """Return the mesh restricted to notes that still exist."""
        known = {record["i"] for record in records}
        source = edges if edges is not None else self._edges
        return {
            node: {other: rel for other, rel in targets.items() if other in known}
            for node, targets in source.items()
            if node in known
        }

    @staticmethod
    def _encode_index(index: dict[str, dict[str, str]]) -> bytes:
        return b"".join(
            (json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
            for entry in index.values()
        )

    def _store_remote_index(self, client: ftplib.FTP, index: dict[str, dict[str, str]]) -> None:
        _ftp_store_binary(client, "STOR " + self.remote_index_path, io.BytesIO(self._encode_index(index)))

    def _store_remote_mesh(self, client: ftplib.FTP, mesh: dict[str, dict[str, str]]) -> None:
        payload = json.dumps(mesh, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(payload) > _MESH_MAX_REMOTE_BYTES:
            print("⚠️ Mesh is too large to archive; skipping its FTP upload.")
            return
        folder = self.remote_mesh_path.rsplit("/", 1)[0]
        if folder:
            self._make_remote_dirs(client, folder)
        _ftp_store_binary(client, "STOR " + self.remote_mesh_path, io.BytesIO(payload))

    @staticmethod
    def _make_remote_dirs(client: ftplib.FTP, folder: str) -> None:
        """Create nested remote folders, ignoring ones that already exist."""
        # Other archive paths are relative to the configured base directory, so
        # leave the session where it started once the folders exist.
        try:
            start = client.pwd()
        except (AttributeError, ftplib.all_errors):
            start = None
        current = ""
        for part in folder.split("/"):
            if not part:
                continue
            current = f"{current}/{part}" if current else part
            try:
                client.cwd(current)
            except (AttributeError, ftplib.all_errors):
                try:
                    client.mkd(current)
                except (AttributeError, ftplib.all_errors):
                    pass
        try:
            client.cwd(start or "/")
        except (AttributeError, ftplib.all_errors):
            pass

    def _read_remote_index(self, client: ftplib.FTP) -> dict[str, dict[str, str]] | None:
        """Download and validate the archived index; ``None`` when it is absent."""
        chunks: list[bytes] = []
        received = 0
        limit = _MAX_REMOTE_SHARDS * self.max_remote_bytes

        def collect(chunk: bytes) -> None:
            nonlocal received
            received += len(chunk)
            if received > limit:
                raise RuntimeError("FTP archive index exceeds the archive size limit.")
            chunks.append(chunk)

        try:
            _ftp_retr_binary(client, "RETR " + self.remote_index_path, collect)
        except ftplib.error_perm as exc:
            if str(exc).startswith("550"):
                return None
            raise
        index: dict[str, dict[str, str]] = {}
        for raw_line in b"".join(chunks).splitlines():
            if len(raw_line) > _MAX_RECORD_BYTES:
                continue
            try:
                value = json.loads(raw_line.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            if not self._valid_record(value):
                continue
            note = self._normalize_note(value["n"])
            category = str(value.get("c", "Knowledge"))
            source_url = str(value.get("s", ""))
            if len(source_url) > 500 or not source_url.startswith(("https://", "http://")):
                source_url = ""
            index[value["i"]] = self._normalize_record({
                "i": value["i"], "d": str(value.get("d", "")), "c": category,
                "k": str(value.get("k", self._keywords(note, category))), "n": note,
                "s": source_url, "l": str(value.get("l", "")),
            })
        return index

    def _load_remote_index_cached(self) -> dict[str, dict[str, str]]:
        """Fetch the archived index (and mesh) once per process and remember them."""
        return self._load_archive()

    def _load_archive(self, force: bool = False) -> dict[str, dict[str, str]]:
        """Download the archived index and mesh in one FTP session.

        ``force`` is used by sync/startup, which must see the server's current
        state; ordinary recall reuses whatever is already in RAM.
        """
        with self._lock:
            if self._remote_index and not force:
                return self._remote_index
        client = self._connect()
        try:
            index = self._read_remote_index(client)
            mesh = self._read_remote_mesh(client)
        finally:
            try:
                client.quit()
            except ftplib.all_errors:
                client.close()
        # An empty dict records "checked, nothing archived yet" so a pre-upgrade
        # archive is not re-probed on every question.
        index = index or {}
        with self._lock:
            self._remote_index = index
        if mesh:
            self._import_remote_mesh(mesh)
        return index

    def warm(self) -> int:
        """Load the archive index and mesh into RAM. Returns the note count."""
        index = self._load_archive(force=True)
        return len(index)

    def _read_remote_mesh(self, client: ftplib.FTP) -> dict[str, dict[str, str]]:
        """Download the optional archived mesh; ``{}`` when it is absent."""
        chunks: list[bytes] = []
        received = 0

        def collect(chunk: bytes) -> None:
            nonlocal received
            received += len(chunk)
            if received > _MESH_MAX_REMOTE_BYTES:
                raise RuntimeError("FTP mesh exceeds its size limit.")
            chunks.append(chunk)

        try:
            _ftp_retr_binary(client, "RETR " + self.remote_mesh_path, collect)
        except ftplib.error_perm:
            return {}
        try:
            data = json.loads(b"".join(chunks).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}
        if not isinstance(data, dict):
            return {}
        return {
            str(node): {str(other): str(rel) for other, rel in targets.items() if isinstance(targets, dict)}
            for node, targets in data.items()
            if isinstance(targets, dict)
        }

    def _import_remote_mesh(self, mesh: dict[str, dict[str, str]]) -> None:
        """Merge an archived mesh into the in-memory graph and persist it locally."""
        with self._mesh_lock:
            changed = False
            for node, targets in mesh.items():
                current = self._edges.setdefault(node, {})
                for other, relation in targets.items():
                    if other not in current:
                        current[other] = relation
                        changed = True
            if changed:
                self._save_edges()

    def _migrate_mesh_file_once(self) -> None:
        """Re-home a legacy sidecar mesh so mesh links survive FTP sync."""
        legacy = self.path.with_suffix(".mesh.json")
        if legacy == self._edges_path or not legacy.is_file() or self._edges_path.is_file():
            return
        try:
            data = json.loads(legacy.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            return
        if isinstance(data, dict) and data:
            self._edges = {
                str(node): {str(other): str(rel) for other, rel in targets.items()}
                for node, targets in data.items() if isinstance(targets, dict)
            }
            self._save_edges()
