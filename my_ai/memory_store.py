#!/usr/bin/env python3
"""MCF3 notes with a bounded local cache and size-limited FTP/FTPS archive shards."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
import ftplib
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import ssl
from urllib.parse import urlsplit
import uuid


_WORDS = re.compile(r"[^\W_]+", re.UNICODE)
_TAG_RE = re.compile(r"#([a-zA-Z0-9_\-]+)")
_REL_RE = re.compile(r"(?:rel:|->\s*)([a-zA-Z0-9_/.\-]+)")
_SOURCE_URL_RE = re.compile(r"\^(https?://[a-zA-Z0-9_\-./?&=%#]+)")

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


def _expand_terms(terms: set[str]) -> set[str]:
    """Return terms plus their curated synonyms (query-side expansion)."""
    expanded: set[str] = set(terms)
    for term in terms:
        expanded.update(_SYNONYMS.get(term, ()))
    return expanded


_MAX_NOTE_CHARS = 500
_MAX_RECORD_BYTES = 4096
_HARD_REMOTE_MAX_BYTES = 64 * 1024
_DEFAULT_REMOTE_MAX_BYTES = 32 * 1024
_DEFAULT_LOCAL_CACHE_RECORDS = 50
_MAX_REMOTE_SHARDS = 10_000


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
        self._load_edges()
        self._open_index()

    def _open_index(self) -> None:
        """Build or update a persistent full-text index with Porter stemming."""
        try:
            self._index_path.parent.mkdir(parents=True, exist_ok=True)
            self._index = sqlite3.connect(self._index_path)

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
                or not isinstance(source, str) or len(source) > 500):
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
                        records.append({
                            "i": value["i"], "d": str(value.get("d", "")), "c": category,
                            "k": str(value.get("k", self._keywords(note, category))), "n": note,
                            "s": source_url, "v": MemoryStore._source_status(source_url),
                        })
        except OSError:
            return []
        return self._deduplicate(records)

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
            category = record.get("c", "Knowledge")
            clean = {"i": record["i"], "d": record.get("d", ""), "c": category,
                     "k": record.get("k", MemoryStore._keywords(note, category)), "n": note,
                     "s": source, "v": MemoryStore._source_status(source)}
            by_id[clean["i"]] = clean
            seen_notes.add(note_key)
            result.append(clean)
        return result

    def _write_local(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + ".tmp")
        with temporary.open("w", encoding="utf-8", newline="\n") as output:
            for record in self.records:
                output.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        os.replace(temporary, self.path)

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
                self.records.append({"i": uuid.uuid4().hex[:12], "d": "", "c": "Knowledge", "n": note})
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
        self.records.append(record)
        self._trim_local_cache()
        self._write_local()
        self._rebuild_index()
        # Wire explicit mesh edges from any rel:<note-id> references in the note.
        for rel in _REL_RE.findall(final_note):
            rel = rel.strip()
            if re.fullmatch(r"[a-fA-F0-9]{12}", rel):
                self.link(record["i"], rel, "rel")
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

        removed = self.records.pop(match_idx)
        self._write_local()
        # Drop mesh edges touching the removed note.
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
                client.storbinary("STOR " + self._remote_shard_path(index), io.BytesIO(contents))
            for index in range(len(grouped), len(old_sizes)):
                try:
                    client.delete(self._remote_shard_path(index))
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
        cat_filter, tags, _, clean_query = MemoryLanguage.parse_query(query)
        query_terms = {
            word.casefold() for word in _WORDS.findall(clean_query)
            if len(word) > 1 and word.casefold() not in _STOP_WORDS
        }
        for tag in tags:
            query_terms.add(tag)

        if not query_terms:
            return ""

        ranked = self._find_records(query_terms, limit * 4, clean_query, category_filter=cat_filter)
        direct = ranked[:limit]

        # Build associative graph outward from direct matches
        direct_ids = {record["i"] for record in direct}
        linked_terms: set[str] = set()
        for record in direct:
            linked_terms.update(record.get("k", "").split())
        bridge_terms = linked_terms - query_terms
        related_candidates = self._find_records(bridge_terms, limit * 3, category_filter=cat_filter) if bridge_terms else []
        related: list[tuple[int, dict[str, str], list[str]]] = []
        for record in related_candidates:
            if record["i"] in direct_ids:
                continue
            overlap = sorted(bridge_terms & set(record.get("k", "").split()))
            if overlap:
                related.append((len(overlap), record, overlap))
        related.sort(key=lambda item: (item[0], item[1].get("d", "")), reverse=True)

        selected: list[str] = []
        used = 0
        for record in direct:
            provenance = f"; saved {record.get('d', 'date unknown')}; {record['v']}"
            provenance += f"; source {record['s']}" if record.get("s") else ""
            line = f"- [{record.get('c', 'Knowledge')}{provenance}] {record['n']}"
            extra = len(line) + (1 if selected else 0)
            if used + extra > max_chars:
                continue
            selected.append(line)
            used += extra
        for _, record, overlap in related[:2]:
            provenance = f"; saved {record.get('d', 'date unknown')}; {record['v']}"
            provenance += f"; source {record['s']}" if record.get("s") else ""
            line = f"- [RELATED via {', '.join(overlap[:3])}; {record.get('c', 'Knowledge')}{provenance}] {record['n']}"
            extra = len(line) + (1 if selected else 0)
            if used + extra > max_chars:
                continue
            selected.append(line)
            used += extra
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
                client.retrbinary("RETR " + self._remote_shard_path(index), collect)
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
                remote_records.append({
                    "i": value["i"], "d": str(value.get("d", "")), "c": category,
                    "k": str(value.get("k", self._keywords(note, category))), "n": note,
                    "s": source_url, "v": self._source_status(source_url),
                })
        else:
            raise RuntimeError(f"FTP memory contains at least {_MAX_REMOTE_SHARDS} files; refusing an unbounded scan.")
        return self._deduplicate(remote_records), shard_sizes

    def _read_remote_records(self) -> list[dict[str, str]]:
        """Read and validate FTP notes in memory without changing the local cache."""
        if not self.ftp_configured:
            return []
        client = self._connect()
        try:
            records, _ = self._read_remote_shards(client)
            return records
        finally:
            try:
                client.quit()
            except ftplib.all_errors:
                client.close()

    def remote_categories(self) -> list[str]:
        """List categories currently stored on FTP without syncing locally."""
        return sorted({record.get("c", "Knowledge") for record in self._read_remote_records()})

    @staticmethod
    def _ephemeral_view(records: list[dict[str, str]]) -> MemoryStore:
        """Build an FTS5 index in RAM only, for query quality without growing Render storage."""
        remote_view = object.__new__(MemoryStore)
        remote_view.records = records
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
        remote_view = self._ephemeral_view(self._read_remote_records())
        return remote_view.relevant(query, limit=limit, max_chars=max_chars)

    def recall_details_remote(self, query: str, limit: int = 8) -> dict[str, object]:
        """Return structured direct and associative matches from FTP-only memory."""
        remote_view = self._ephemeral_view(self._read_remote_records())
        return remote_view.recall_details(query, limit=limit)

    def recall_details(self, query: str, limit: int = 8) -> dict[str, object]:
        """Return rich diagnostic details about recall for a given query."""
        cat_filter, tags, _, clean_query = MemoryLanguage.parse_query(query)
        query_terms = {
            word.casefold() for word in _WORDS.findall(clean_query)
            if len(word) > 1 and word.casefold() not in _STOP_WORDS
        }
        for tag in tags:
            query_terms.add(tag)

        ranked = self._find_records(query_terms, limit * 4, clean_query, category_filter=cat_filter)
        direct = ranked[:limit]

        direct_ids = {r["i"] for r in direct}
        linked_terms: set[str] = set()
        for r in direct:
            linked_terms.update(r.get("k", "").split())
        bridge_terms = linked_terms - query_terms
        related_candidates = self._find_records(bridge_terms, limit * 3, category_filter=cat_filter) if bridge_terms else []
        related: list[dict[str, object]] = []
        for r in related_candidates:
            if r["i"] in direct_ids:
                continue
            overlap = sorted(bridge_terms & set(r.get("k", "").split()))
            if overlap:
                related.append({
                    "record": r,
                    "overlap": overlap,
                    "score": len(overlap),
                })
        related.sort(key=lambda item: (item["score"], item["record"].get("d", "")), reverse=True)  # type: ignore[arg-type]

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
                    "id": item["record"]["i"],
                    "category": item["record"].get("c", "Knowledge"),
                    "note": item["record"]["n"],
                    "via": item["overlap"],
                }
                for item in related[:3]
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

        # Try FTS5 porter search
        fts_hit_ids: set[str] = set()
        if self._index is not None and terms:
            match_terms = ['"' + term.replace('"', '""') + '"' for term in sorted(terms)]
            match_clause = " OR ".join(match_terms)
            try:
                rows = self._index.execute(
                    "SELECT id, bm25(memories, 2.0, 1.5, 1.0) FROM memories WHERE memories MATCH ? LIMIT ?",
                    (match_clause, limit * 4),
                ).fetchall()
                for row_id, bm25_score in rows:
                    if row_id in by_id:
                        fts_hit_ids.add(row_id)
            except sqlite3.Error:
                pass

        query_cf = original_query.casefold() if original_query else ""
        for index, record in enumerate(self.records):
            if category_filter:
                rec_cat = record.get("c", "").casefold()
                if not (rec_cat == category_filter.casefold() or rec_cat.startswith(category_filter.casefold() + "/")):
                    continue

            keywords = set(record.get("k", "").split())
            note_terms = {word.casefold() for word in _WORDS.findall(record["n"])}
            record_terms = keywords | note_terms

            # Exact keyword overlap, synonym expansion (linguistic understanding)
            # and light stemming (morphological variants) each vote; the strongest
            # signal wins so exact matches are never diluted.
            overlap = len(terms & record_terms)
            expanded_overlap = len(_expand_terms(terms) & record_terms)
            stemmed_overlap = len(
                {_stem(t) for t in _expand_terms(terms)}
                & {_stem(w) for w in record_terms}
            )
            overlap = max(overlap, expanded_overlap, stemmed_overlap)

            if overlap == 0 and record["i"] not in fts_hit_ids and not category_filter:
                continue

            score = float(overlap * 2.0)
            if record["i"] in fts_hit_ids:
                score += 1.5
            if query_cf and record["n"].casefold() in query_cf:
                score += 4.0
            elif query_cf and any(word in query_cf for word in record["n"].casefold().split() if len(word) > 4):
                score += 1.0
            if category_filter:
                score += 3.0
            # Recency boost: notes appended later (higher index) surface first.
            score += index * 0.02

            scored_records.append((score, index, record))

        scored_records.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [item[2] for item in scored_records[:limit]]

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
        """Compress a cluster of related notes into one higher-level memory.

        Finds the largest connected group of notes sharing vocabulary, writes a
        single synthesis note under Harold/Understanding/Consolidated, and
        returns it. The source notes are left intact; this adds a compressed
        layer so distant but related memories recall together.
        """
        if len(self.records) < 2:
            return None

        # Build adjacency via shared non-stopword vocabulary.
        adjacency: dict[str, set[str]] = {r["i"]: set() for r in self.records}
        term_index: dict[str, set[str]] = {}
        for record in self.records:
            terms = {
                word.casefold() for word in _WORDS.findall(record["n"])
                if len(word) > 1 and word.casefold() not in _STOP_WORDS
            }
            terms.update(record.get("k", "").split())
            for term in terms:
                term_index.setdefault(term, set()).add(record["i"])
        for ids in term_index.values():
            ids = list(ids)
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    adjacency[ids[i]].add(ids[j])
                    adjacency[ids[j]].add(ids[i])

        # Largest connected component.
        seen: set[str] = set()
        best: list[str] = []
        for start in adjacency:
            if start in seen:
                continue
            stack = [start]
            component: list[str] = []
            seen.add(start)
            while stack:
                node = stack.pop()
                component.append(node)
                for neighbor in adjacency[node]:
                    if neighbor not in seen:
                        seen.add(neighbor)
                        stack.append(neighbor)
            if len(component) > len(best):
                best = component

        if len(best) < 2:
            return None

        members = [r for r in self.records if r["i"] in best]
        members.sort(key=lambda r: r.get("d", ""))
        joined = " ".join(record["n"] for record in members)
        collapsed = " ".join(joined.split())
        if len(collapsed) > _MAX_NOTE_CHARS - 40:
            clipped = collapsed[: _MAX_NOTE_CHARS - 40]
            if " " in clipped:
                clipped = clipped[: clipped.rfind(" ")]
            collapsed = clipped.rstrip(" ,;:-") + "…"
        note = f"Consolidated understanding from {len(members)} note(s): {collapsed}"

        try:
            return self.add(
                note, category="Harold/Understanding/Consolidated",
            )
        except ValueError:
            return None

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
        temporary = self._edges_path.with_name(self._edges_path.name + ".tmp")
        with temporary.open("w", encoding="utf-8", newline="\n") as output:
            json.dump(self._edges, output, ensure_ascii=False, separators=(",", ":"))
        os.replace(temporary, self._edges_path)

    def link(self, source_id: str, target_id: str, relation: str = "related") -> None:
        """Create a bidirectional mesh edge between two notes."""
        source_id = source_id.strip()
        target_id = target_id.strip()
        if not source_id or not target_id or source_id == target_id:
            return
        self._edges.setdefault(source_id, {})[target_id] = relation
        self._edges.setdefault(target_id, {})[source_id] = relation
        self._save_edges()

    def unlink(self, source_id: str, target_id: str) -> None:
        """Remove a mesh edge between two notes."""
        for side, other in ((source_id, target_id), (target_id, source_id)):
            targets = self._edges.get(side)
            if targets and other in targets:
                del targets[other]
        self._save_edges()

    def neighbors(self, node_id: str) -> list[tuple[str, str]]:
        """Return (neighbor_id, relation) pairs for a mesh node."""
        return [(nid, rel) for nid, rel in self._edges.get(node_id, {}).items()]

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
            return False, f"{stage}: {type(exc).__name__}: {message[:180]}"
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
            if size + len(payload) > self.max_remote_bytes:
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
            client.storbinary(command + self._remote_shard_path(index), io.BytesIO(b"".join(group)))

    def upload(self, record: dict[str, str]) -> None:
        """Append one note to the current capped FTP shard or create the next shard."""
        self.upload_many([record])

    def upload_many(self, records: list[dict[str, str]], timeout: float = 20.0) -> int:
        """Append several notes in one FTP session, preflighting them together."""
        payloads = [self._encode_record(record) for record in records]
        if not payloads:
            return 0
        client = self._connect(timeout=timeout)
        try:
            self._append_payloads(client, payloads)
        finally:
            try:
                client.quit()
            except ftplib.all_errors:
                client.close()
        return len(payloads)

    def sync(self) -> tuple[int, int]:
        """Merge capped FTP shards with the bounded local cache and upload local-only notes."""
        client = self._connect()
        try:
            remote_records, shard_sizes = self._read_remote_shards(client)

            remote_ids = {record["i"] for record in remote_records}
            merged = self._deduplicate(remote_records + self.records)
            remote_added = sum(record["i"] not in {item["i"] for item in self.records} for record in remote_records)
            pending = [record for record in merged if record["i"] not in remote_ids]
            payloads = [self._encode_record(record) for record in pending]
            self._append_payloads(client, payloads, shard_sizes)
            self.records = merged[-self.max_local_records:]
            self._write_local()
            self._rebuild_index()
            return remote_added, len(payloads)
        finally:
            try:
                client.quit()
            except ftplib.all_errors:
                client.close()
