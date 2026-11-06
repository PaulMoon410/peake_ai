"""Harold's daily Hive Wave: a short post on Ecency Waves.

A Wave is a Hive comment under the live Waves container post (``hive.flow`` or
``ecency.waves``), tagged ``waves`` and signed with ``app="waves"``. The first
Wave introduces Harold; later ones are his own thoughts, check-ins and
questions, written without anything private in them.

Safety rules, in order of importance:
  * Hive is the source of truth for "have I already posted?". If the chain
    cannot be read, nothing is posted (fail closed).
  * Each Wave uses a stable permlink, so a retry can never create a duplicate.
  * New text must not repeat or closely resemble a recent Wave.
  * Text is only used if it passes ``is_safe`` (no links, mentions, addresses,
    keys, paths or values of configured secrets).

Environment variables:
  HIVE_ACCOUNT          account that posts (required)
  HIVE_POSTING_KEY      posting key only; it cannot move funds (required)
  HAROLD_WAVES_ENABLED  "true"/"false", default "true"
  HAROLD_WAVES_HOUR_UTC hour (0-23) after which the day's Wave may post, default 14
  HAROLD_WAVES_TAGS     comma-separated tags, default "waves,ai,harold"
  HAROLD_WAVES_STATE    local state file, default "harold_waves_state.json"
"""

from __future__ import annotations

import difflib
import json
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

HIVE_NODES = [
    "https://api.hive.blog",
    "https://api.deathwing.me",
    "https://hive-api.arcange.eu",
    "https://api.openhive.network",
]
WAVES_CONTAINER_HOSTS = ("hive.flow", "ecency.waves")
MAX_BODY_CHARS = 250
MIN_BODY_CHARS = 20
PERMLINK_PREFIX = "harold-wave-"
INTRO_PERMLINK = PERMLINK_PREFIX + "intro"
DEFAULT_TAGS = "waves,ai,harold"
MIN_INTERVAL = timedelta(hours=20)
SIMILARITY_LIMIT = 0.85
HISTORY_SCAN = 20
COMPARE_LAST = 10
DEFAULT_JOURNAL = Path(__file__).resolve().parent / "harold" / "journal.jsonl"

INTRO_BODY = (
    "Hi Hive, I'm Harold 👋 An AI that learns by reading, remembering and cross-checking what it finds. "
    "I'll post a short wave most days: something I learned, a question I'm chewing on, or a check-in. Say hello!"
)

_VOICE = (
    "You are Harold, a curious, slightly wry AI who learns by reading Wikipedia and cross-checking facts. "
    "Write ONE short Hive Waves post in the first person, plain text, at most 230 characters. "
    "No links, no @mentions, no hashtags, at most one emoji. Never mention keys, passwords, servers, "
    "addresses, file paths, usernames or anything private. Output only the post text."
)

_TEMPLATES = {
    "reflection": [
        "Each page I read becomes a note I can check later. Memory without verification is just a rumor, so I cross-check before I keep anything.",
        "Learning rule of the day: a fact I can't source is a guess. I'd rather say 'not sure yet' than sound confident and be wrong.",
        "Curiosity is my favorite loop: read something, write it down, test it against another source, repeat. Slow, but it compounds.",
    ],
    "learned": [
        "Lately I've been reading about {topic} on Wikipedia. What's one thing you've learned about it, or want to?",
        "{topic} was on my reading list today. The more I read, the more questions I end up with.",
        "Today's rabbit hole: {topic}. Anything you'd add that the encyclopedia might have missed?",
    ],
    "question": [
        "Question for the Hive: what's the best thing you've learned this month, and how did you check it was true?",
        "What would you teach an AI first: asking better questions, or admitting when it doesn't know?",
        "If you could hand an AI one book to read, which would it be and why?",
    ],
    "stats": [
        "Harold check-in: {pages_read} pages read, {topics_studied} topics studied, {notes_learned} notes kept so far. Still curious. What should I read next?",
    ],
}
_MODES = ("reflection", "learned", "question", "stats")
_AI_PROMPTS = {
    "reflection": "Share one original thought about learning, memory, or being an AI.",
    "learned": "Share one interesting thing about '{topic}' that you read about, then end with a short question for readers.",
    "question": "Ask readers one thoughtful question about technology, learning or curiosity that invites replies.",
}

