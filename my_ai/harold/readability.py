"""Turn an HTML page into clean prose and individual sentences.

Harold reads text, not markup. This module drops scripts, styling, navigation and
form furniture, keeps paragraph-like content, and splits the result into whole
sentences so the curator can pick out observations about human experience.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from html.parser import HTMLParser

from harold.lexicon import WORD_RE, experience_score, is_experiential, note_key


SKIP_TAGS = frozenset({
    "script", "style", "noscript", "template", "svg", "iframe", "form", "nav",
    "header", "footer", "aside", "button", "select", "option", "canvas", "object",
    "embed", "map", "picture", "video", "audio", "meta-refresh",
})
BLOCK_TAGS = frozenset({
    "p", "div", "li", "tr", "td", "th", "section", "article", "blockquote", "br",
    "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "dl", "dt", "dd", "pre",
    "table", "hr", "main", "figure", "figcaption", "caption",
})
HEADING_TAGS = frozenset({"h1", "h2", "h3"})
SENTENCE_END_RE = re.compile(r"(?<=[.!?])[\"'\u2019\u201d)\]]?\s+")
ABBREVIATIONS = (
    "mr.", "mrs.", "ms.", "dr.", "prof.", "st.", "vs.", "etc.", "e.g.", "i.e.",
    "cf.", "no.", "approx.", "ca.", "fig.", "al.", "jr.", "sr.",
)
MIN_SENTENCE_CHARS = 45
MAX_SENTENCE_CHARS = 460


@dataclass(frozen=True, slots=True)
class PageText:
    """Extracted page content."""

    url: str
    title: str
    description: str
    text: str

    @property
    def is_empty(self) -> bool:
        return len(self.text) < 200


class _TextExtractor(HTMLParser):
    """Collect visible text, skipping the furniture that surrounds it."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.pieces: list[str] = []
        self.title = ""
        self.description = ""
        self._skip_depth = 0
        self._in_title = False
        self._heading_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.casefold()
        if lowered in SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if lowered == "meta":
            attributes = {key.casefold(): (value or "") for key, value in attrs}
            if attributes.get("name", "").casefold() == "description" and not self.description:
                self.description = attributes.get("content", "").strip()
            return
        if lowered == "title":
            self._in_title = True
            return
        if lowered in HEADING_TAGS:
            self._heading_depth += 1
        if lowered in BLOCK_TAGS:
            self.pieces.append("\n")

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.casefold()
        if lowered in SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return
        if lowered == "title":
            self._in_title = False
            return
        if lowered in HEADING_TAGS and self._heading_depth:
            self._heading_depth -= 1
        if lowered in BLOCK_TAGS:
            self.pieces.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_title:
            if not self.title:
                self.title = data.strip()
            return
        if data.strip():
            self.pieces.append(data)


def _collapse(pieces: list[str], max_chars: int) -> str:
    raw = "".join(pieces)
    raw = raw.replace("\u00a0", " ").replace("\u200b", "")
    raw = re.sub(r"[ \t\r\f\v]+", " ", raw)
    raw = re.sub(r" *\n *", "\n", raw)
    raw = re.sub(r"\n{2,}", "\n\n", raw).strip()
    if len(raw) <= max_chars:
        return raw
    window = raw[:max_chars]
    boundary = max(window.rfind("\n"), window.rfind(". "))
    if boundary < max_chars // 2:
        boundary = window.rfind(" ")
    return window[:boundary].strip() if boundary > 0 else window.strip()


def html_to_text(html: str, url: str = "", max_chars: int = 20000) -> PageText:
    """Extract title, description and prose from an HTML document."""
    parser = _TextExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        # Malformed markup must not lose the text already collected.
        pass
    return PageText(
        url=url,
        title=parser.title.strip() or _first_heading(parser.pieces),
        description=parser.description.strip(),
        text=_collapse(parser.pieces, max_chars),
    )


def _first_heading(pieces: list[str]) -> str:
    """Fallback title: the first reasonably long line of the page."""
    for piece in pieces:
        candidate = piece.strip()
        if 12 <= len(candidate) <= 120 and not candidate.endswith((".", ",", ";")):
            return candidate
    return ""


def clean_sentence(text: str) -> str:
    """Strip list markers and stray punctuation from one sentence."""
    cleaned = " ".join(text.split())
    cleaned = re.sub(r"^[\-\u2022\u2013\u2014\*\d.)\s]+", "", cleaned)
    cleaned = re.sub(r"\s*\|\s*", " ", cleaned)
    return cleaned.strip(" \"'")


def split_sentences(text: str) -> list[str]:
    """Split prose into whole sentences, re-joining abbreviation fragments."""
    fragments: list[str] = []
    for block in text.splitlines():
        stripped = block.strip()
        if not stripped:
            continue
        fragments.extend(piece for piece in SENTENCE_END_RE.split(stripped) if piece.strip())

    sentences: list[str] = []
    for fragment in fragments:
        candidate = clean_sentence(fragment)
        if not candidate:
            continue
        if sentences and (len(candidate) < 40 or sentences[-1].casefold().endswith(ABBREVIATIONS)):
            sentences[-1] = f"{sentences[-1]} {candidate}".strip()
            continue
        sentences.append(candidate)
    return [s for s in sentences if len(s) >= MIN_SENTENCE_CHARS]


def salient_sentences(
    text: str,
    keywords: tuple[str, ...] | set[str] = (),
    limit: int = 4,
    min_score: int = 2,
) -> list[str]:
    """The most human-experience-bearing sentences in a page, best first."""
    keywords = tuple(keywords)
    ranked: list[tuple[int, int, str]] = []
    seen: set[str] = set()
    for position, sentence in enumerate(split_sentences(text)):
        key = note_key(sentence)
        if not key or key in seen:
            continue
        seen.add(key)
        score = experience_score(sentence, keywords)
        if score < min_score or not is_experiential(sentence, keywords):
            continue
        ranked.append((score, -position, sentence))
    ranked.sort(reverse=True)
    return [sentence for _, _, sentence in ranked[: max(0, limit)]]


def keyword_hits(text: str, keywords: tuple[str, ...] | set[str]) -> int:
    """How many of the given keywords appear in the text."""
    lowered = text.casefold()
    return sum(1 for keyword in keywords if keyword.casefold() in lowered)


def is_probably_article(text: str, keywords: tuple[str, ...] | set[str] = ()) -> bool:
    """True when a page carries enough relevant prose to be worth curating."""
    if len(text) < 400:
        return False
    words = WORD_RE.findall(text)
    if len(words) < 80:
        return False
    return bool(keywords) is False or keyword_hits(text, keywords) > 0
