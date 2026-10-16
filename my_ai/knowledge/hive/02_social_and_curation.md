# Hive Social Bots: Posting, Voting, and Curation Guide

Frontends like Ecency, PeakD, and Hive.blog are graphical interfaces that read from and write to the exact same decentralized Hive blockchain. Any post or vote created through a bot script is immediately visible across Ecency, PeakD, and Hive.blog.

## 1. Creating Posts and Comments

On Hive, top-level blog posts and replies use the `comment` operation. A top-level post sets `parent_author=""` and `parent_permlink="main-tag"`. A comment sets `parent_author="target_author"` and `parent_permlink="target_permlink"`.

### Posting with Python (`beem`)

```python
from beem import Hive
import os

account_name = os.environ.get("HIVE_ACCOUNT")
posting_key = os.environ.get("HIVE_POSTING_KEY")

hive = Hive(node=["https://api.hive.blog", "https://api.deathwing.me"], keys=[posting_key])

title = "Automated Daily Report"
body = "## Daily Update\n\nHere are the latest automated statistics from the bot."
tags = ["hive-engine", "programming", "python", "automation"]
permlink = "automated-daily-report-2026-10-11"

# Post operation - visible on Ecency, PeakD, and Hive.blog
hive.post(
    title=title,
    body=body,
    author=account_name,
    permlink=permlink,
    tags=tags,
    self_vote=False,
    json_metadata={"app": "pocket-ai/1.0", "format": "markdown", "tags": tags}
)
```

## 2. Upvoting and Curation Bots

Upvoting on Hive rewards authors and curators with HIVE and HBD from the daily reward pool. Upvoting requires only the **Posting Key**.

### Key Rules for Curation Bots

1. **Voting Power (VP)**:
   - Every account has Voting Power (0% to 100%).
   - Each 100% upvote consumes approximately 2% of your current voting power.
   - Voting power regenerates linearly at 20% per day (about 0.83% per hour).
   - Bots should monitor VP and pause voting when VP drops below a threshold (typically 80%) to maximize return.

2. **Curation Reward Window**:
   - Voting between 0 and 5 minutes after a post is published shares curation rewards with the author.
   - At exactly 5 minutes (300 seconds) or later, 100% of the curation reward goes to the curator. Optimal curation bots wait 5 minutes before voting.

### Curation Upvote Script Example

```python
from beem import Hive
from beem.account import Account
from beem.comment import Comment
import os

account_name = os.environ.get("HIVE_ACCOUNT")
posting_key = os.environ.get("HIVE_POSTING_KEY")

hive = Hive(node=["https://api.hive.blog"], keys=[posting_key])
acc = Account(account_name, blockchain_instance=hive)

# Check Voting Power
vp = acc.get_voting_power()
print(f"Current Voting Power: {vp:.2f}%")

if vp >= 80.0:
    author = "alice"
    permlink = "my-latest-post"
    post = Comment(f"@{author}/{permlink}", blockchain_instance=hive)
    # Vote weight: 100.0 is 100%, 50.0 is 50%
    post.upvote(weight=100.0, voter=account_name)
    print(f"Upvoted @{author}/{permlink} with 100% weight")
```

## 3. Streaming the Blockchain for New Posts

A curation bot can listen to all new posts in real time using `hive.blockchain_stream()`:

```python
from beem.blockchain import Blockchain
from beem import Hive
import time

hive = Hive(node=["https://api.hive.blog"])
chain = Blockchain(blockchain_instance=hive)

whitelist = {"alice", "bob", "cryptonews"}

print("Listening for posts by whitelist authors...")
for op in chain.stream(opNames=["comment"]):
    # Only top-level posts have empty parent_author
    if op.get("parent_author") == "" and op.get("author") in whitelist:
        print(f"Detected post by @{op['author']}: {op['title']}")
        # Schedule vote 5 minutes later for optimal curation
```

