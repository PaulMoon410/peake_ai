"""A small, explicit recall benchmark for the MCF3 memory store.

The point of this module is to make recall quality *measurable* instead of
argued about. It builds a representative memory collection with known ground
truth, runs a fixed query set, and reports four numbers that map directly to
the risks in this codebase:

``precision@k``       of the notes returned, how many were actually relevant
``recall@k``          of the relevant notes, how many were returned
``false_association`` related notes surfaced that share nothing with the query
``storage_savings``   how much of the collection the archive index covers

The thresholds pinned in the tests are deliberately modest: they are a floor
to catch regressions (a ranking change that lets one common word dominate, or
an alias rule that starts wiring unrelated ideas together), not a claim of a
perfect retriever.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from memory_store import MemoryStore  # noqa: E402

# (id, category, note, topic). ``topic`` is the ground-truth relevance label.
CORPUS: list[tuple[str, str, str, str]] = [
    ("py1", "Knowledge", "Python scripting automates repetitive file cleanup on the server", "python"),
    ("py2", "Projects", "The python coding project rewrites report templates every night", "python"),
    ("py3", "Tools", "Use the python debugger to trace recursion depth in the parser", "python"),
    ("db1", "Knowledge", "Postgres indexing strategy for slow analytical queries", "database"),
    ("db2", "Projects", "Database migration rollback plan for the billing service", "database"),
    ("mt1", "Knowledge", "Market volatility rises when liquidity thins out", "markets"),
    ("mt2", "Finance", "Trading risk is capped by position sizing rules", "markets"),
    ("sl1", "Knowledge", "Sleep quality improves with a consistent bedtime", "sleep"),
    ("sl2", "Personal", "My sleep schedule drifts on work travel days", "sleep"),
    ("wd1", "Personal", "We bought a new dining table for the kitchen", "home"),
    ("wd2", "Personal", "The kitchen renovation quote arrived on friday", "home"),
    ("hp1", "Knowledge", "A nightly backup keeps the harold archive recoverable", "backup"),
    ("hp2", "Tools", "FTP upload retries should resume rather than restart", "backup"),
    ("tr1", "Knowledge", "Trauma recovery often needs steady, patient support", "health"),
    ("tr2", "Personal", "Anxiety spikes before public speaking", "health"),
    ("misc1", "Personal", "My favourite tea is jasmine green", "misc"),
    ("misc2", "Work", "The office moved to the fourth floor", "misc"),
]

# (query, {topics that must be represented in the results}, max_rank_of_best)
QUERIES: list[tuple[str, set[str], int]] = [
    ("python scripting automation", {"python"}, 3),
    ("database migration", {"database"}, 2),
    ("trading market risk", {"markets"}, 2),
    ("bedtime sleep", {"sleep"}, 2),
    ("kitchen renovation", {"home"}, 2),
    ("ftp upload retry", {"backup"}, 2),
    ("anxiety support", {"health"}, 3),
]


@dataclass
class QueryResult:
    query: str
    returned: list[str] = field(default_factory=list)
    relevant_returned: int = 0
    relevant_total: int = 0
    false_associations: list[str] = field(default_factory=list)

    @property
    def precision(self) -> float:
        return self.returned_relevant_ratio()

    def returned_relevant_ratio(self) -> float:
        if not self.returned:
            return 0.0
        return len([item for item in self.returned if item in self.relevant_ids]) / len(self.returned)

    relevant_ids: set[str] = field(default_factory=set)


def build_store(folder: str) -> tuple[MemoryStore, dict[str, str]]:
    """Create the benchmark store; return it plus note-text -> record id map."""
    store = MemoryStore(Path(folder) / "memory.jsonl")
    ids: dict[str, str] = {}
    for note_id, category, note, _topic in CORPUS:
        record = store.add(note, category=category)
        assert record is not None, note
        ids[note_id] = record["i"]
    return store, ids


def evaluate(store: MemoryStore, ids: dict[str, str], k: int = 3) -> dict[str, object]:
    """Run the fixed query set and summarise precision, recall, and associations."""
    # Map record id -> benchmark id. Notes are matched by id, never by text:
    # the bounded local cache can trim older notes, which would make a text
    # lookup silently miss them and understate recall.
    ids_key = {record_id: note_id for note_id, record_id in ids.items()}
    results: list[QueryResult] = []

    for query, topics, max_rank in QUERIES:
        details = store.recall_details(query, limit=k)
        direct_keys = [ids_key.get(item["id"]) for item in details["direct"]]
        relevant = {note_id for note_id, _c, _note, topic in CORPUS if topic in topics}
        found = {key for key in direct_keys if key in relevant}

        result = QueryResult(query=query, relevant_ids=relevant)
        result.returned = [key for key in direct_keys if key]
        result.relevant_returned = len(found)
        result.relevant_total = len(relevant)

        # A related item is a false association when it belongs to none of the
        # topics in play and shares no content word with the query. Topics are
        # resolved by note id, because the local cache may already have trimmed
        # an older note and text lookup would then miss it.
        topic_of = {note_id: topic for note_id, _c, _note, topic in CORPUS}
        query_words = {word for word in query.lower().split() if len(word) > 3}
        for item in details["related"]:
            key = ids_key.get(item["id"])
            if topic_of.get(key) in topics:
                continue
            words = set(item["note"].lower().split())
            if not (query_words & words):
                result.false_associations.append(item["note"])
        results.append(result)

        best_rank = next(
            (rank for rank, key in enumerate(result.returned, start=1) if key in relevant),
            None,
        )
        if best_rank is None or best_rank > max_rank:
            return {
                "queries": len(results),
                "error": f"query {query!r}: expected a relevant note by rank {max_rank}, got {result.returned}",
            }

    precision = sum(r.precision for r in results) / len(results)
    recall = sum(r.relevant_returned / max(1, r.relevant_total) for r in results) / len(results)
    false_associations = sum(len(r.false_associations) for r in results)
    return {
        "queries": len(results),
        f"precision@{k}": round(precision, 3),
        f"recall@{k}": round(recall, 3),
        "false_associations": false_associations,
        "results": results,
    }


def measure_storage(store: MemoryStore, folder: str) -> dict[str, int]:
    """Compare raw note shard bytes with the compact archive index."""
    index = store._build_index_map(store.records)
    index_bytes = len(store._encode_index(index))
    raw_bytes = sum(
        len((__import__("json").dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"))
        for r in store.records
    )
    return {
        "notes": len(store.records),
        "raw_bytes": raw_bytes,
        "index_bytes": index_bytes,
        "saved_bytes": raw_bytes - index_bytes,
    }
