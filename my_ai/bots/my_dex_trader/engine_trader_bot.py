#!/usr/bin/env python3
"""Hive Engine DEX Trading Bot - three level strategy.

Level 1: micro market maker.  Follows the best bid/ask by one tick, sized at
0.5% of visible book volume, and ratchets each side one tick closer per cycle
without ever letting the buy and sell touch.

Level 2: fixed 1.2% profit maker.  Only places when the spread can carry a
1.2% round trip; otherwise rests a buy/sell pair separated by exactly 1.2%.

Level 3: swing watcher.  Tracks the mid price and reacts to fast shifts.
"""

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

from beem import Hive

ACCOUNT_NAME = os.environ.get("HIVE_ACCOUNT")
ACTIVE_KEY = os.environ.get("HIVE_ACTIVE_KEY")
TARGET_SYMBOLS = [
    s.strip().upper()
    for s in os.environ.get("TARGET_SYMBOLS", os.environ.get("TARGET_SYMBOL", "SWAP.HBD")).split(",")
    if s.strip()
]
TRADE_QUANTITY = float(os.environ.get("TRADE_QUANTITY", "5.0"))
MIN_PROFIT_PCT = float(os.environ.get("MIN_PROFIT_PCT", "1.2"))
SWING_PCT = float(os.environ.get("SWING_PCT", "2.0"))
VOLUME_SHARE = float(os.environ.get("VOLUME_SHARE", "0.005"))
TICK = float(os.environ.get("PRICE_TICK", "0.00000001"))
LEVEL_COOLDOWN = float(os.environ.get("LEVEL_COOLDOWN", "5.0"))

ENGINE_RPC = os.environ.get("ENGINE_RPC", "https://engine.rishipanthee.com/contracts")
HIVE_NODES = [n.strip() for n in os.environ.get("HIVE_NODES", "https://api.hive.blog,https://api.deathwing.me").split(",") if n.strip()]
STATE_PATH = Path(os.environ.get("TRADING_STATE_PATH", str(Path(__file__).with_name("trading_state.json"))))


def query_engine(contract: str, table: str, query: dict, limit: int = 100) -> list:
    payload = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "find",
        "params": {"contract": contract, "table": table, "query": query, "limit": limit},
    }).encode("utf-8")
    req = urllib.request.Request(ENGINE_RPC, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as res:
        return json.loads(res.read().decode("utf-8")).get("result", [])


def get_order_books(symbol: str) -> tuple[float | None, float | None, float]:
    buys = query_engine("market", "buyBook", {"symbol": symbol}, limit=100)
    sells = query_engine("market", "sellBook", {"symbol": symbol}, limit=100)
    highest_bid = float(buys[0]["price"]) if buys else None
    lowest_ask = float(sells[0]["price"]) if sells else None
    total_volume = sum(float(o.get("quantity", 0) or 0) for o in buys + sells)
    return highest_bid, lowest_ask, total_volume


def place_engine_order(hive: Hive, action: str, symbol: str, quantity: float, price: float) -> str:
    payload = {
        "contractName": "market",
        "contractAction": action,
        "contractPayload": {
            "symbol": symbol,
            "quantity": f"{quantity:.8f}",
            "price": f"{price:.8f}",
        },
    }
    tx = hive.custom_json(
        id="ssc-mainnet-hive",
        json_data=payload,
        required_active_auths=[ACCOUNT_NAME],
    )
    return tx.get("trx_id", "")


def load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}


def save_state(state: dict) -> None:
    try:
        STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    except OSError:
        pass


