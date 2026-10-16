"""URL safety rules for Harold's fetcher.

Harold is an autonomous scraper, so every URL is treated as hostile until it
proves otherwise. Only public http/https hosts are reachable; loopback, private,
link-local and cloud-metadata addresses are refused, as are URLs carrying
credentials. This is the guard that keeps a scraped page from steering Harold at
the local model server or the machine's own network.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit


MAX_URL_CHARS = 2048
ALLOWED_SCHEMES = frozenset({"http", "https"})
ALLOWED_PORTS = frozenset({80, 443})

# Sites that require a login, are mostly client-side JavaScript, or exist to
# trap scrapers. Harold skips them instead of burning his page budget on walls.
DEFAULT_DENY_SUFFIXES: tuple[str, ...] = (
    "facebook.com", "instagram.com", "x.com", "twitter.com", "tiktok.com",
    "pinterest.com", "quora.com", "youtube.com", "reddit.com", "linkedin.com",
    "amazon.com", "ebay.com", "netflix.com", "spotify.com", "discord.com",
)


class UrlRejected(ValueError):
    """Raised when a URL is not a permitted public, plain-HTTP resource."""


def canonical(url: str) -> str:
    """Trim a URL and drop any fragment, which never changes page content."""
    trimmed = url.strip()
    if "#" in trimmed:
        trimmed = trimmed.split("#", 1)[0]
    return trimmed


def _split(url: str):
    if len(url) > MAX_URL_CHARS:
        raise UrlRejected(f"URL longer than {MAX_URL_CHARS} characters.")
    try:
        parsed = urlsplit(url)
    except ValueError as exc:
        raise UrlRejected(f"Unparseable URL: {url!r}") from exc
    if parsed.scheme.casefold() not in ALLOWED_SCHEMES:
        raise UrlRejected("Only http:// and https:// URLs can be fetched.")
    if not parsed.hostname:
        raise UrlRejected("URL has no host.")
    if parsed.username or parsed.password:
        raise UrlRejected("URLs carrying credentials are refused.")
    return parsed


def hostname(url: str) -> str:
    """Lower-cased host of a permitted URL."""
    return _split(url).hostname.casefold()


def registrable_host(url: str) -> str:
    """Best-effort domain for grouping pages by site (no public-suffix list)."""
    parts = hostname(url).split(".")
    if len(parts) >= 3 and len(parts[-2]) <= 3:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else "".join(parts)


def is_denied_host(url: str, denied_suffixes: tuple[str, ...] = DEFAULT_DENY_SUFFIXES) -> bool:
    """True when the host is on the skip list (login-walled or scraper-hostile)."""
    host = hostname(url)
    return any(host == suffix or host.endswith("." + suffix) for suffix in denied_suffixes)


def resolve_public_ips(host: str) -> list[str]:
    """Resolve a host to addresses, raising if it is not publicly routable.

    Resolution happens here, before any connection, so a hostname cannot resolve
    to a loopback or metadata address after the guard has approved it.
    """
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UrlRejected(f"Could not resolve host {host!r}.") from exc
    addresses: list[str] = []
    for info in infos:
        address = info[4][0]
        if address not in addresses:
            addresses.append(address)
    if not addresses:
        raise UrlRejected(f"Host {host!r} resolved to no addresses.")
    for address in addresses:
        if not is_public_address(address):
            raise UrlRejected(f"Host {host!r} resolves to non-public address {address}.")
    return addresses


def is_public_address(address: str) -> bool:
    """True only for globally routable unicast addresses."""
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return False
    if isinstance(parsed, ipaddress.IPv6Address) and parsed.ipv4_mapped is not None:
        return is_public_address(str(parsed.ipv4_mapped))
    return not (
        parsed.is_private
        or parsed.is_loopback
        or parsed.is_link_local
        or parsed.is_multicast
        or parsed.is_reserved
        or parsed.is_unspecified
    )


def approve(url: str, denied_suffixes: tuple[str, ...] = DEFAULT_DENY_SUFFIXES) -> str:
    """Validate a URL end to end and return its canonical form."""
    cleaned = canonical(url)
    parsed = _split(cleaned)
    if parsed.port is not None and parsed.port not in ALLOWED_PORTS:
        raise UrlRejected(f"Only ports 80 and 443 are fetched, not {parsed.port}.")
    host = parsed.hostname.casefold()
    if is_denied_host(cleaned, denied_suffixes):
        raise UrlRejected(f"Host {host!r} is on Harold's skip list.")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        resolve_public_ips(host)
    else:
        if not is_public_address(host):
            raise UrlRejected(f"Address {host!r} is not publicly routable.")
    return cleaned
