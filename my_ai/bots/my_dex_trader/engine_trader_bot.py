#!/usr/bin/env python3
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
    print(f"\nChecking market for {TARGET_SYMBOL}...")
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
            print("\nTrading bot stopped.")
            break
        except Exception as exc:
            print(f"Error during trading cycle: {exc}")
            time.sleep(15)

if __name__ == "__main__":
    main()