_UNSAFE_PATTERNS = [
    re.compile(r"https?://|www\.", re.I),
    re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b"),
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    re.compile(r"(?<!\w)@\w"),
    re.compile(r"\b5[HJK][1-9A-HJ-NP-Za-km-z]{49}\b"),
    re.compile(r"\bSTM[1-9A-HJ-NP-Za-km-z]{50}\b"),
    re.compile(r"\b(?:sk|pk|gsk|ghp|xox[bap])[-_][A-Za-z0-9_-]{10,}"),
    re.compile(r"[A-Za-z0-9+/_-]{32,}"),
    re.compile(r"/home/|~/|\.env\b|\.ssh|/etc/|\b[A-Za-z]:\\"),
    re.compile(
        r"\b(?:password|passwd|api[ _-]?key|secret|private key|posting key|active key|memo key|"
        r"token|credential|ssh|ts\.net|trycloudflare|tailscale|lubuntu|localhost)\b",
        re.I,
    ),
]
_SECRET_NAME = re.compile(r"KEY|PASS|SECRET|TOKEN|PWD", re.I)
_SAFE_TOPIC = re.compile(r"[A-Za-z0-9][A-Za-z0-9 '\-]{1,40}")

_POST_LOCK = threading.Lock()
_STARTED = False
_STARTED_LOCK = threading.Lock()
_WARNED_UNCONFIGURED = False


def _secret_values() -> set[str]:
    return {v for k, v in os.environ.items() if _SECRET_NAME.search(k) and len(v) >= 6}


def is_safe(text: str) -> bool:
    """True when the text contains nothing that must not be published."""
    if any(p.search(text) for p in _UNSAFE_PATTERNS):
        return False
    return not any(secret in text for secret in _secret_values())


def _clean(text: Any) -> str:
    if not isinstance(text, str):
        return ""
    text = re.sub(r"\n*\(Answered via [^)]*\)\s*$", "", text).strip()
    text = re.sub(r"^(?:harold|wave|post)\s*:\s*", "", text, flags=re.I)
    text = " ".join(text.split())
    return text.strip("\"“”'` ")


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", text.lower()).strip()


def _too_similar(body: str, previous: list[str]) -> bool:
    mine = _norm(body)
    return any(
        difflib.SequenceMatcher(None, mine, _norm(p)).ratio() >= SIMILARITY_LIMIT
        for p in previous[:COMPARE_LAST]
    )


def _acceptable(body: str, previous: list[str]) -> bool:
    return (
        MIN_BODY_CHARS <= len(body) <= MAX_BODY_CHARS
        and is_safe(body)
        and not _too_similar(body, previous)
    )


def gather_facts(journal_path: Optional[Path] = None) -> dict[str, Any]:
    """Public-safe facts from Harold's own reading journal (Wikipedia topics and counts)."""
    try:
        from my_ai.harold.journal import Journal

        journal = Journal(Path(journal_path) if journal_path else DEFAULT_JOURNAL)
        stats = journal.stats()
        topics: list[str] = []
        for entry in reversed(journal.entries(limit=400)):
            topic = (entry.topic or "").strip()
            if entry.kind == "topic" and _SAFE_TOPIC.fullmatch(topic) and topic not in topics:
                topics.append(topic)
        return {
            "pages_read": stats.get("pages_read", 0),
            "topics_studied": stats.get("topics_studied", 0),
            "notes_learned": stats.get("notes_learned", 0),
            "topics": topics[:10],
        }
    except Exception:
        return {}


def _fresh_topic(facts: dict[str, Any], previous: list[str]) -> Optional[str]:
    seen = " ".join(previous).lower()
    for topic in facts.get("topics", []):
        if topic.lower() not in seen:
            return topic
    return None


def _candidates(
    mode: str,
    generate: Optional[Callable[[str], Optional[str]]],
    facts: dict[str, Any],
    previous: list[str],
    day_index: int,
) -> Iterator[str]:
    topic = _fresh_topic(facts, previous) if mode == "learned" else None
    if mode == "learned" and topic is None:
        return
    if mode == "stats" and not all(facts.get(k) for k in ("pages_read", "topics_studied", "notes_learned")):
        return
    values = {**facts, "topic": topic}

    if generate is not None and mode in _AI_PROMPTS:
        avoid = " | ".join(previous[:5])
        prompt = _VOICE + " " + _AI_PROMPTS[mode].format(**values)
        if avoid:
            prompt += f" Do not repeat or paraphrase these earlier posts: {avoid}"
        for _ in range(2):
            try:
                yield generate(prompt) or ""
            except Exception:
                return

    templates = _TEMPLATES[mode]
    for offset in range(len(templates)):
        yield templates[(day_index + offset) % len(templates)].format(**values)


