"""Extract topic-relevant source passages and compare independent pages.

This module preserves the source wording instead of asking a small model to
invent a fact summary. Similar passages across distinct registrable domains
are reported as corroborating evidence, never as proof that a claim is true.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
import re

from .lexicon import is_boilerplate, words
from .net import FetchError, PoliteFetcher
from .readability import html_to_text, split_sentences
from .urlguard import UrlRejected, registrable_host


_STOP_WORDS = frozenset({
    "about", "after", "again", "also", "and", "are", "because", "been", "before",
    "being", "between", "could", "does", "during", "each", "from", "have", "into",
    "more", "most", "other", "over", "same", "some", "such", "than", "that", "their",
    "them", "then", "there", "these", "they", "this", "those", "through", "under",
    "very", "what", "when", "where", "which", "while", "with", "would",
})
_MAX_SOURCES = 4
_MAX_EXCERPTS_PER_SOURCE = 3
_MIN_EXCERPT_CHARS = 50
_MAX_EXCERPT_CHARS = 460


@dataclass(frozen=True, slots=True)
class SourcePage:
    """Extracted evidence saved from one source page."""

    url: str
    title: str
    excerpts: tuple[str, ...]
    notes_added: int
    notes_uploaded: int
    detail: str = ""


@dataclass(frozen=True, slots=True)
class Corroboration:
    """Similar source excerpts on distinct domains; not a truth guarantee."""

    first_excerpt: str
    first_url: str
    second_excerpt: str
    second_url: str
    shared_terms: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SourceResearchReport:
    """Result of bounded, source-preserving research over a small URL set."""

    topic: str
    pages: tuple[SourcePage, ...]
    corroborations: tuple[Corroboration, ...]

    @property
    def notes_added(self) -> int:
        return sum(page.notes_added for page in self.pages)

    @property
    def notes_uploaded(self) -> int:
        return sum(page.notes_uploaded for page in self.pages)


class SourceResearcher:
    """Extract source-backed evidence and conservatively compare several pages."""

    def __init__(self, store: object, fetcher: PoliteFetcher) -> None:
        self.store = store
        self.fetcher = fetcher

    def learn(self, topic: str, urls: list[str]) -> SourceResearchReport:
        """Save short source excerpts and report close matches across distinct domains."""
        cleaned_topic = " ".join(topic.split())
        if not cleaned_topic or len(cleaned_topic) > 120:
            raise ValueError("Enter a topic between 1 and 120 characters.")
        if not 2 <= len(urls) <= _MAX_SOURCES:
            raise ValueError(f"Provide two to {_MAX_SOURCES} source URLs.")

        domains: set[str] = set()
        for url in urls:
            if len(url) > 500:
                raise ValueError("Source URLs must be 500 characters or fewer so Harold can save the citation.")
            try:
                domain = registrable_host(url)
            except (UrlRejected, ValueError) as exc:
                raise ValueError("Use valid public HTTP(S) article URLs.") from exc
            if domain in domains:
                raise ValueError("Use sources from distinct registrable domains to compare them.")
            domains.add(domain)

        topic_terms = {
            token for token in words(cleaned_topic)
            if len(token) > 2 and token not in _STOP_WORDS
        }
        category = "Harold/Research/" + re.sub(r"[^A-Za-z0-9_-]+", "-", cleaned_topic).strip("-")[:48]
        results: list[tuple[SourcePage, list[dict[str, str]]]] = []
        for url in urls:
            results.append(self._read_source(url, topic_terms, category))

        pending_by_page = [records for _, records in results]
        pending_uploads = [record for records in pending_by_page for record in records]
        uploaded = 0
        if pending_uploads and getattr(self.store, "ftp_configured", False):
            try:
                uploaded = self.store.upload_many(pending_uploads, timeout=5.0)  # type: ignore[attr-defined]
            except Exception:
                uploaded = 0

        pages: list[SourcePage] = []
        upload_offset = 0
        for page, page_records in results:
            page_uploaded = min(len(page_records), max(0, uploaded - upload_offset))
            upload_offset += len(page_records)
            pages.append(SourcePage(
                url=page.url,
                title=page.title,
                excerpts=page.excerpts,
                notes_added=page.notes_added,
                notes_uploaded=page_uploaded,
                detail=page.detail,
            ))
        corroborations = self._compare_pages(pages)
        return SourceResearchReport(cleaned_topic, tuple(pages), tuple(corroborations))

    def _read_source(
        self, url: str, topic_terms: set[str], category: str,
    ) -> tuple[SourcePage, list[dict[str, str]]]:
        try:
            fetched = self.fetcher.page(url)
            page = html_to_text(fetched.text, url=fetched.url, max_chars=12000)
        except (FetchError, UrlRejected, OSError, ValueError) as exc:
            return (
                SourcePage(url=url, title="", excerpts=(), notes_added=0,
                           notes_uploaded=0, detail=f"read refused: {exc}"),
                [],
            )

        excerpts = self._select_excerpts(page.text, topic_terms)
        added = 0
        records: list[dict[str, str]] = []
        for excerpt in excerpts:
            try:
                record = self.store.add(excerpt, category=category, source=fetched.url)  # type: ignore[attr-defined]
            except (OSError, ValueError) as exc:
                return (
                    SourcePage(fetched.url, page.title, tuple(excerpts), added, 0,
                               f"could not save all excerpts: {exc}"),
                    records,
                )
            if record is None:
                continue
            added += 1
            records.append(record)
        return SourcePage(fetched.url, page.title, tuple(excerpts), added, 0), records

    @staticmethod
    def _select_excerpts(text: str, topic_terms: set[str]) -> list[str]:
        ranked: list[tuple[int, int, str]] = []
        seen: set[str] = set()
        for index, sentence in enumerate(split_sentences(text)):
            normalized = " ".join(sentence.split())
            folded = normalized.casefold()
            if not (_MIN_EXCERPT_CHARS <= len(normalized) <= _MAX_EXCERPT_CHARS):
                continue
            if is_boilerplate(normalized) or folded in seen:
                continue
            seen.add(folded)
            sentence_terms = set(words(normalized))
            relevance = len(sentence_terms & topic_terms)
            if topic_terms and not relevance:
                continue
            ranked.append((relevance, -index, normalized))
        ranked.sort(reverse=True)
        return [sentence for _, _, sentence in ranked[:_MAX_EXCERPTS_PER_SOURCE]]

    @staticmethod
    def _compare_pages(pages: list[SourcePage]) -> list[Corroboration]:
        matches: list[Corroboration] = []
        for first, second in combinations(pages, 2):
            if not first.url or not second.url:
                continue
            if registrable_host(first.url) == registrable_host(second.url):
                continue
            for first_excerpt in first.excerpts:
                first_terms = {
                    token for token in words(first_excerpt)
                    if len(token) > 3 and token not in _STOP_WORDS
                }
                for second_excerpt in second.excerpts:
                    second_terms = {
                        token for token in words(second_excerpt)
                        if len(token) > 3 and token not in _STOP_WORDS
                    }
                    shared = first_terms & second_terms
                    union = first_terms | second_terms
                    if len(shared) >= 4 and len(shared) / max(1, len(union)) >= 0.6:
                        matches.append(Corroboration(
                            first_excerpt=first_excerpt,
                            first_url=first.url,
                            second_excerpt=second_excerpt,
                            second_url=second.url,
                            shared_terms=tuple(sorted(shared)),
                        ))
        return matches