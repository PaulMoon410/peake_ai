"""robots.txt handling for Harold.

The cache takes a plain ``fetch_text`` callable so it can be exercised offline in
tests. Rules follow RFC 9309 closely enough to be conservative: the most specific
matching group wins, the longest matching path rule wins, and an allow and a
disallow of equal length resolve in favour of the site's *allow* only when the
allow rule is not overridden by a longer disallow.
"""

from __future__ import annotations

from collections.abc import Callable
import re
from dataclasses import dataclass, field


MAX_CRAWL_DELAY_SECONDS = 30.0
DEFAULT_CRAWL_DELAY_SECONDS = 1.0
MAX_ROBOTS_BYTES = 512 * 1024
_WILDCARD_RE_CACHE: dict[str, re.Pattern[str]] = {}


@dataclass(frozen=True, slots=True)
class RobotsRules:
    """The rules that apply to one crawler for one host."""

    allow: tuple[str, ...] = ()
    disallow: tuple[str, ...] = ()
    crawl_delay: float | None = None
    source: str = "absent"

    def permits(self, path: str) -> bool:
        """True when the path may be fetched."""
        return _longest_rule_permits(self.allow, self.disallow, path)

    @property
    def delay_seconds(self) -> float:
        """Polite delay to leave between requests to this host."""
        if self.crawl_delay is None:
            return DEFAULT_CRAWL_DELAY_SECONDS
        return max(0.0, min(self.crawl_delay, MAX_CRAWL_DELAY_SECONDS))


ALLOW_ALL = RobotsRules(source="absent")


def _pattern_to_regex(pattern: str) -> re.Pattern[str]:
    """Compile a robots path pattern, honouring '*' wildcards and '$' anchors."""
    cached = _WILDCARD_RE_CACHE.get(pattern)
    if cached is not None:
        return cached
    anchored_end = pattern.endswith("$")
    body = pattern[:-1] if anchored_end else pattern
    parts = [re.escape(piece) for piece in body.split("*")]
    expression = ".*".join(parts)
    expression = "^" + expression + ("$" if anchored_end else "")
    compiled = re.compile(expression)
    _WILDCARD_RE_CACHE[pattern] = compiled
    return compiled


def _matches(pattern: str, path: str) -> bool:
    if not pattern:
        return False
    return _pattern_to_regex(pattern).match(path) is not None


def _longest_rule_permits(allow: tuple[str, ...], disallow: tuple[str, ...], path: str) -> bool:
    """Resolve competing rules by specificity, as real crawlers do."""
    blocked = max((len(p) for p in disallow if _matches(p, path)), default=-1)
    if blocked < 0:
        return True
    permitted = max((len(p) for p in allow if _matches(p, path)), default=-1)
    return permitted >= blocked


def _agent_groups(text: str) -> list[tuple[list[str], list[str], list[str], float | None]]:
    """Split a robots.txt into (agents, allow, disallow, crawl_delay) records."""
    groups: list[tuple[list[str], list[str], list[str], float | None]] = []
    agents: list[str] = []
    allow: list[str] = []
    disallow: list[str] = []
    delay: float | None = None
    pending_agents = True

    def flush() -> None:
        nonlocal agents, allow, disallow, delay, pending_agents
        if agents:
            groups.append((agents, allow, disallow, delay))
        agents, allow, disallow, delay = [], [], [], None
        pending_agents = True

    for raw_line in text.splitlines()[:20000]:
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().casefold()
        value = value.strip()
        if key == "user-agent":
            if not pending_agents:
                flush()
            agents.append(value.casefold())
            pending_agents = True
        elif key in {"allow", "disallow"}:
            if not agents:
                continue
            pending_agents = False
            (allow if key == "allow" else disallow).append(value)
        elif key == "crawl-delay":
            if not agents:
                continue
            pending_agents = False
            try:
                delay = float(value)
            except ValueError:
                delay = None
    flush()
    return groups


def parse_robots(text: str, agent_token: str) -> RobotsRules:
    """Rules for ``agent_token``, falling back to the '*' group."""
    wanted = agent_token.casefold()
    exact: RobotsRules | None = None
    wildcard: RobotsRules | None = None
    for agents, allow, disallow, delay in _agent_groups(text):
        rules = RobotsRules(
            allow=tuple(allow), disallow=tuple(disallow),
            crawl_delay=delay, source="robots.txt",
        )
        if wanted in agents and exact is None:
            exact = rules
        elif "*" in agents and wildcard is None:
            wildcard = rules
    chosen = exact or wildcard
    if chosen is None:
        return RobotsRules(source="robots.txt")
    return chosen


@dataclass
class RobotsCache:
    """Per-host robots.txt cache. ``fetch_text`` returns None when there is none."""

    fetch_text: Callable[[str], str | None]
    agent_token: str
    _entries: dict[str, RobotsRules] = field(default_factory=dict)

    def rules_for(self, origin: str) -> RobotsRules:
        """Cached rules for an origin such as https://example.org."""
        if origin in self._entries:
            return self._entries[origin]
        robots_url = origin.rstrip("/") + "/robots.txt"
        try:
            text = self.fetch_text(robots_url)
        except Exception:
            # An unreachable robots.txt is not permission. Treat it as a site
            # that has not told us anything, and rely on the polite delay.
            text = None
        if text is None:
            rules = ALLOW_ALL
        else:
            rules = parse_robots(text[:MAX_ROBOTS_BYTES], self.agent_token)
        self._entries[origin] = rules
        return rules

    def permits(self, url: str, path: str) -> bool:
        """True when the path is allowed for our agent on that origin."""
        return self.rules_for(url).permits(path)