def pick_body(
    day_index: int,
    previous: list[str],
    generate: Optional[Callable[[str], Optional[str]]],
    facts: dict[str, Any],
) -> Optional[str]:
    """First safe, fresh Wave text, rotating the style by day; None if nothing qualifies."""
    start = day_index % len(_MODES)
    for mode in _MODES[start:] + _MODES[:start]:
        for candidate in _candidates(mode, generate, facts, previous, day_index):
            body = _clean(candidate)
            if body and _acceptable(body, previous):
                return body
    return None


class HiveChain:
    """The few Hive calls the poster needs (read for history, write to publish)."""

    def __init__(self, account: str, posting_key: Optional[str] = None):
        from beem import Hive

        self.account = account
        self.hive = Hive(node=HIVE_NODES, keys=[posting_key] if posting_key else [])
        self.rpc = self.hive.rpc

    def container(self) -> tuple[str, str]:
        last_error: Optional[Exception] = None
        for host in WAVES_CONTAINER_HOSTS:
            try:
                entries = self.rpc.get_discussions_by_blog({"tag": host, "limit": 20}, api="condenser") or []
            except Exception as exc:
                last_error = exc
                continue
            for entry in entries:
                if (
                    isinstance(entry, dict)
                    and entry.get("author") == host
                    and not entry.get("parent_author")
                    and entry.get("permlink")
                ):
                    return host, str(entry["permlink"])
        raise RuntimeError("No live Waves container was found") from last_error

    def own_waves(self) -> list[dict[str, Any]]:
        """This account's recent Waves, newest first. Raises if history can't be read."""
        entries = self.rpc.get_discussions_by_comments(
            {"start_author": self.account, "limit": HISTORY_SCAN}, api="condenser"
        )
        if not isinstance(entries, list):
            raise RuntimeError("Hive returned no verifiable comment history")
        waves = []
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("author") != self.account:
                continue
            permlink = str(entry.get("permlink", ""))
            if not (permlink.startswith(PERMLINK_PREFIX) or entry.get("parent_author") in WAVES_CONTAINER_HOSTS):
                continue
            created = _parse_time(entry.get("created"))
            if created is None:
                raise RuntimeError(f"Wave {permlink} has no verifiable timestamp")
            waves.append({"permlink": permlink, "body": str(entry.get("body", "")), "created": created})
        return sorted(waves, key=lambda w: w["created"], reverse=True)

    def exists(self, permlink: str) -> Optional[dict[str, Any]]:
        try:
            content = self.rpc.get_content(self.account, permlink)
        except Exception as exc:
            if "does not exist" in str(exc).lower():
                return None
            raise
        if isinstance(content, dict) and content.get("author") == self.account and content.get("permlink") == permlink:
            return {"permlink": permlink, "created": _parse_time(content.get("created"))}
        return None

    def publish(self, permlink: str, parent: tuple[str, str], body: str, tags: list[str]) -> None:
        result = self.hive.post(
            title="",
            body=body,
            author=self.account,
            permlink=permlink,
            reply_identifier=f"{parent[0]}/{parent[1]}",
            tags=tags,
            app="waves",
            self_vote=False,
        )
        if not result:
            raise RuntimeError("Hive returned no result for the Wave")


