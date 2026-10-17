"""Decide what Harold should read next for a given topic.

Discovery only proposes candidate pages with a reason attached; the agent decides
what to actually fetch, how many, and when to stop. Ranking favours encyclopedia
articles and treats search results as leads rather than truths.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import urllib.parse

from . import urlguard
from .net import PoliteFetcher
from .sources import WebSearchSource
from .topics import CurriculumTopic
from .wiki import WikipediaSource


# Paths that usually mean a tag archive, feed or index rather than an article.
INDEX_PATH_MARKERS = (
    "/tag/", "/tags/", "/category/", "/categories/", "/topics/", "/archive",
    "/author/", "/feed", "/rss", "/page/", "/wp-json", "/search", "?s=", "?p=",
)
ORIGIN_SCORES = {"wikipedia": 30, "search": 10, "link": 5, "direct": 40}


@dataclass(frozen=True, slots=True)
class Candidate:
    """A page Harold could read, and why he might."""

    url: str
    title: str
    origin: str
    score: int = 0
    snippet: str = ""

    @property
    def host(self) -> str:
        return urlguard.hostname(self.url)


@dataclass
class Discovery:
    """Gather candidate pages for a curriculum topic."""

    fetcher: PoliteFetcher
    wikipedia: WikipediaSource
    web: WebSearchSource
    search_result_limit: int = 5
    _seen: set[str] = field(default_factory=set, init=False)

    def for_topic(self, topic: CurriculumTopic, limit: int = 4) -> list[Candidate]:
        """Ranked candidates: encyclopedia articles first, then web leads."""
        found: list[Candidate] = []
        for url in self.wikipedia.article_candidates(topic):
            found.append(Candidate(url=url, title=topic.name, origin="wikipedia",
                                   score=ORIGIN_SCORES["wikipedia"] + 5))
        for hit in self.wikipedia.search_articles(topic, limit=2):
            found.append(Candidate(url=hit.url, title=hit.title or topic.name,
                                   origin="wikipedia", score=ORIGIN_SCORES["wikipedia"],
                                   snippet=hit.snippet))
        for hit in self.web.search(topic.question, limit=self.search_result_limit):
            found.append(Candidate(url=hit.url, title=hit.title or hit.url,
                                   origin="search", score=ORIGIN_SCORES["search"],
                                   snippet=hit.snippet))
        return self._rank(found)[:limit]

    def for_url(self, url: str, title: str = "") -> list[Candidate]:
        """A single explicit candidate, validated."""
        try:
            approved = urlguard.approve(url)
        except urlguard.UrlRejected:
            return []
        return [Candidate(url=approved, title=title or approved, origin="direct",
                          score=ORIGIN_SCORES["direct"])]

    def links_from(self, url: str, html: str, limit: int = 2) -> list[Candidate]:
        """Follow a couple of same-host article links from a page just read."""
        candidates: list[Candidate] = []
        if self.wikipedia.is_article_url(url):
            for related in self.wikipedia.related_articles(url, html, limit=limit):
                candidates.append(Candidate(url=related, title="", origin="link",
                                            score=ORIGIN_SCORES["link"]))
        return candidates

    def mark_seen(self, url: str) -> None:
        """Remember a URL so later topics do not repeat it in one session."""
        self._seen.add(url.rstrip("/"))

    def has_seen(self, url: str) -> bool:
        """True when this URL has already been offered in this session."""
        return url.rstrip("/") in self._seen

    def _rank(self, candidates: list[Candidate]) -> list[Candidate]:
        ranked: dict[str, Candidate] = {}
        for candidate in candidates:
            key = candidate.url.rstrip("/")
            if key in self._seen or key in ranked:
                continue
            if self._is_index_page(candidate.url):
                continue
            ranked[key] = candidate
        return sorted(ranked.values(), key=lambda item: item.score, reverse=True)

    @staticmethod
    def _is_index_page(url: str) -> bool:
        parsed = urllib.parse.urlsplit(url)
        lowered = (parsed.path + ("?" + parsed.query if parsed.query else "")).casefold()
        return any(marker in lowered for marker in INDEX_PATH_MARKERS)
