"""Turn a page of prose into a few short observations about human experience.

Two paths, deliberately: the local model is asked to rephrase what the page says,
and if it is unavailable or produces nothing usable, an extractive fallback lifts
the most experience-bearing sentences verbatim. Either way the note stays short,
keeps the topic in its own words, and carries no claim the source did not make.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from harold.lexicon import fit_note, is_experiential, note_key
from harold.readability import PageText, salient_sentences
from harold.topics import CurriculumTopic


NOTE_CHAR_LIMIT = 460          # below the memory store's own 500-char ceiling
PROMPT_EXTRACT_CHARS = 1100
MIN_NOTE_CHARS = 50
MAX_NOTE_CHARS = 400
ModelFn = Callable[[str], str]

CURATOR_PROMPT = """You write short observations about what human life is like, using only the page below.

Rules:
- Use only facts stated in the page. Never add outside knowledge or opinion.
- Write at most {count} observations. One per line, each beginning with "- ".
- Each observation is a single sentence under {limit} characters.
- Each must describe how people feel, sense, think, behave, believe or live.
- No headings, numbering, links, or quotations longer than a few words.

Topic: {topic}
Page title: {title}
Page extract:
{extract}

Observations:
"""


@dataclass(frozen=True, slots=True)
class MemoryCandidate:
    """One observation ready to be stored, with the source it came from."""

    note: str
    topic: str
    source_url: str
    generated_by: str

    def as_memory_text(self) -> str:
        """Note text carrying the semantic tags the store understands."""
        return self.note


@dataclass
class Curator:
    """Distil pages into note-sized observations."""

    model: ModelFn | None = None
    use_model: bool = True
    max_notes_per_page: int = 3
    _seen: set[str] = field(default_factory=set, init=False)

    def distill(
        self, topic: CurriculumTopic, page: PageText, source_url: str,
    ) -> list[MemoryCandidate]:
        """Observations from one page, model-written where possible."""
        sentences = salient_sentences(
            page.text, topic.keywords, limit=self.max_notes_per_page * 3
        )
        if not sentences:
            return []
        candidates = self._from_model(topic, page, source_url, sentences)
        if not candidates:
            candidates = self._from_text(topic, source_url, sentences)
        return self._accept(candidates)

    # -- generation paths ---------------------------------------------------
    def _from_model(
        self,
        topic: CurriculumTopic,
        page: PageText,
        source_url: str,
        sentences: list[str],
    ) -> list[MemoryCandidate]:
        if not self.use_model or self.model is None:
            return []
        extract = " ".join(sentences)[:PROMPT_EXTRACT_CHARS]
        prompt = CURATOR_PROMPT.format(
            count=self.max_notes_per_page, limit=MAX_NOTE_CHARS,
            topic=topic.name, title=page.title or "(untitled)", extract=extract,
        )
        try:
            raw = self.model(prompt)
        except Exception:
            return []
        produced: list[MemoryCandidate] = []
        for line in raw.splitlines():
            stripped = line.strip()
            if not stripped.startswith(("- ", "* ", "\u2022 ")):
                continue
            body = stripped.lstrip("-*\u2022 ").strip()
            if is_experiential(body, topic.keywords):
                produced.append(MemoryCandidate(
                    note=self._contextualise(topic, body), topic=topic.name,
                    source_url=source_url, generated_by="model",
                ))
        return produced

    def _from_text(
        self, topic: CurriculumTopic, source_url: str, sentences: list[str],
    ) -> list[MemoryCandidate]:
        """Extractive fallback: keep the source's own wording."""
        return [
            MemoryCandidate(
                note=self._contextualise(topic, sentence), topic=topic.name,
                source_url=source_url, generated_by="extract",
            )
            for sentence in sentences
        ]

    # -- validation ---------------------------------------------------------
    def _contextualise(self, topic: CurriculumTopic, text: str) -> str:
        """Make a note self-describing so it recalls well on its own."""
        body = " ".join(text.split())
        lowered = body.casefold()
        if not any(keyword.casefold() in lowered for keyword in topic.keywords):
            body = f"{topic.name}: {body}"
        return fit_note(body, NOTE_CHAR_LIMIT)

    def _accept(self, candidates: list[MemoryCandidate]) -> list[MemoryCandidate]:
        accepted: list[MemoryCandidate] = []
        for candidate in candidates:
            key = note_key(candidate.note)
            if len(candidate.note) < MIN_NOTE_CHARS or key in self._seen:
                continue
            if not is_experiential(candidate.note, ()):
                continue
            self._seen.add(key)
            accepted.append(candidate)
            if len(accepted) >= self.max_notes_per_page:
                break
        return accepted

    def forget_notes(self) -> None:
        """Clear the in-session duplicate filter (a new session starts fresh)."""
        self._seen.clear()
