#!/usr/bin/env python3
"""Hive Curation and Auto-Voting Bot.

Monitors the Hive blockchain stream for new posts by whitelisted authors or tags,
checks account Voting Power (VP), waits for the 5-minute curation window, and upvotes.
"""

import os
import sys
import time
from beem import Hive
from beem.account import Account
from beem.blockchain import Blockchain
from beem.comment import Comment

ACCOUNT_NAME = os.environ.get("HIVE_ACCOUNT")
POSTING_KEY = os.environ.get("HIVE_POSTING_KEY")
MIN_VOTING_POWER = float(os.environ.get("MIN_VOTING_POWER", "80.0"))
VOTE_WEIGHT = float(os.environ.get("VOTE_WEIGHT", "100.0"))
CURATION_DELAY_SECONDS = int(os.environ.get("CURATION_DELAY_SECONDS", "300"))  # 5 minutes

WHITELIST_AUTHORS = set(filter(None, [
    a.strip().lstrip("@") for a in os.environ.get("WHITELIST_AUTHORS", "alice,bob").split(",")
]))

NODES = [
    "https://api.hive.blog",
    "https://api.deathwing.me",
    "https://hive-api.arcange.eu",
    "https://api.openhive.network"
]

def main() -> None:
    if not ACCOUNT_NAME or not POSTING_KEY:
        print("Error: Set HIVE_ACCOUNT and HIVE_POSTING_KEY in your .env or environment.")
        sys.exit(1)

    print(f"Starting Curation Bot for @{ACCOUNT_NAME}...")
    print(f"Target authors: {', '.join(sorted(WHITELIST_AUTHORS))}")
    print(f"Min Voting Power: {MIN_VOTING_POWER}%, Vote Weight: {VOTE_WEIGHT}%")

    hive = Hive(node=NODES, keys=[POSTING_KEY], num_retries=5)
    account = Account(ACCOUNT_NAME, blockchain_instance=hive)
    chain = Blockchain(blockchain_instance=hive)

    current_vp = account.get_voting_power()
    print(f"Initial Voting Power: {current_vp:.2f}%")

    for op in chain.stream(opNames=["comment"]):
        if op.get("parent_author") == "":
            author = op.get("author")
            permlink = op.get("permlink")

            if author in WHITELIST_AUTHORS:
                title = op.get("title", "(no title)")
                print(f"\nDetected post by @{author}: {title!r}")

                # Refresh and check voting power
                account.refresh()
                vp = account.get_voting_power()
                if vp < MIN_VOTING_POWER:
                    print(f"Skipping: Voting power {vp:.2f}% is below threshold {MIN_VOTING_POWER}%.")
                    continue

                if CURATION_DELAY_SECONDS > 0:
                    print(f"Waiting {CURATION_DELAY_SECONDS}s for optimal curation rewards...")
                    time.sleep(CURATION_DELAY_SECONDS)

                try:
                    post = Comment(f"@{author}/{permlink}", blockchain_instance=hive)
                    # Check if already voted
                    if not any(v.get("voter") == ACCOUNT_NAME for v in post.get_votes()):
                        post.upvote(weight=VOTE_WEIGHT, voter=ACCOUNT_NAME)
                        print(f"Successfully upvoted @{author}/{permlink} at {VOTE_WEIGHT}%!")
                    else:
                        print(f"Already voted on @{author}/{permlink}.")
                except Exception as exc:
                    print(f"Failed to vote on @{author}/{permlink}: {exc}")

if __name__ == "__main__":
    main()
