"""Polite HTTP fetching for Harold.

Every request goes through the URL guard, honours robots.txt, waits its turn per
host, caps the bytes it reads, and follows redirects one hop at a time so each new
location is re-validated. No cookies, no forms, no JavaScript, GET only.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import time
import urllib.error
import urllib.parse
import urllib.request

from harold import robots as robots_module
from harold import urlguard


DEFAULT_USER_AGENT = (
    "PocketAI-Harold/1.0 (personal research assistant; respects robots.txt)"
)
DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_MAX_BYTES = 512 * 1024
DEFAULT_MAX_REDIRECTS = 3
DEFAULT_MIN_DELAY_SECONDS = 1.0
READ_CHUNK_BYTES = 32 * 1024
REDIRECT_CODES = frozenset({301, 302, 303, 307, 308})
TEXT_CONTENT_TYPES = ("text/", "application/xhtml", "application/json", "application/xml")


class FetchError(RuntimeError):
    """Raised when a page cannot be fetched within Harold's rules."""


def agent_token(user_agent: str = DEFAULT_USER_AGENT) -> str:
    """Product token used for robots.txt group matching."""
    return user_agent.strip().split(" ", 1)[0].split("/", 1)[0]


@dataclass(frozen=True, slots=True)
class FetchPolicy:
    """Everything that bounds a Harold request."""

    user_agent: str = DEFAULT_USER_AGENT
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_bytes: int = DEFAULT_MAX_BYTES
    max_redirects: int = DEFAULT_MAX_REDIRECTS
    min_delay_seconds: float = DEFAULT_MIN_DELAY_SECONDS
    respect_robots: bool = True
    denied_suffixes: tuple[str, ...] = urlguard.DEFAULT_DENY_SUFFIXES

    @property
    def token(self) -> str:
        return agent_token(self.user_agent)


@dataclass(frozen=True, slots=True)
class FetchResult:
    """A fetched resource, already bounded and decoded-ready."""

    url: str
    status: int
    content_type: str
    body: bytes
    truncated: bool = False

    @property
    def charset(self) -> str:
        for parameter in self.content_type.split(";")[1:]:
            key, _, value = parameter.partition("=")
            if key.strip().casefold() == "charset" and value.strip():
                return value.strip().strip('"').casefold()
        return "utf-8"

    @property
    def text(self) -> str:
        """Decoded body, never raising on malformed bytes."""
        try:
            return self.body.decode(self.charset, errors="replace")
        except LookupError:
            return self.body.decode("utf-8", errors="replace")


@dataclass
class _RawResponse:
    status: int
    headers: object
    body: bytes
    truncated: bool
    content_type: str


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Redirects are resolved manually so each hop is re-validated."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102, ANN001
        return None


@dataclass
class PoliteFetcher:
    """A single, well-behaved client for public text pages."""

    policy: FetchPolicy = field(default_factory=FetchPolicy)
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic
    _last_request_at: dict[str, float] = field(default_factory=dict)
    _robots: robots_module.RobotsCache = field(init=False)

    def __post_init__(self) -> None:
        self._robots = robots_module.RobotsCache(self._fetch_robots_text, self.policy.token)

    # -- public API ---------------------------------------------------------
    def page(self, url: str) -> FetchResult:
        """Fetch an allowed page, following validated redirects."""
        current = urlguard.approve(url, self.policy.denied_suffixes)
        for _ in range(self.policy.max_redirects + 1):
            if self.policy.respect_robots and not self._allowed(current):
                raise FetchError(f"robots.txt disallows {current}")
            response = self._request(current)
            if response.status not in REDIRECT_CODES:
                return self._as_result(current, response)
            location = self._header(response, "Location")
            if not location:
                raise FetchError(f"Redirect from {current} without a Location header.")
            current = urlguard.approve(
                urllib.parse.urljoin(current, location), self.policy.denied_suffixes
            )
        raise FetchError(f"Too many redirects starting at {url}.")

    def robots_text(self, url: str) -> str | None:
        """Raw robots.txt contents, or None when the host does not serve one."""
        try:
            approved = urlguard.approve(url, self.policy.denied_suffixes)
            response = self._request(approved)
        except (FetchError, urlguard.UrlRejected):
            return None
        if not 200 <= response.status < 300:
            return None
        return response.body.decode("utf-8", errors="replace")

    # -- internals ----------------------------------------------------------
    def _as_result(self, url: str, response: _RawResponse) -> FetchResult:
        if response.status != 200:
            raise FetchError(f"{url} returned HTTP {response.status}.")
        content_type = response.content_type.casefold()
        if not any(content_type.startswith(kind) for kind in TEXT_CONTENT_TYPES):
            raise FetchError(f"{url} is {content_type or 'an unknown type'}, not a text page.")
        return FetchResult(
            url=url, status=response.status, content_type=response.content_type,
            body=response.body, truncated=response.truncated,
        )

    def _allowed(self, url: str) -> bool:
        parsed = urllib.parse.urlsplit(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        return self._robots.rules_for(origin).permits(parsed.path or "/")

    def _fetch_robots_text(self, robots_url: str) -> str | None:
        return self.robots_text(robots_url)

    @staticmethod
    def _header(response: _RawResponse, name: str) -> str:
        if hasattr(response.headers, "get"):
            return response.headers.get(name, "") or ""
        return ""

    def _wait_for_host(self, url: str, delay: float) -> None:
        origin = urllib.parse.urlsplit(url).netloc.casefold()
        last = self._last_request_at.get(origin)
        wait = self.policy.min_delay_seconds
        if last is not None:
            wait = max(wait, delay)
        now = self.clock()
        if last is not None and now - last < wait:
            self.sleep(wait - (now - last))
        self._last_request_at[origin] = self.clock()

    def _request(self, url: str) -> _RawResponse:
        parsed = urllib.parse.urlsplit(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        self._wait_for_host(url, self._robots.rules_for(origin).delay_seconds)
        request = urllib.request.Request(
            url, headers={"User-Agent": self.policy.user_agent, "Accept": "text/html,text/plain;q=0.9,*/*;q=0.1"}
        )
        opener = urllib.request.build_opener(_NoRedirect)
        try:
            with opener.open(request, timeout=self.policy.timeout_seconds) as handle:
                return self._read(handle)
        except urllib.error.HTTPError as exc:
            return self._read(exc)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            raise FetchError(f"Could not fetch {url}: {exc}") from exc

    def _read(self, handle) -> _RawResponse:  # noqa: ANN001
        limit = self.policy.max_bytes
        chunks: list[bytes] = []
        total = 0
        truncated = False
        while True:
            try:
                chunk = handle.read(READ_CHUNK_BYTES)
            except (OSError, ValueError) as exc:
                raise FetchError(f"Connection failed while reading: {exc}") from exc
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total >= limit:
                truncated = True
                break
        body = b"".join(chunks)[:limit]
        headers = getattr(handle, "headers", None)
        content_type = ""
        if headers is not None and hasattr(headers, "get_content_type"):
            content_type = headers.get_content_type() or ""
        status = getattr(handle, "status", None) or getattr(handle, "code", 0)
        try:
            handle.close()
        except Exception:
            pass
        return _RawResponse(
            status=int(status or 0), headers=headers, body=body,
            truncated=truncated, content_type=content_type,
        )