def safe_price(value: float | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def level_quantity(total_volume: float) -> float:
    quantity = total_volume * VOLUME_SHARE
    if quantity <= 0:
        quantity = TRADE_QUANTITY
    return max(0.001, min(quantity, TRADE_QUANTITY if TRADE_QUANTITY > 0 else quantity))


def non_touching(buy_price: float, sell_price: float) -> bool:
    return buy_price + TICK < sell_price


def run_level_one(hive: Hive, symbol: str, bid: float, ask: float, volume: float, state: dict) -> None:
    symbol_state = state.setdefault(symbol, {})
    last_buy = safe_price(symbol_state.get("level1_buy"))
    last_sell = safe_price(symbol_state.get("level1_sell"))

    if last_buy is None:
        buy_price = bid + TICK
    else:
        buy_price = last_buy + TICK
    if last_sell is None:
        sell_price = ask - TICK
    else:
        sell_price = last_sell - TICK

    # Keep the pair valid and never touching.
    if buy_price >= ask - TICK:
        buy_price = bid + TICK
    if sell_price <= buy_price + TICK:
        sell_price = ask - TICK
    if not non_touching(buy_price, sell_price):
        buy_price = bid + TICK
        sell_price = ask - TICK
        if not non_touching(buy_price, sell_price):
            print(f"[{symbol}] Level 1 skipped: book too tight to stay non-touching.")
            return

    quantity = level_quantity(volume)
    print(f"[{symbol}] Level 1 micro maker: buy {quantity:.8f} @ {buy_price:.8f}, sell {quantity:.8f} @ {sell_price:.8f}")
    try:
        tx1 = place_engine_order(hive, "buy", symbol, quantity, buy_price)
        print(f"[{symbol}] Level 1 buy submitted: {tx1}")
        time.sleep(LEVEL_COOLDOWN)
        tx2 = place_engine_order(hive, "sell", symbol, quantity, sell_price)
        print(f"[{symbol}] Level 1 sell submitted: {tx2}")
        symbol_state["level1_buy"] = buy_price
        symbol_state["level1_sell"] = sell_price
    except Exception as exc:
        print(f"[{symbol}] Level 1 failed: {exc}")


def run_level_two(hive: Hive, symbol: str, bid: float, ask: float, volume: float) -> None:
    spread = ((ask - bid) / bid) * 100.0 if bid else 0.0
    quantity = level_quantity(volume)
    if spread >= MIN_PROFIT_PCT:
        buy_price = bid + TICK
        sell_price = buy_price * (1 + MIN_PROFIT_PCT / 100.0)
        if sell_price >= ask:
            sell_price = ask - TICK
        if not non_touching(buy_price, sell_price):
            print(f"[{symbol}] Level 2 skipped: cannot keep 1.2% profit without touching.")
            return
        print(f"[{symbol}] Level 2 profit maker: spread {spread:.2f}% >= {MIN_PROFIT_PCT:.2f}%")
        try:
            tx1 = place_engine_order(hive, "buy", symbol, quantity, buy_price)
            print(f"[{symbol}] Level 2 buy submitted: {tx1}")
            time.sleep(LEVEL_COOLDOWN)
            tx2 = place_engine_order(hive, "sell", symbol, quantity, sell_price)
            print(f"[{symbol}] Level 2 sell submitted: {tx2}")
        except Exception as exc:
            print(f"[{symbol}] Level 2 failed: {exc}")
        return

    # Rest a fixed 1.2% pair around the current bid when the live spread is too small.
    buy_price = bid + TICK
    sell_price = buy_price * (1 + MIN_PROFIT_PCT / 100.0)
    if not non_touching(buy_price, sell_price):
        print(f"[{symbol}] Level 2 skipped: resting 1.2% pair would touch.")
        return
    print(f"[{symbol}] Level 2 resting 1.2% pair: buy {quantity:.8f} @ {buy_price:.8f}, sell {quantity:.8f} @ {sell_price:.8f}")
    try:
        tx1 = place_engine_order(hive, "buy", symbol, quantity, buy_price)
        print(f"[{symbol}] Level 2 buy submitted: {tx1}")
        time.sleep(LEVEL_COOLDOWN)
        tx2 = place_engine_order(hive, "sell", symbol, quantity, sell_price)
        print(f"[{symbol}] Level 2 sell submitted: {tx2}")
    except Exception as exc:
        print(f"[{symbol}] Level 2 failed: {exc}")


def run_level_three(hive: Hive, symbol: str, bid: float, ask: float, volume: float, state: dict) -> None:
    symbol_state = state.setdefault(symbol, {})
    mid = (bid + ask) / 2.0
    last_mid = safe_price(symbol_state.get("last_mid"))
    symbol_state["last_mid"] = mid
    if last_mid is None or last_mid == 0:
        print(f"[{symbol}] Level 3 swing watcher: baseline mid {mid:.8f}")
        return

    change = ((mid - last_mid) / last_mid) * 100.0
    if abs(change) < SWING_PCT:
        print(f"[{symbol}] Level 3 swing watcher: mid moved {change:.2f}% (threshold {SWING_PCT:.2f}%)")
        return

    quantity = level_quantity(volume)
    if change > 0:
        # Upward shift: sell into strength.
        price = bid
        action = "sell"
    else:
        # Downward shift: buy the dip.
        price = ask
        action = "buy"
    print(f"[{symbol}] Level 3 swing watcher: {change:+.2f}% shift, {action} {quantity:.8f} @ {price:.8f}")
    try:
        tx = place_engine_order(hive, action, symbol, quantity, price)
        print(f"[{symbol}] Level 3 {action} submitted: {tx}")
    except Exception as exc:
        print(f"[{symbol}] Level 3 failed: {exc}")


def run_cycle(hive: Hive, state: dict) -> None:
    for symbol in TARGET_SYMBOLS:
        print(f"\n=== {symbol} ===")
        bid, ask, volume = get_order_books(symbol)
        if bid is None or ask is None:
            print(f"[{symbol}] Order book is empty on one or both sides.")
            continue
        print(f"Best Bid: {bid:.8f} | Best Ask: {ask:.8f} | Visible volume: {volume:.8f}")

        run_level_one(hive, symbol, bid, ask, volume, state)
        time.sleep(LEVEL_COOLDOWN)
        run_level_two(hive, symbol, bid, ask, volume)
        time.sleep(LEVEL_COOLDOWN)
        run_level_three(hive, symbol, bid, ask, volume, state)
        save_state(state)


def main() -> None:
    if not ACCOUNT_NAME or not ACTIVE_KEY:
        print("Error: Set HIVE_ACCOUNT and HIVE_ACTIVE_KEY in your environment to trade on Hive Engine.")
        sys.exit(1)
    if not TARGET_SYMBOLS:
        print("Error: TARGET_SYMBOLS is empty.")
        sys.exit(1)

    hive = Hive(node=HIVE_NODES, keys=[ACTIVE_KEY])
    print(f"Three-level Hive Engine trader initialized for @{ACCOUNT_NAME}: {', '.join(TARGET_SYMBOLS)}")
    state = load_state()

    while True:
        try:
            run_cycle(hive, state)
            time.sleep(30)
        except KeyboardInterrupt:
            print("\nTrading bot stopped.")
            save_state(state)
            break
        except Exception as exc:
            print(f"Error during trading cycle: {exc}")
            time.sleep(15)


if __name__ == "__main__":
    main()
