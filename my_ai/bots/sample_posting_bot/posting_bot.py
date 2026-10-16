#!/usr/bin/env python3
"""Hive Blog Publisher Bot.

Publishes formatted markdown posts to the Hive blockchain.
Posts appear automatically across all frontends (Ecency, PeakD, Hive.blog).
"""

from datetime import datetime
import os
import re
import sys
from beem import Hive

ACCOUNT_NAME = os.environ.get("HIVE_ACCOUNT")
POSTING_KEY = os.environ.get("HIVE_POSTING_KEY")

NODES = [
    "https://api.hive.blog",
    "https://api.deathwing.me",
    "https://hive-api.arcange.eu"
]

def make_permlink(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40]
    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    return f"{slug}-{timestamp}"

def publish_post(title: str, body: str, tags: list[str]) -> str:
    if not ACCOUNT_NAME or not POSTING_KEY:
        raise ValueError("Set HIVE_ACCOUNT and HIVE_POSTING_KEY in your environment.")

    hive = Hive(node=NODES, keys=[POSTING_KEY])
    permlink = make_permlink(title)
    clean_tags = [t.lower().replace(" ", "-") for t in tags if t]

    metadata = {
        "app": "pocket-ai/1.0",
        "format": "markdown",
        "tags": clean_tags
    }

    tx = hive.post(
        title=title,
        body=body,
        author=ACCOUNT_NAME,
        permlink=permlink,
        tags=clean_tags,
        self_vote=False,
        json_metadata=metadata
    )
    return f"https://peakd.com/@{ACCOUNT_NAME}/{permlink}"

def main() -> None:
    title = os.environ.get("POST_TITLE", "Automated Daily Update from Bot")
    body = os.environ.get("POST_BODY", "## Automated Update\n\nThis post was published automatically via Pocket AI.")
    tags = [t.strip() for t in os.environ.get("POST_TAGS", "hive,technology,programming,automation").split(",")]

    print(f"Publishing post as @{ACCOUNT_NAME}...")
    url = publish_post(title, body, tags)
    print(f"Post published successfully!\nView it at: {url}")

if __name__ == "__main__":
    main()
