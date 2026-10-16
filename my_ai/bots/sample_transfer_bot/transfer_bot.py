#!/usr/bin/env python3
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

            print(f"\nPayment received: {amount_val:.3f} {asset_type} from @{sender}")
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
