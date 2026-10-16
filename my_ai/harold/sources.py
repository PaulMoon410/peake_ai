"""Where Harold's raw material comes from.

One parser reads DuckDuckGo's result markup whether it arrives from the Lite
endpoint (``result-link``) or the HTML endpoint (``result__a``), so the search
provider can fall back between the two without a second implementation. Every
result is validated by the URL guard before it is offered to the agent.
"""

from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
import urllib.parse

from harold import urlguard
from harold.net import FetchError, PoliteFetcher


DDG_LITE_ENDPOINT = "https://lite.duckduckgo.com/lite/"
DDG_HTML_ENDPOINT = "https://html.duckduckgo.com/html/"
DEFAULT_ENDPOINTS = (DDG_LITE_ENDPOINT, DDG_HTML_ENDPOINT)
RESULT_LINK_CLASSES = ("result-link", "result__a")
SNIPPET_CLASSES = ("result-snippet", "result__snippet")


@dataclass(frozen=True, slots=True)
class SearchHit:
    """One search result, already checked against the URL guard."""

    title: str
    url: str
    snippet: str = ""
    query: str = ""

    def as_dict(self) -> dict[str, str]:
        return {"title": self.title, "url": self.url, "snippet": self.snippet}


def decode_redirect(href: str) -> str:
    """Turn a search engine's tracking link into the destination URL."""
    if "uddg=" not in href:
        return href
    query = urllib.parse.urlsplit(href).query
    values = urllib.parse.parse_qs(query)
    target = values.get("uddg", [""])[0]
    return target or href


class _ResultParser(HTMLParser):
    """Read titles, links and snippets out of a search results page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hits: list[dict[str, str]] = []
        self._capturing_title = False
        self._snippet_target: dict[str, str] | None = None
        self._snippet_tag: str | None = None

    @staticmethod
    def _classes(attrs: list[tuple[str, str | None]]) -> list[str]:
        for key, value in attrs:
            if key.casefold() == "class" and value:
                return value.split()
        return []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = self._classes(attrs)
        if tag == "a" and any(name in classes for name in RESULT_LINK_CLASSES):
            href = ""
            for key, value in attrs:
                if key.casefold() == "href" and value:
                    href = value
            self.hits.append({"url": decode_redirect(href.strip()), "title": "", "snippet": ""})
            self._capturing_title = True
            return
        if any(name in classes for name in SNIPPET_CLASSES) and self.hits:
            self._snippet_target = self.hits[-1]
            self._snippet_tag = tag

    def handle_data(self, data: str) -> None:
        if self._capturing_title and self.hits:
            self.hits[-1]["title"] += data
        elif self._snippet_target is not None:
            self._snippet_target["snippet"] += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._capturing_title:
            self._capturing_title = False
            if self.hits:
                self.hits[-1]["title"] = " ".join(self.hits[-1]["title"].split())
            return
        if self._snippet_tag is not None and tag == self._snippet_tag:
            if self._snippet_target is not None:
                self._snippet_target["snippet"] = " ".join(
                    self._snippet_target["snippet"].split()
                )
            self._snippet_target = None
            self._snippet_tag = None


def parse_search_html(html: str, limit: int = 8) -> list[SearchHit]:
    """Parse a search results page into validated hits."""
    parser = _ResultParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        pass
    hits: list[SearchHit] = []
    seen: set[str] = set()
    for raw in parser.hits:
        url = raw.get("url", "").strip()
        title = raw.get("title", "").strip()
        if not url or not title or url in seen:
            continue
        try:
            checked = urlguard.approve(url)
        except urlguard.UrlRejected:
            continue
        if checked in seen:
            continue
        seen.add(checked)
        hits.append(SearchHit(title=title, url=checked, snippet=raw.get("snippet", "").strip()))
        if len(hits) >= limit:
            break
    return hits


@dataclass
class WebSearchSource:
    """Find candidate pages about a question using a public search endpoint."""

    fetcher: PoliteFetcher
    endpoints: tuple[str, ...] = DEFAULT_ENDPOINTS
    name: str = "web-search"

    def search(self, query: str, limit: int = 5) -> list[SearchHit]:
        """Best-effort search. Returns an empty list rather than raising."""
        for endpoint in self.endpoints:
            url = endpoint + "?" + urllib.parse.urlencode({"q": query})
            try:
                page = self.fetcher.page(url)
            except (FetchError, urlguard.UrlRejected):
                continue
            hits = parse_search_html(page.text, limit=limit)
            if hits:
                return [SearchHit(h.title, h.url, h.snippet, query) for h in hits]
        return []
