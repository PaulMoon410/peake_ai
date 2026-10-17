"""Collect the links on a page so Harold can read a little further.

The crawler stays shallow on purpose: links are limited to the same host, obvious
non-article paths are dropped, and the agent decides how many to follow. This is
what lets one article lead Harold to the next related one without wandering off
the site he was invited to read.
"""

from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
import re
import urllib.parse

from .readability import SKIP_TAGS


BINARY_EXTENSIONS = (
    ".pdf", ".zip", ".gz", ".tgz", ".png", ".jpg", ".jpeg", ".gif", ".webp",
    ".svg", ".ico", ".mp3", ".mp4", ".wav", ".ogg", ".css", ".js", ".json",
    ".xml", ".rss", ".atom", ".woff", ".woff2", ".ttf", ".doc", ".docx", ".xls",
)
NAVIGATION_MARKERS = (
    "special:", "talk:", "user:", "help:", "wikipedia:", "template:", "file:",
    "category:", "portal:", "draft:", "module:", "mediawiki:", "edit", "action=",
    "oldid=", "diff=", "printable=", "share=", "login", "signup", "sign-up",
    "privacy", "terms", "cookie", "contact", "donate", "subscribe", "account",
)


class _LinkExtractor(HTMLParser):
    """Gather anchor targets that are worth following."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.casefold()
        if lowered in SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth or lowered != "a":
            return
        attributes = {key.casefold(): (value or "") for key, value in attrs}
        href = attributes.get("href", "").strip()
        if href and not href.casefold().startswith(("javascript:", "mailto:", "tel:", "#")):
            self.hrefs.append(href)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)


@dataclass(frozen=True, slots=True)
class PageLink:
    """One followable link, normalised to an absolute URL."""

    url: str
    anchor: str


def _is_followable(url: str, deny_path_fragments: tuple[str, ...]) -> bool:
    lowered = url.casefold()
    if any(lowered.endswith(extension) for extension in BINARY_EXTENSIONS):
        return False
    if any(marker in lowered for marker in NAVIGATION_MARKERS):
        return False
    return not any(fragment.casefold() in lowered for fragment in deny_path_fragments)


def extract_links(
    html: str,
    base_url: str,
    same_host_only: bool = True,
    deny_path_fragments: tuple[str, ...] = (),
    limit: int = 40,
) -> list[PageLink]:
    """Absolute, de-duplicated links from a page, in document order."""
    parser = _LinkExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        pass
    base_host = urllib.parse.urlsplit(base_url).hostname or ""
    seen: set[str] = set()
    links: list[PageLink] = []
    for href in parser.hrefs:
        absolute = urllib.parse.urljoin(base_url, href)
        absolute = absolute.split("#", 1)[0]
        if not absolute.startswith(("http://", "https://")):
            continue
        parsed = urllib.parse.urlsplit(absolute)
        if same_host_only and (parsed.hostname or "").casefold() != base_host.casefold():
            continue
        if not _is_followable(absolute, deny_path_fragments):
            continue
        key = absolute.rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        links.append(PageLink(url=absolute, anchor=""))
        if len(links) >= limit:
            break
    return links


def title_from_url(url: str) -> str:
    """A readable title guessed from the last path segment of a URL."""
    path = urllib.parse.urlsplit(url).path.rstrip("/")
    if not path:
        return urllib.parse.urlsplit(url).hostname or url
    last = urllib.parse.unquote(path.rsplit("/", 1)[-1])
    words = re.sub(r"[_\-]+", " ", last).strip()
    return words[:120] or last[:120]
