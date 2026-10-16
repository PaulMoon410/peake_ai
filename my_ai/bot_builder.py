#!/usr/bin/env python3
"""Hive Blockchain and Hive Engine Bot Generator for Pocket AI.

Scaffolds standalone, ready-to-run bot scripts for:
1. curation      - Auto-upvoting bot for PeakD/Ecency with voting power and delay controls
2. posting        - Automated markdown blog publisher for Ecency, PeakD, and Hive.blog
3. transfers      - Payment/deposit listener and automated transfer bot
4. engine_trader  - Hive Engine DEX limit order and spread trading bot
"""

from __future__ import annotations

import os
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parent
BOTS_DIR = ROOT / "bots"


TEMPLATES: dict[str, dict[str, str]] = {
    "curation": {
        "description": "Auto-upvoting and curation bot for PeakD, Ecency, and Hive.blog",
        "key_required": "Posting Key",
        "filename": "curation_bot.py",
        "code": '''#!/usr/bin/env python3
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
                print(f"\\nDetected post by @{author}: {title!r}")

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
''',
        "env_example": '''# Hive Account credentials (Posting Key only - cannot move funds)
HIVE_ACCOUNT=your_hive_username
HIVE_POSTING_KEY=5K...your_private_posting_key

# Curation rules
WHITELIST_AUTHORS=author1,author2,author3
MIN_VOTING_POWER=80.0
VOTE_WEIGHT=100.0
CURATION_DELAY_SECONDS=300
''',
    },
    "posting": {
        "description": "Automated publisher for Ecency, PeakD, and Hive.blog",
        "key_required": "Posting Key",
        "filename": "posting_bot.py",
        "code": '''#!/usr/bin/env python3
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
    body = os.environ.get("POST_BODY", "## Automated Update\\n\\nThis post was published automatically via Pocket AI.")
    tags = [t.strip() for t in os.environ.get("POST_TAGS", "hive,technology,programming,automation").split(",")]

    print(f"Publishing post as @{ACCOUNT_NAME}...")
    url = publish_post(title, body, tags)
    print(f"Post published successfully!\\nView it at: {url}")

if __name__ == "__main__":
    main()
''',
        "env_example": '''# Hive Account credentials (Posting Key only)
HIVE_ACCOUNT=your_hive_username
HIVE_POSTING_KEY=5K...your_private_posting_key

# Post configuration
POST_TITLE=My Automated Daily Report
POST_TAGS=hive,programming,python,automation
''',
    },
    "transfers": {
        "description": "Payment/deposit watcher and automated transfer bot",
        "key_required": "Active Key",
        "filename": "transfer_bot.py",
        "code": '''#!/usr/bin/env python3
"""Hive Payment and Deposit Listener Bot.

Streams incoming transfers, parses order memos, and executes automated transactions.
Requires Active Key for sending transfers.
"""

import os
import sys
from beem import Hive
from beem.account import Account
from beem.blockchain import Blockchain

ACCOUNT_NAME = os.environ.get("HIVE_ACCOUNT")
ACTIVE_KEY = os.environ.get("HIVE_ACTIVE_KEY")

NODES = [
    "https://api.hive.blog",
    "https://api.deathwing.me",
    "https://hive-api.arcange.eu"
]

def send_transfer(hive: Hive, to_account: str, amount: float, asset: str, memo: str) -> str:
    """Send HIVE or HBD with exact 3-decimal precision."""
    acc = Account(ACCOUNT_NAME, blockchain_instance=hive)
    tx = acc.transfer(to=to_account, amount=amount, asset=asset, memo=memo)
    return tx.get("trx_id", "")

def listen_for_transfers(hive: Hive) -> None:
    chain = Blockchain(blockchain_instance=hive)
    print(f"Listening for incoming transfers to @{ACCOUNT_NAME}...")

    for op in chain.stream(opNames=["transfer"]):
        if op.get("to") == ACCOUNT_NAME:
            sender = op.get("from")
            amount_str = op.get("amount")  # e.g. "1.500 HBD"
            memo = op.get("memo", "").strip()

            parts = amount_str.split()
            amount_val = float(parts[0])
            asset_type = parts[1]

            print(f"\\nPayment received: {amount_val:.3f} {asset_type} from @{sender}")
            print(f"Memo: {memo!r}")

            # Example: Automated receipt or refund
            if memo.startswith("buy:"):
                item = memo.split(":", 1)[1]
                print(f"Order confirmed: User @{sender} purchased {item!r}")
            elif memo == "ping":
                print(f"Sending automated pong reply to @{sender}...")
                send_transfer(hive, sender, 0.001, "HIVE", "pong! payment verified")

def main() -> None:
    if not ACCOUNT_NAME:
        print("Error: Set HIVE_ACCOUNT in your environment.")
        sys.exit(1)

    keys = [ACTIVE_KEY] if ACTIVE_KEY else []
    hive = Hive(node=NODES, keys=keys, num_retries=5)

    if ACTIVE_KEY:
        print("Active Key loaded: Automated transfers enabled.")
    else:
        print("Warning: No Active Key provided. Running in read-only watcher mode.")

    listen_for_transfers(hive)

if __name__ == "__main__":
    main()
''',
        "env_example": '''# Hive Account credentials (Active Key required to send transfers)
HIVE_ACCOUNT=your_hive_username
HIVE_ACTIVE_KEY=5J...your_private_active_key
''',
    },
    "engine_trader": {
        "description": "Hive Engine DEX limit order and spread trading bot",
        "key_required": "Active Key",
        "filename": "engine_trader_bot.py",
        "code": '''#!/usr/bin/env python3
"""Hive Engine DEX Trading Bot.

Queries order books and token balances via Hive Engine RPC, calculates market spread,
and places limit buy/sell orders via Hive custom_json operations.
Requires Active Key to place orders on Layer 2.
"""

import json
import os
import sys
import time
import urllib.request
from beem import Hive

ACCOUNT_NAME = os.environ.get("HIVE_ACCOUNT")
ACTIVE_KEY = os.environ.get("HIVE_ACTIVE_KEY")
TARGET_SYMBOL = os.environ.get("TARGET_SYMBOL", "LEO").upper()
TRADE_QUANTITY = float(os.environ.get("TRADE_QUANTITY", "5.0"))
MIN_SPREAD_PCT = float(os.environ.get("MIN_SPREAD_PCT", "1.5"))  # Minimum 1.5% profit spread

ENGINE_RPC = "https://engine.rishipanthee.com/contracts"
HIVE_NODES = ["https://api.hive.blog", "https://api.deathwing.me"]

def query_engine(contract: str, table: str, query: dict, limit: int = 10) -> list:
    payload = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "find",
        "params": {
            "contract": contract,
            "table": table,
            "query": query,
            "limit": limit
        }
    }).encode("utf-8")
    req = urllib.request.Request(ENGINE_RPC, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as res:
        return json.loads(res.read().decode("utf-8")).get("result", [])

def get_order_books(symbol: str) -> tuple[float | None, float | None]:
    buys = query_engine("market", "buyBook", {"symbol": symbol}, limit=1)
    sells = query_engine("market", "sellBook", {"symbol": symbol}, limit=1)
    highest_bid = float(buys[0]["price"]) if buys else None
    lowest_ask = float(sells[0]["price"]) if sells else None
    return highest_bid, lowest_ask

def place_engine_order(hive: Hive, action: str, symbol: str, quantity: float, price: float) -> str:
    """action: 'buy' or 'sell'"""
    payload = {
        "contractName": "market",
        "contractAction": action,
        "contractPayload": {
            "symbol": symbol,
            "quantity": f"{quantity:.8f}",
            "price": f"{price:.8f}"
        }
    }
    tx = hive.custom_json(
        id="ssc-mainnet-hive",
        json_data=payload,
        required_active_auths=[ACCOUNT_NAME]
    )
    return tx.get("trx_id", "")

def run_trading_cycle(hive: Hive) -> None:
    print(f"\\nChecking market for {TARGET_SYMBOL}...")
    bid, ask = get_order_books(TARGET_SYMBOL)

    if bid is None or ask is None:
        print("Order book is empty on one or both sides.")
        return

    spread = ((ask - bid) / bid) * 100.0
    print(f"Best Bid: {bid:.8f} SWAP.HIVE | Best Ask: {ask:.8f} SWAP.HIVE")
    print(f"Current Spread: {spread:.2f}% (Target min spread: {MIN_SPREAD_PCT}%)")

    if spread >= MIN_SPREAD_PCT:
        my_buy_price = bid + 0.00000001
        my_sell_price = ask - 0.00000001
        print(f"Profitable spread opportunity found!")
        print(f"Placing Limit Buy at {my_buy_price:.8f} and Limit Sell at {my_sell_price:.8f}")

        try:
            tx1 = place_engine_order(hive, "buy", TARGET_SYMBOL, TRADE_QUANTITY, my_buy_price)
            print(f"Buy Order submitted: TX {tx1}")
            time.sleep(3)  # Wait 1 block
            tx2 = place_engine_order(hive, "sell", TARGET_SYMBOL, TRADE_QUANTITY, my_sell_price)
            print(f"Sell Order submitted: TX {tx2}")
        except Exception as exc:
            print(f"Order placement failed: {exc}")
    else:
        print("Spread is too tight for market making. Waiting for next cycle.")

def main() -> None:
    if not ACCOUNT_NAME or not ACTIVE_KEY:
        print("Error: Set HIVE_ACCOUNT and HIVE_ACTIVE_KEY in your environment to trade on Hive Engine.")
        sys.exit(1)

    hive = Hive(node=HIVE_NODES, keys=[ACTIVE_KEY])
    print(f"Hive Engine Trader initialized for @{ACCOUNT_NAME} on {TARGET_SYMBOL}")

    while True:
        try:
            run_trading_cycle(hive)
            time.sleep(30)  # Check market every 30 seconds
        except KeyboardInterrupt:
            print("\\nTrading bot stopped.")
            break
        except Exception as exc:
            print(f"Error during trading cycle: {exc}")
            time.sleep(15)

if __name__ == "__main__":
    main()
''',
        "env_example": '''# Hive Account credentials (Active Key required for Layer 2 smart contracts)
HIVE_ACCOUNT=your_hive_username
HIVE_ACTIVE_KEY=5J...your_private_active_key

# Trading parameters
TARGET_SYMBOL=LEO
TRADE_QUANTITY=5.0
MIN_SPREAD_PCT=1.5
''',
    }
}


