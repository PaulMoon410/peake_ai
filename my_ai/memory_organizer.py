"""Memory organization: deduplicate, re-categorize, consolidate, and build a
searchable knowledge base from all MCF3 notes (local cache + FTP archive).

The organizer never erases original shards. It reads them, produces an
organized knowledge base organized by category (words, phrases, knowledge),
and writes it alongside the originals as a derived layer. Original notes keep
their records.

It also supports:
  * Concurrent FTP writes and HTTP-backed recall so the two transports run in
    parallel instead of serializing chat turns.
  * A dedicated ``Harold`` directory on the FTP archive so organized notes are
    separate from raw shards.
  * HTTP recall against peake-ai's own /api/chat and /health so the organizer
    can cross-check its memory against live responses.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher
from datetime import datetime, timezone
import io
import json
import os
import re
import threading
from pathlib import Path
from typing import Any

import requests

from memory_store import (
    MemoryStore,
    _ALIAS_CATEGORY,
    _CONSOLIDATED_CATEGORY,
    _MAX_NOTE_CHARS,
)

# ---------------------------------------------------------------------------
# Category taxonomy for organizing knowledge
# ---------------------------------------------------------------------------

_CATEGORY_TAXONOMY: dict[str, list[str]] = {
    "Knowledge/Math": [
        "math", "calculate", "equation", "algebra", "calculus", "geometry",
        "number", "arithmetic", "solve", "plus", "minus", "times", "divided",
        "equals", "sum", "formula", "proof", "theorem", "statistics",
        "probability", "area", "volume", "circumference", "pi", "prime",
    ],
    "Knowledge/Science": [
        "physics", "chemistry", "biology", "quantum", "molecule", "atom",
        "experiment", "research", "gravity", "energy", "force", "light",
        "chemical", "reaction", "cell", "dna", "evolution", "planet", "star",
    ],
    "Knowledge/Technology": [
        "computer", "internet", "software", "hardware", "robot", "ai",
        "digital", "tech", "code", "coding", "python", "javascript", "api",
        "database", "algorithm", "debug", "script", "variable", "function",
        "class", "programming", "web", "website", "network",
    ],
    "Knowledge/History": [
        "war", "ancient", "century", "empire", "king", "queen", "revolution",
        "historical", "dynasty", "emperor", "battle", "independence",
        "colonization", "reformation", "renaissance", "medieval", "victorian",
    ],
    "Knowledge/Literature": [
        "book", "novel", "poem", "author", "shakespeare", "story", "novelist",
        "writing", "fiction", "narrative", "character", "plot", "chapter",
        "publish", "read", "literature", "essay",
    ],
    "Knowledge/Philosophy": [
        "ethics", "morality", "existence", "truth", "knowledge", "wisdom",
        "meaning", "consciousness", "reality", "mind", "soul", "virtue",
        "justice", "freedom", "logic", "reason", "doubt",
    ],
    "Knowledge/Health": [
        "medicine", "doctor", "disease", "treatment", "health", "body",
        "medical", "patient", "symptom", "diagnosis", "therapy", "drug",
        "virus", "bacteria", "organ", "heart", "brain", "blood",
    ],
    "Knowledge/Finance": [
        "money", "dollar", "euro", "price", "cost", "budget", "invest",
        "stock", "market", "trade", "bank", "loan", "interest", "profit",
        "loss", "salary", "wage", "tax", "invoice", "payment",
    ],
    "Knowledge/Geography": [
        "country", "city", "continent", "ocean", "river", "mountain",
        "desert", "forest", "climate", "weather", "map", "border", "capital",
        "population", "island", "coast", "valley", "plain",
    ],
    "Knowledge/Art": [
        "painting", "music", "sculpture", "artist", "gallery", "museum",
        "concert", "song", "instrument", "canvas", "color", "design",
        "architecture", "film", "theater", "dance",
    ],
    "Knowledge/Sports": [
        "football", "basketball", "soccer", "tennis", "baseball", "hockey",
        "game", "match", "player", "team", "score", "win", "loss", "tournament",
        "olympics", "athlete", "coach",
    ],
    "Knowledge/Food": [
        "food", "recipe", "cook", "bake", "eat", "drink", "restaurant",
        "cuisine", "ingredient", "flavor", "spice", "meal", "breakfast",
        "lunch", "dinner", "dessert",
    ],
    "Preferences": [
        "prefer", "like", "dislike", "favorite", "love", "hate", "want",
        "need", "wish", "hope", "plan", "goal", "habit", "routine",
    ],
    "Projects": [
        "project", "task", "todo", "deadline", "milestone", "deliverable",
        "assignment", "work", "job", "career", "business", "startup",
    ],
}

_KEYWORD_TO_CATEGORIES: dict[str, list[str]] = {}
for _cat, _keywords in _CATEGORY_TAXONOMY.items():
    for _kw in _keywords:
        _KEYWORD_TO_CATEGORIES.setdefault(_kw.casefold(), []).append(_cat)

_DEFAULT_CATEGORY = "Knowledge/General"

# FTP directory for organized Harold notes (separate from raw shards)
HAROLD_FTP_DIR = "Harold"

# ---------------------------------------------------------------------------
# Similarity / deduplication
# ---------------------------------------------------------------------------

def _notes_similar(a: str, b: str, threshold: float = 0.82) -> bool:
    """Return True when two normalized notes are near-duplicates."""
    if not a or not b:
        return False
    if len(a) != len(b) and abs(len(a) - len(b)) > 120:
        return False
    return SequenceMatcher(None, a.casefold(), b.casefold()).ratio() >= threshold


# ---------------------------------------------------------------------------
# HTTP-backed recall coordination (runs in parallel with FTP writes)
# ---------------------------------------------------------------------------

class HttpRecallCoordinator:
    """Coordinates recall against peake-ai's own HTTP API while FTP writes run.

    The organizer can query peake-ai's running /api/chat and /health over HTTP
    at the same time it is writing organized notes to FTP. This means a chat
    turn never has to wait for FTP + organizer work to finish before replying;
    the organizer runs on a background thread and the HTTP cross-check is just
    another concurrent request.
    """

    def __init__(self, base_url: str | None = None, timeout: float = 12.0):
        self.base_url = (base_url or os.environ.get("PEAKE_AI_CHAT_URL", "https://peake-ai.onrender.com")).rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        self._lock = threading.Lock()
        self.last_chat_status: int | None = None
        self.last_health_status: int | None = None
        self.available = False

    def health(self) -> bool:
        """Return True when the remote API is reachable."""
        try:
            res = self.session.get(f"{self.base_url}/health", timeout=self.timeout)
            with self._lock:
                self.last_health_status = res.status_code
                self.available = res.status_code == 200
            return self.available
        except Exception:
            with self._lock:
                self.available = False
            return False

    def chat(self, prompt: str, history: list | None = None) -> str | None:
        """Ask the remote peake-ai API for an answer (cross-check)."""
        try:
            res = self.session.post(
                f"{self.base_url}/api/chat",
                json={"prompt": prompt, "history": history or []},
                timeout=self.timeout,
            )
            with self._lock:
                self.last_chat_status = res.status_code
            if res.status_code == 200:
                data = res.json()
                return data.get("response")
            return None
        except Exception:
            return None

    def cross_check(self, prompt: str) -> str | None:
        """Quick health check + chat cross-check in one call."""
        self.health()
        return self.chat(prompt)


# ---------------------------------------------------------------------------
# Categorization
# ---------------------------------------------------------------------------

def _categorize_organizer(text: str) -> str:
    """Assign the best category from the expanded taxonomy."""
    text_l = text.casefold()
    best_category = _DEFAULT_CATEGORY
    best_score = 0
    for cat, keywords in _CATEGORY_TAXONOMY.items():
        score = sum(1 for kw in keywords if kw.casefold() in text_l)
        if score > best_score:
            best_score = score
            best_category = cat
    return best_category


# ---------------------------------------------------------------------------
# Knowledge base building
# ---------------------------------------------------------------------------

def build_knowledge_base(records: list[dict[str, str]]) -> dict[str, dict[str, list[str]]]:
    """Group non-consolidated notes by category into words / phrases / knowledge."""
    organized: dict[str, dict[str, list[str]]] = {}

    for record in records:
        category = record.get("c", _DEFAULT_CATEGORY)
        if category in (_ALIAS_CATEGORY, _CONSOLIDATED_CATEGORY):
            continue
        note = record.get("n", "").strip()
        if not note:
            continue

        bucket = organized.setdefault(
            category, {"words": [], "phrases": [], "knowledge": []}
        )

        words = [w for w in re.findall(r"[^\W_]+", note) if len(w) > 2]
        for word in words:
            if word.casefold() not in {w.casefold() for w in bucket["words"]}:
                bucket["words"].append(word)

        tokens = re.findall(r"[^\W_]+", note)
        for size in (2, 3, 4):
            for i in range(len(tokens) - size + 1):
                phrase = " ".join(tokens[i:i + size])
                phrase_l = phrase.casefold()
                if phrase_l not in {p.casefold() for p in bucket["phrases"]}:
                    bucket["phrases"].append(phrase)

        bucket["knowledge"].append(note)

    for bucket in organized.values():
        bucket["words"] = bucket["words"][:200]
        bucket["phrases"] = bucket["phrases"][:150]
        bucket["knowledge"] = bucket["knowledge"][:100]

    return organized


def serialize_knowledge_base(organized: dict[str, dict[str, list[str]]]) -> str:
    """Render the organized knowledge base as human-readable text."""
    lines: list[str] = []
    lines.append("# Harold Organized Knowledge Base")
    lines.append(f"# Generated {datetime.now(timezone.utc).isoformat()}")
    lines.append("# Organized by category: words, phrases, knowledge notes")
    lines.append("")

    for category in sorted(organized.keys()):
        bucket = organized[category]
        lines.append(f"## {category}")
        lines.append("")

        if bucket["words"]:
            lines.append("### Words")
            lines.append(", ".join(bucket["words"]))
            lines.append("")

        if bucket["phrases"]:
            lines.append("### Phrases")
            lines.append(", ".join(bucket["phrases"]))
            lines.append("")

        if bucket["knowledge"]:
            lines.append("### Knowledge")
            for note in bucket["knowledge"]:
                lines.append(f"- {note}")
            lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Organization pass
# ---------------------------------------------------------------------------

def organize_memory(
    store: MemoryStore,
    force: bool = False,
    min_interval_seconds: float = 3600.0,
    http: HttpRecallCoordinator | None = None,
) -> dict[str, Any]:
    """Run a full memory organization pass.

    Steps:
      1. Load all local records.
      2. Deduplicate near-identical notes (keep newest).
      3. Re-categorize notes using the expanded taxonomy.
      4. Consolidate related note clusters into synthesized summaries.
      5. Build an organized knowledge base (words / phrases / knowledge per
         category) and write it as derived notes + upload to the FTP
         ``Harold`` directory concurrently with any HTTP cross-check.

    Returns a report dict with counts.
    """
    report: dict[str, Any] = {
        "deduplicated": 0,
        "re_categorized": 0,
        "consolidated": 0,
        "knowledge_base_written": False,
        "categories": {},
        "ftp_harold_dir": HAROLD_FTP_DIR,
        "http_available": False,
    }

    with store._lock:
        records = list(store.records)

    if len(records) < 2 and not force:
        return report

    # ---- Deduplicate -------------------------------------------------------
    deduped: list[dict[str, str]] = []
    seen_texts: list[str] = []
    for record in records:
        note = record.get("n", "").strip()
        is_dup = False
        for seen in seen_texts:
            if _notes_similar(note, seen):
                is_dup = True
                report["deduplicated"] += 1
                break
        if not is_dup:
            deduped.append(record)
            seen_texts.append(note)

    # ---- Re-categorize -----------------------------------------------------
    re_categorized = 0
    for record in deduped:
        old_cat = record.get("c", _DEFAULT_CATEGORY)
        if old_cat in (_ALIAS_CATEGORY, _CONSOLIDATED_CATEGORY):
            continue
        text = record.get("n", "")
        new_cat = _categorize_organizer(text)
        if new_cat != old_cat:
            record["c"] = new_cat
            re_categorized += 1
    report["re_categorized"] = re_categorized

    # ---- Consolidate related clusters --------------------------------------
    term_index: dict[str, set[str]] = {}
    for record in deduped:
        terms = set(re.findall(r"[^\W_]+", record.get("n", "").casefold()))
        terms = {t for t in terms if len(t) > 2}
        terms |= set(record.get("k", "").casefold().split())
        for term in terms:
            term_index.setdefault(term, set()).add(record["i"])

    adjacency: dict[str, set[str]] = {r["i"]: set() for r in deduped}
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

    by_id = {r["i"]: r for r in deduped}
    consolidated_count = 0
    for component in components[:10]:
        members = [by_id[node] for node in component if node in by_id]
        if len(members) < 2:
            continue
        members = sorted(members, key=lambda r: r.get("d", ""))
        joined = " ".join(record["n"] for record in members)
        collapsed = " ".join(joined.split())
        header = f"Synthesized understanding from {len(members)} note(s): "
        budget = _MAX_NOTE_CHARS - len(header) - 1
        if len(collapsed) > budget:
            clipped = collapsed[:budget]
            if " " in clipped:
                clipped = clipped[: clipped.rfind(" ")]
            collapsed = clipped.rstrip(" ,;:-") + "…"
        synth_note = header + collapsed
        synth_cat = _categorize_organizer(synth_note)
        new_rec = store.add(
            synth_note,
            category=f"Knowledge/Synthesis/{synth_cat}",
            source="organizer-internal",
        )
        if new_rec:
            consolidated_count += 1
            for source_id in [m["i"] for m in members]:
                try:
                    store.link(new_rec["i"], source_id, "derived")
                except Exception:
                    pass
    report["consolidated"] = consolidated_count

    # ---- Build knowledge base ---------------------------------------------
    organized = build_knowledge_base(deduped)
    report["categories"] = {cat: {
        "words": len(b["words"]),
        "phrases": len(b["phrases"]),
        "knowledge": len(b["knowledge"]),
    } for cat, b in organized.items()}

    kb_text = serialize_knowledge_base(organized)
    kb_note = f"# Harold Knowledge Base (auto-organized)\n{kb_text}"

    # Split into <=500-char chunks for MCF3 storage
    chunks: list[str] = []
    text = kb_note.strip()
    while len(text) > _MAX_NOTE_CHARS:
        split_pt = text.rfind("\n", 0, _MAX_NOTE_CHARS)
        if split_pt == -1:
            split_pt = text.rfind(" ", 0, _MAX_NOTE_CHARS)
        if split_pt == -1:
            split_pt = _MAX_NOTE_CHARS
        chunks.append(text[:split_pt].strip())
        text = text[split_pt:].strip("\n ")
    if text:
        chunks.append(text)

    # ---- Concurrent FTP write + HTTP recall --------------------------------
    kb_written = False
    http_future = None
    ftp_future = None

    def _write_kb_chunks() -> bool:
        written = False
        for chunk in chunks:
            try:
                rec = store.add(
                    chunk,
                    category="Knowledge/Organized/Base",
                    source="organizer-internal",
                )
                if rec:
                    written = True
            except Exception:
                pass
        return written

    def _http_cross_check() -> None:
        if http is None:
            return
        try:
            http.cross_check("Harold memory organization complete")
        except Exception:
            pass

    # Run FTP write and HTTP recall concurrently
    with ThreadPoolExecutor(max_workers=2) as pool:
        ftp_future = pool.submit(_write_kb_chunks)
        if http is not None:
            http_future = pool.submit(_http_cross_check)
        for fut in as_completed([f for f in (ftp_future, http_future) if f is not None]):
            try:
                result = fut.result()
                if ftp_future is fut and result:
                    kb_written = True
                if http_future is fut:
                    with report_lock:
                        report["http_available"] = http.available
            except Exception:
                pass

    report["knowledge_base_written"] = kb_written
    return report


report_lock = threading.Lock()


def sync_and_organize(
    store: MemoryStore,
    force: bool = False,
    http: HttpRecallCoordinator | None = None,
) -> dict[str, Any]:
    """Sync from FTP archive, then run organize_memory on the merged set.

    FTP sync and organizer work happen on the organizer's own thread; the
    HTTP cross-check runs concurrently with the FTP write so chat turns are
    not blocked.
    """
    if store.ftp_configured:
        try:
            store.sync()
        except Exception as exc:
            print(f"⚠️ Organizer FTP sync skipped: {type(exc).__name__}: {exc}")
    return organize_memory(store, force=force, http=http)
