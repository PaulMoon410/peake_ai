# dust_collector.py

import time
from place_order import get_balance, place_order, HIVE_ACCOUNT
from fetch_market import get_orderbook_top

# Configuration
DUST_THRESHOLD = 0.001   # Minimum amount to sell
PEAKECOIN_SYMBOL = "SWAP.PEAKECOIN"

def get_all_balances(account_name):
    """Fetch all token balances except PeakeCoin."""
    payload = {
        "jsonrpc": "2.0",
        "method": "find",
        "params": {
            "contract": "tokens",
            "table": "balances",
            "query": {"account": account_name},
            "limit": 1000
        },
        "id": 1
    }
    response = requests.post("https://api.hive-engine.com/rpc/contracts", json=payload)
    if response.status_code == 200:
        return response.json().get("result", [])
    return []

def sell_token(token, amount):
    """Sell a token for SWAP.HIVE at the highest bid."""
    orderbook = get_orderbook_top(token)
    if orderbook and orderbook["highestBid"] > 0:
        sell_price = orderbook["highestBid"]
        print(f"⚡ Selling {amount} {token} at {sell_price}")
        success = place_order(HIVE_ACCOUNT, token, sell_price, amount, "sell")
        return success
    else:
        print(f"⚠️ No buyers for {token}. Skipping.")
        return False

def buy_peakecoin():
    """Buy as much PeakeCoin as possible with SWAP.HIVE."""
    hive_balance = get_balance(HIVE_ACCOUNT, "SWAP.HIVE")
    if hive_balance > DUST_THRESHOLD:
        orderbook = get_orderbook_top(PEAKECOIN_SYMBOL)
        if orderbook and orderbook["lowestAsk"] > 0:
            buy_price = orderbook["lowestAsk"]
            print(f"⚡ Buying {hive_balance} worth of {PEAKECOIN_SYMBOL} at {buy_price}")
            place_order(HIVE_ACCOUNT, PEAKECOIN_SYMBOL, buy_price, hive_balance, "buy")
        else:
            print("⚠️ No PeakeCoin available to buy.")
    else:
        print("⚠️ Not enough SWAP.HIVE to buy PeakeCoin.")

def dust_collector():
    """Main Dust Collection Process"""
    print("🔵 Starting Dust Collector...")
    balances = get_all_balances(HIVE_ACCOUNT)

    for token_info in balances:
        token = token_info["symbol"]
        balance = float(token_info["balance"])

        if token != PEAKECOIN_SYMBOL and balance > DUST_THRESHOLD:
            print(f"🔹 Processing {token} balance: {balance}")
            sold = sell_token(token, balance)
            if sold:
                time.sleep(10)  # Wait a bit for transaction to settle
                buy_peakecoin()
                time.sleep(5)

    print("✅ Dust collection complete!")

if __name__ == "__main__":
    dust_collector()
