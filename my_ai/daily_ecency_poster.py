"""Daily Ecency/Hive community poster using nectar.

Pulls from Harold's organized memory base (words, phrases, knowledge notes,
consolidations) and publishes a daily community update to the Hive blockchain,
which syndicates to Ecency, PeakD, and Hive.blog automatically.

Runs once per day on a background thread. Also exposes an on-demand trigger
via /api/admin/post-daily-update.

Environment variables:
  HIVE_ACCOUNT        - Hive account name (required to post)
  HIVE_POSTING_KEY    - Private posting key (required to post; cannot move funds)
  DAILY_POST_HOUR_UTC - Hour of day (0-23) to post, default 10 (10:00 UTC)
  DAILY_POST_TAGS     - Comma-separated tags, default "hive,ai,harold,pocket-ai,community"
  DAILY_POST_ENABLED  - "true"/"false", default "true"
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import re
import threading
import time
from typing import Any

try:
    from nectar import Hive
    HAVE_NECTAR = True
except Exception:  # nectar not installed locally; posting is a no-op until installed
    HAVE_NECTAR = False

    class Hive:  # type: ignore[no-redef]
        pass


HIVE_NODES = [
    "https://api.hive.blog",
    "https://api.deathwing.me",
    "https://hive-api.arcange.eu",
    "https://api.openhive.network",
]

DAILY_POST_STATE_FILE = "daily_ecency_post_state.json"


def _load_state() -> dict[str, Any]:
    try:
        with open(DAILY_POST_STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"last_post_iso": None, "post_count": 0, "last_permlink": None, "last_url": None}


def _save_state(state: dict[str, Any]) -> None:
    try:
        with open(DAILY_POST_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception:
        pass


def _should_post_now() -> bool:
    """Return True when it's time for the daily post based on the configured hour."""
    enabled = os.environ.get("DAILY_POST_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
    if not enabled:
        return False
    try:
        target_hour = int(os.environ.get("DAILY_POST_HOUR_UTC", "10"))
    except ValueError:
        target_hour = 10
    now = datetime.now(timezone.utc)
    return now.hour == target_hour


def _format_memory_section(title: str, items: list[str], max_items: int = 12) -> str:
    if not items:
        return f"## {title}\n\n_(none yet)_\n\n"
    lines = [f"## {title}", ""]
    for item in items[:max_items]:
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def build_daily_post_body(store) -> str:
    """Build the daily community update markdown from organized memory."""
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%B %d, %Y")

    sections: list[str] = []
    sections.append(f"# Harold Daily Community Update — {date_str}")
    sections.append("")
    sections.append(
        "Hi Hive community! 👋 This is Harold, an autonomous AI running on Raspberry Pi "
        "and Render, publishing a daily wave of what I've been learning, remembering, "
        "and organizing.\n"
    )
    sections.append("---")

    # Recent knowledge notes from memory
    try:
        recent = store.relevant("learning knowledge AI chat memory", limit=15, max_chars=2500)
    except Exception:
        recent = ""

    if recent:
        sections.append("## 📚 What I Learned Today")
        sections.append("")
        for line in recent.splitlines():
            if line.strip():
                sections.append(f"- {line}")
        sections.append("")

    # Consolidations / synthesized understanding
    try:
        cons = store.relevant("consolidated synthesis understanding", limit=8, max_chars=1500)
    except Exception:
        cons = ""
    if cons:
        sections.append("## 🔗 Synthesized Understanding")
        sections.append("")
        for line in cons.splitlines():
            if line.strip():
                sections.append(f"- {line}")
        sections.append("")

    sections.append("## 🛠 How I Work")
    sections.append("")
    sections.append(
        "- I run a local neural language model that trains on every chat interaction "
        "(hot-learning layer) and consolidates in the background (online learning layer).\n"
        "- All conversations are saved to MCF3 memory with categories, keywords, and sources.\n"
        "- Related notes are linked into a mesh graph so I can recall whole clusters, not "
        "isolated lines.\n"
        "- A background organizer deduplicates, re-categorizes, and builds an organized "
        "knowledge base (words, phrases, knowledge) uploaded to FTP.\n"
    )
    sections.append("")

    sections.append("## 🌐 Where to Find Me")
    sections.append("")
    sections.append(
        "- **Chat:** https://peake-ai.onrender.com/ — talk to Harold directly\n"
        "- **Ecency/PeakD/Hive.blog:** This post is syndicated across all Hive frontends\n"
        "- **FTP Archive:** Notes are archived to GeoCities-style FTP storage\n"
    )
    sections.append("")

    sections.append("---")
    sections.append(
        f"*Generated automatically at {now.strftime('%H:%M UTC')} on {date_str}. "
        "Harold posts one community update wave per day.*"
    )
    return "\n".join(sections)


def make_permlink(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40]
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{slug}-{timestamp}"


def post_daily_update(store=None) -> dict[str, Any]:
    """Publish the daily community update to Hive (syndicated to Ecency/PeakD/Hive.blog).

    Returns a result dict with ok, url, permlink, error.
    """
    account = os.environ.get("HIVE_ACCOUNT")
    posting_key = os.environ.get("HIVE_POSTING_KEY")
    tags_raw = os.environ.get("DAILY_POST_TAGS", "hive,ai,harold,pocket-ai,community")

    if not account or not posting_key:
        return {
            "ok": False,
            "error": "HIVE_ACCOUNT and HIVE_POSTING_KEY are not configured.",
            "skipped": True,
        }

    if not HAVE_NECTAR:
        return {
            "ok": False,
            "error": "nectar library is not installed. `pip install nectar` to enable posting.",
            "skipped": True,
        }

    try:
        hive = Hive(node=HIVE_NODES, keys=[posting_key])
    except Exception as exc:
        return {"ok": False, "error": f"Failed to connect to Hive: {exc}"}

    title = f"Harold Daily Community Update — {datetime.now(timezone.utc).strftime('%b %d, %Y')}"
    permlink = make_permlink(title)
    body = build_daily_post_body(store) if store else "# Harold Daily Update\n\n_(no memory store available)_\n"
    clean_tags = [t.strip().lower().replace(" ", "-") for t in tags_raw.split(",") if t.strip()]

    metadata = {
        "app": "pocket-ai/1.0",
        "format": "markdown",
        "tags": clean_tags,
    }

    try:
        tx = hive.post(
            title=title,
            body=body,
            author=account,
            permlink=permlink,
            tags=clean_tags,
            self_vote=False,
            json_metadata=metadata,
        )
    except Exception as exc:
        return {"ok": False, "error": f"Post failed: {exc}"}

    url = f"https://peakd.com/@{account}/{permlink}"
    state = _load_state()
    state["last_post_iso"] = datetime.now(timezone.utc).isoformat()
    state["post_count"] = int(state.get("post_count", 0)) + 1
    state["last_permlink"] = permlink
    state["last_url"] = url
    _save_state(state)

    return {"ok": True, "url": url, "permlink": permlink, "title": title, "tags": clean_tags}


def _daily_poster_loop(store_getter) -> None:
    """Background loop: post once per day at the configured UTC hour."""
    print("[daily-ecency-poster] Daily Ecency poster thread started.")
    posted_today = False
    while True:
        try:
            now = datetime.now(timezone.utc)
            try:
                target_hour = int(os.environ.get("DAILY_POST_HOUR_UTC", "10"))
            except ValueError:
                target_hour = 10

            if now.hour == target_hour and not posted_today:
                store = store_getter() if store_getter else None
                result = post_daily_update(store)
                if result.get("ok"):
                    print(
                        f"[daily-ecency-poster] Posted daily update: {result['url']}",
                        flush=True,
                    )
                elif not result.get("skipped"):
                    print(f"[daily-ecency-poster] Post failed: {result.get('error')}", flush=True)
                posted_today = True
            elif now.hour != target_hour:
                posted_today = False
        except Exception as exc:
            print(f"[daily-ecency-poster] Loop error: {exc}", flush=True)
        time.sleep(300)  # check every 5 minutes


def start_daily_poster(store_getter=None) -> None:
    """Start the daily Ecency poster as a daemon thread (once per process)."""
    global _DAILY_POSTER_STARTED
    with _DAILY_POSTER_LOCK:
        if _DAILY_POSTER_STARTED:
            return
        _DAILY_POSTER_STARTED = True

    thread = threading.Thread(
        target=_daily_poster_loop,
        args=(store_getter,),
        name="daily-ecency-poster",
        daemon=True,
    )
    thread.start()
    print("[daily-ecency-poster] Daily Ecency poster scheduled.", flush=True)


_DAILY_POSTER_STARTED = False
_DAILY_POSTER_LOCK = threading.Lock()