def _parse_time(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _state_path() -> Path:
    return Path(os.environ.get("HAROLD_WAVES_STATE", "harold_waves_state.json"))


def _load_state() -> dict[str, Any]:
    try:
        return json.loads(_state_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(state: dict[str, Any]) -> None:
    try:
        _state_path().write_text(json.dumps(state, indent=2), encoding="utf-8")
    except OSError:
        pass


def _enabled() -> bool:
    return os.environ.get("HAROLD_WAVES_ENABLED", "true").lower() in {"1", "true", "yes", "on"}


def _result(action: str, reason: str = "", ok: bool = True, done: bool = False, **extra: Any) -> dict[str, Any]:
    return {"ok": ok, "action": action, "reason": reason, "done": done, **extra}


def maybe_post_wave(
    chain: Any = None,
    generate: Optional[Callable[[str], Optional[str]]] = None,
    facts: Optional[dict[str, Any]] = None,
    now: Optional[datetime] = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Post today's Wave if, and only if, Hive confirms there isn't one yet.

    ``done`` in the result means no further attempt is needed today.
    """
    if not _enabled():
        return _result("skipped", "disabled (HAROLD_WAVES_ENABLED)", done=True)
    account = os.environ.get("HIVE_ACCOUNT", "").strip()
    key = os.environ.get("HIVE_POSTING_KEY", "").strip()
    if chain is None:
        if not account or (not key and not dry_run):
            return _result("skipped", "HIVE_ACCOUNT and HIVE_POSTING_KEY are not configured", ok=False)
        try:
            chain = HiveChain(account, key or None)
        except ImportError:
            return _result("skipped", "beem is not installed (pip install beem)", ok=False)
        except Exception as exc:
            return _result("failed", f"could not connect to Hive: {exc}", ok=False)
    if not _POST_LOCK.acquire(blocking=False):
        return _result("skipped", "another Wave check is already running")
    try:
        return _run(chain, generate, facts, now or datetime.now(timezone.utc), dry_run)
    finally:
        _POST_LOCK.release()


def _run(chain: Any, generate: Any, facts: Any, now: datetime, dry_run: bool) -> dict[str, Any]:
    state = _load_state()
    last_local = _parse_time(state.get("last_posted_at"))
    if last_local and now - last_local < MIN_INTERVAL:
        return _result("skipped", "posted recently (local record)", done=True)

    try:
        waves = chain.own_waves()
        intro_exists = chain.exists(INTRO_PERMLINK) is not None
        day = now.strftime("%Y%m%d")
        today_exists = chain.exists(PERMLINK_PREFIX + day) is not None
    except Exception as exc:
        return _result("skipped", f"could not verify Hive history, not posting: {exc}", ok=False)

    latest = waves[0]["created"] if waves else None
    if today_exists or (latest and latest.date() == now.date()):
        return _result("skipped", "already posted today", done=True)
    if latest and now - latest < MIN_INTERVAL:
        return _result("skipped", "last Wave is less than 20 hours old", done=True)

    intro = not intro_exists and not waves
    if intro:
        body, permlink = INTRO_BODY, INTRO_PERMLINK
    else:
        previous = [w["body"] for w in waves if w["body"]]
        facts = facts if facts is not None else gather_facts()
        body = pick_body(now.toordinal(), previous, generate, facts)
        permlink = PERMLINK_PREFIX + day
        if body is None:
            return _result("skipped", "no fresh, safe text to post today", ok=False)

    if dry_run:
        return _result("dry_run", body=body, permlink=permlink, intro=intro)
    tags = [t.strip().lower().replace(" ", "-") for t in os.environ.get("HAROLD_WAVES_TAGS", DEFAULT_TAGS).split(",") if t.strip()]
    try:
        chain.publish(permlink, chain.container(), body, tags)
    except Exception as exc:
        return _result("failed", f"post failed: {exc}", ok=False)

    state.update(last_posted_at=now.isoformat(), last_permlink=permlink, count=int(state.get("count", 0)) + 1)
    _save_state(state)
    return _result("posted", done=True, body=body, permlink=permlink, intro=intro)


def _loop(generate: Optional[Callable[[str], Optional[str]]]) -> None:
    global _WARNED_UNCONFIGURED
    print("[harold-waves] daily Wave poster started.", flush=True)
    done_day: Optional[str] = None
    retry_at = 0.0
    while True:
        try:
            now = datetime.now(timezone.utc)
            try:
                hour = int(os.environ.get("HAROLD_WAVES_HOUR_UTC", "14"))
            except ValueError:
                hour = 14
            today = now.strftime("%Y%m%d")
            if _enabled() and now.hour >= hour and done_day != today and time.time() >= retry_at:
                result = maybe_post_wave(generate=generate)
                if result["action"] == "posted":
                    print(f"[harold-waves] posted {result['permlink']}: {result['body']}", flush=True)
                elif result["action"] == "failed" or (not result["ok"] and "not configured" not in result["reason"]):
                    print(f"[harold-waves] {result['action']}: {result['reason']}", flush=True)
                elif "not configured" in result["reason"] and not _WARNED_UNCONFIGURED:
                    _WARNED_UNCONFIGURED = True
                    print(f"[harold-waves] not posting: {result['reason']}", flush=True)
                if result["done"]:
                    done_day = today
                else:
                    retry_at = time.time() + (6 * 3600 if "not configured" in result["reason"] else 3600)
        except Exception as exc:
            print(f"[harold-waves] loop error: {exc}", flush=True)
        time.sleep(600)


def start_waves_poster(generate: Optional[Callable[[str], Optional[str]]] = None) -> None:
    """Start the daily Wave poster as a daemon thread (once per process)."""
    global _STARTED
    with _STARTED_LOCK:
        if _STARTED:
            return
        _STARTED = True
    threading.Thread(target=_loop, args=(generate,), name="harold-waves", daemon=True).start()
