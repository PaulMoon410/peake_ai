"""Harold's attempt to say what he has understood so far.

A reflection is not evidence. It is a summary built only from observations that
already sit in memory, and it names the note ids it drew on so anything it says
can be checked against the source it came from. When no local model is available
the reflection degrades to a plain, clearly-labelled digest of those notes.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from harold.lexicon import fit_note


SUMMARY_CHAR_LIMIT = 480
REFLECTION_CHAR_LIMIT = 1200
MAX_NOTES_USED = 12
NOTE_EXCERPT_CHARS = 240
ModelFn = Callable[[str], str]

REFLECTION_PROMPT = """You are Harold. Below are notes you gathered from public pages about {topic}.

Write 3 to 6 sentences describing what people report about this experience.

Rules:
- Use only the notes below. Add nothing from outside them.
- Write plainly in the third person about people, not about yourself.
- Do not give advice, predictions, diagnoses or statistics.
- If the notes disagree or are thin, say so in one clause.
- After the summary, list the note ids you used as: Sources: id1, id2

Notes:
{notes}

Summary:
"""

DIGEST_HEADER = "Harold's digest (no model was available, so these are the notes themselves)"


@dataclass(frozen=True, slots=True)
class NoteView:
    """The part of a stored note a reflection may use."""

    id: str
    category: str
    note: str
    source: str = ""

    @classmethod
    def from_record(cls, record: dict[str, str]) -> "NoteView":
        return cls(
            id=str(record.get("i", "")), category=str(record.get("c", "")),
            note=str(record.get("n", "")), source=str(record.get("s", "")),
        )

    def cited(self) -> str:
        """Excerpt plus its id, for a digest."""
        return f"[{self.id}] {fit_note(self.note, NOTE_EXCERPT_CHARS)}"


@dataclass(frozen=True, slots=True)
class Reflection:
    """A synthesis and the notes it was allowed to use."""

    topic: str
    category: str
    body: str
    note_ids: tuple[str, ...]
    generated_by: str

    def as_memory_note(self) -> str:
        """Memory text: labelled as a synthesis, sized for the store."""
        prefix = f"Harold's synthesis of {self.topic}"
        body = fit_note(self.body, SUMMARY_CHAR_LIMIT - len(prefix) - 3)
        return f"{prefix}: {body}"

    def render(self) -> str:
        """Terminal view including provenance."""
        cited = ", ".join(self.note_ids) or "none"
        origin = "model" if self.generated_by == "model" else "extractive digest"
        return f"{self.body}\n\n  basis: {len(self.note_ids)} notes ({cited})\n  written by: {origin}"


def _notes_block(notes: list[NoteView]) -> str:
    lines = []
    for note in notes[:MAX_NOTES_USED]:
        lines.append(f"- [{note.id}] ({note.category}) {fit_note(note.note, NOTE_EXCERPT_CHARS)}")
    return "\n".join(lines)


def build_reflection(
    topic: str,
    category: str,
    notes: list[NoteView],
    model: ModelFn | None = None,
    use_model: bool = True,
) -> Reflection | None:
    """Summarise notes into a reflection, or None when there is nothing to say."""
    usable = [note for note in notes if note.note.strip()][:MAX_NOTES_USED]
    if not usable:
        return None
    if use_model and model is not None:
        produced = _ask_model(topic, usable, model)
        if produced:
            body, cited_ids = produced
            return Reflection(topic=topic, category=category, body=body,
                              note_ids=cited_ids, generated_by="model")
    return Reflection(
        topic=topic, category=category, body=_digest(usable, topic),
        note_ids=tuple(note.id for note in usable), generated_by="extract",
    )


def _ask_model(
    topic: str, notes: list[NoteView], model: ModelFn,
) -> tuple[str, tuple[str, ...]] | None:
    prompt = REFLECTION_PROMPT.format(topic=topic, notes=_notes_block(notes))
    try:
        raw = model(prompt).strip()
    except Exception:
        return None
    if len(raw) < 80:
        return None
    body, _, cited = raw.partition("Sources:")
    summary = " ".join(body.split())
    if len(summary) < 80:
        return None
    known = {note.id: note.id for note in notes}
    cited_ids = tuple(
        known[token.strip().strip(".,;[]")]
        for token in cited.replace("\n", " ").split(",")
        if token.strip().strip(".,;[]") in known
    )
    if not cited_ids:
        cited_ids = tuple(note.id for note in notes[:3])
    return fit_note(summary, REFLECTION_CHAR_LIMIT), cited_ids


def _digest(notes: list[NoteView], topic: str) -> str:
    lines = [f"{DIGEST_HEADER}: {topic}."]
    lines.extend(note.cited() for note in notes[:6])
    return "\n".join(lines)
