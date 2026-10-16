"""Wikipedia as a source, using only what its robots.txt permits.

English Wikipedia's ``*`` group allows ``/wiki/<Article>`` and disallows ``/w/``
and ``/api/``, so Harold reads ordinary article pages and extracts their prose
himself instead of calling the MediaWiki API. Article titles come from the
curriculum, and anything the curriculum misses is found through a search engine
restricted to the site with ``site:``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import urllib.parse

from harold.net import FetchError, PoliteFetcher
from harold.sources import SearchHit, WebSearchSource
from harold.topics import CurriculumTopic


WIKIPEDIA_ARTICLE_PREFIX = "/wiki/"
ARTICLE_DENY_FRAGMENTS: tuple[str, ...] = (
    "/wiki/Special:", "/wiki/Talk:", "/wiki/User:", "/wiki/Help:", "/wiki/File:",
    "/wiki/Category:", "/wiki/Template:", "/wiki/Wikipedia:", "/wiki/Portal:",
    "/wiki/Draft:", "/wiki/Module:", "/wiki/MediaWiki:", "/w/", "/api/",
    "action=edit", "veaction=", "oldid=", "diff=", "printable=",
)


def title_to_url(title: str, language: str = "en") -> str:
    """Build the canonical article URL for a title."""
    cleaned = title.strip().replace(" ", "_")
    if cleaned:
        cleaned = cleaned[0].upper() + cleaned[1:]
    return f"https://{language}.wikipedia.org{WIKIPEDIA_ARTICLE_PREFIX}{urllib.parse.quote(cleaned)}"


@dataclass
class WikipediaSource:
    """Read Wikipedia articles that match the curriculum."""

    fetcher: PoliteFetcher
    language: str = "en"
    name: str = "wikipedia"
    search: WebSearchSource | None = field(default=None)

    def article_candidates(self, topic: CurriculumTopic) -> list[str]:
        """Article URLs to try for a topic, most likely first."""
        titles: list[str] = [topic.name]
        keyword_title = " ".join(topic.keywords[:2])
        if keyword_title and keyword_title.casefold() != topic.name.casefold():
            titles.append(keyword_title)
        urls: list[str] = []
        for title in titles:
            url = title_to_url(title, self.language)
            if url not in urls:
                urls.append(url)
        return urls

    def search_articles(self, topic: CurriculumTopic, limit: int = 3) -> list[SearchHit]:
        """Find Wikipedia articles for a topic through the search engine."""
        if self.search is None:
            return []
        hits = self.search.search(
            f"site:{self.language}.wikipedia.org {topic.question}", limit=limit * 2
        )
        articles = [hit for hit in hits if self.is_article_url(hit.url)]
        return articles[:limit]

    def fetch_text(self, url: str) -> str:
        """Raw HTML of an allowed Wikipedia article."""
        return self.fetcher.page(url).text

    def is_article_url(self, url: str) -> bool:
        """True when a URL is a readable article rather than project furniture."""
        parsed = urllib.parse.urlsplit(url)
        if not (parsed.hostname or "").endswith("wikipedia.org"):
            return False
        if not parsed.path.startswith(WIKIPEDIA_ARTICLE_PREFIX):
            return False
        lowered = url.casefold()
        if any(fragment.casefold() in lowered for fragment in ARTICLE_DENY_FRAGMENTS):
            return False
        return len(parsed.path) > len(WIKIPEDIA_ARTICLE_PREFIX)

    def related_articles(self, url: str, html: str, limit: int = 2) -> list[str]:
        """Other article URLs linked from an article, for a shallow follow."""
        from harold.links import extract_links

        links = extract_links(
            html, url, same_host_only=True, deny_path_fragments=ARTICLE_DENY_FRAGMENTS, limit=60
        )
        related = [link.url for link in links if self.is_article_url(link.url) and link.url != url]
        return related[:limit]


__all__ = ["ARTICLE_DENY_FRAGMENTS", "WikipediaSource", "title_to_url", "FetchError"]