def list_templates() -> list[dict[str, str]]:
    return [
        {
            "type": key,
            "description": data["description"],
            "key_required": data["key_required"],
            "filename": data["filename"],
        }
        for key, data in TEMPLATES.items()
    ]


def generate_bot(bot_type: str, bot_name: str, target_dir: Path | None = None) -> Path:
    bot_type = bot_type.lower().strip()
    if bot_type not in TEMPLATES:
        raise ValueError(f"Unknown bot type: {bot_type!r}. Available types: {', '.join(TEMPLATES.keys())}")

    safe_name = re.sub(r"[^a-zA-Z0-9_\-]+", "_", bot_name.strip()).strip("_") or f"hive_{bot_type}_bot"
    dest = (target_dir or BOTS_DIR) / safe_name
    dest.mkdir(parents=True, exist_ok=True)

    template = TEMPLATES[bot_type]

    # Write main bot code
    code_file = dest / template["filename"]
    code_file.write_text(template["code"].lstrip(), encoding="utf-8")
    code_file.chmod(0o755)

    # Write .env.example
    env_file = dest / ".env.example"
    env_file.write_text(template["env_example"].lstrip(), encoding="utf-8")

    # Write requirements.txt
    req_file = dest / "requirements.txt"
    req_file.write_text("beem>=0.24.26\n", encoding="utf-8")

    # Write README.md
    readme_file = dest / "README.md"
    readme_content = f"""# {safe_name.replace('_', ' ').title()}

{template['description']}

## Requirements

Requires Python 3.9+ and `beem`:

```sh
pip install -r requirements.txt
```

## Setup

1. Copy `.env.example` to `.env`:
   ```sh
   cp .env.example .env
   ```
2. Fill in your Hive account name and private **{template['key_required']}**.
3. Run the bot:
   ```sh
   python3 {template['filename']}
   ```

## Security Note

- **{template['key_required']}**: Always keep private keys secret. Never commit `.env` to git repositories.
"""
    readme_file.write_text(readme_content, encoding="utf-8")

    return dest


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "list":
        for t in list_templates():
            print(f"- {t['type']:15} [{t['key_required']:12}] {t['description']}")
    elif len(sys.argv) >= 3 and sys.argv[1] == "create":
        b_type, b_name = sys.argv[2], sys.argv[3]
        out = generate_bot(b_type, b_name)
        print(f"Created {b_type} bot in: {out}")
    else:
        print("Usage:")
        print("  python3 bot_builder.py list")
        print("  python3 bot_builder.py create <curation|posting|transfers|engine_trader> <bot_name>")

