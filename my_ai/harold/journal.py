"""Harold's private log of what he read and what he learned from it.

The journal is a local, append-only JSONL file. It is deliberately separate from
the shared memory store: memory holds the observations worth keeping and syncing,
while the journal holds the operational record (which pages were read, which were
refused and why) that keeps the work auditable.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path

from .lexicon import fit_note


MAX_TAIL_BYTES = 512 * 1024
DETAIL_CHAR_LIMIT = 300
KIND_SESSION = "session"
KIND_TOPIC = "topic"
KIND_PAGE = "page"
KIND_REFLECTION = "reflection"


def timestamp() -> str:
    """UTC timestamp for a journal entry."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True, slots=True)
class JournalEntry:
    """One line of the journal."""

    at: str
    kind: str
    topic: str = ""
    url: str = ""
    detail: str = ""
    notes: int = 0
    uploaded: int = 0

    @classmethod
    def create(
        cls, kind: str, topic: str = "", url: str = "", detail: str = "",
        notes: int = 0, uploaded: int = 0,
    ) -> "JournalEntry":
        return cls(
            at=timestamp(), kind=kind, topic=topic, url=url,
            detail=fit_note(detail, DETAIL_CHAR_LIMIT) if detail else "",
            notes=notes, uploaded=uploaded,
        )

    @classmethod
    def from_dict(cls, value: object) -> "JournalEntry | None":
        if not isinstance(value, dict):
            return None
        try:
            return cls(
                at=str(value.get("at", "")), kind=str(value.get("kind", "")),
                topic=str(value.get("topic", "")), url=str(value.get("url", "")),
                detail=str(value.get("detail", "")),
                notes=int(value.get("notes", 0) or 0),
                uploaded=int(value.get("uploaded", 0) or 0),
            )
        except (TypeError, ValueError):
            return None

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, separators=(",", ":"))


@dataclass
class Journal:
    """Append-only journal on disk."""

    path: Path

    def append(self, entry: JournalEntry) -> None:
        """Add one entry, creating the file and directory when needed."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(entry.to_json() + "\n")
        except OSError:
            # A journal that cannot be written must never stop a session.
            pass

    def entries(self, limit: int = 40) -> list[JournalEntry]:
        """The most recent entries, newest last."""
        if limit <= 0:
            return []
        parsed: list[JournalEntry] = []
        for line in self._tail_lines():
            try:
                entry = JournalEntry.from_dict(json.loads(line))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            if entry is not None and entry.kind:
                parsed.append(entry)
        return parsed[-limit:]

    def _tail_lines(self) -> list[str]:
        if not self.path.is_file():
            return []
        try:
            size = self.path.stat().st_size
            with self.path.open("rb") as handle:
                if size > MAX_TAIL_BYTES:
                    handle.seek(size - MAX_TAIL_BYTES)
                    handle.readline()  # drop the partial first line
                raw = handle.read()
        except OSError:
            return []
        return raw.decode("utf-8", errors="replace").splitlines()

    def stats(self) -> dict[str, int]:
        """Totals across the whole (bounded) journal."""
        entries = self.entries(limit=100000)
        return {
            "entries": len(entries),
            "pages_read": sum(1 for e in entries if e.kind == KIND_PAGE),
            "topics_studied": len({e.topic for e in entries if e.kind == KIND_TOPIC and e.topic}),
            "notes_learned": sum(e.notes for e in entries if e.kind == KIND_PAGE),
            "notes_uploaded": sum(e.uploaded for e in entries if e.kind == KIND_PAGE),
            "reflections": sum(1 for e in entries if e.kind == KIND_REFLECTION),
        }

    def render(self, limit: int = 20) -> str:
        """Human-readable view of recent entries."""
        entries = self.entries(limit=limit)
        if not entries:
            return "Harold's journal is empty. Run /harold learn to give him something to read."
        lines: list[str] = []
        for entry in entries:
            where = entry.topic or entry.url or "-"
            counts = ""
            if entry.notes or entry.uploaded:
                counts = f" ({entry.notes} new, {entry.uploaded} synced)"
            detail = f" — {entry.detail}" if entry.detail else ""
            lines.append(f"{entry.at}  {entry.kind:<10} {where}{counts}{detail}")
        return "\n".join(lines)
