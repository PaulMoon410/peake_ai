# Hive Engine Trading Bots and Smart Contracts Guide

Hive Engine is the Layer 2 sidechain for custom fungible tokens, non-fungible tokens (NFTs), and decentralized exchange (DEX) smart contracts on Hive. Popular tokens include `SWAP.HIVE`, `LEO`, `DEC`, `SPS`, `POB`, and `CENT`.

## 1. How Hive Engine Works

Hive Engine operations are broadcast to the Hive blockchain as Layer 1 `custom_json` transactions with the identifier `id: "ssc-mainnet-hive"`. Hive Engine witness nodes replay these custom_json transactions to maintain sidechain state.

Because trading moves valuable token balances, Hive Engine trading operations require the **Active Key** and must specify `required_active_auths=[account_name]`.

## 2. Querying Hive Engine (Zero Dependencies)

You can inspect balances, order books, and trade history using standard HTTP requests to Hive Engine RPC nodes:

- Nodes:
  - `https://engine.rishipanthee.com/contracts`
  - `https://api.hive-engine.com/rpc/contracts`
  - `https://ha.herpc.dtools.dev/contracts`

### Fetching Order Book & Balances with Python

```python
import json
import urllib.request

RPC_URL = "https://engine.rishipanthee.com/contracts"

def query_hive_engine(contract: str, table: str, query: dict, limit: int = 20) -> list:
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
    req = urllib.request.Request(RPC_URL, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as res:
        data = json.loads(res.read().decode("utf-8"))
        return data.get("result", [])

# 1. Fetch user's token balance
balances = query_hive_engine("tokens", "balances", {"account": "your_account", "symbol": "LEO"})
print("Balance:", balances)

# 2. Fetch Buy Orders (Highest bid first)
buy_orders = query_hive_engine("market", "buyBook", {"symbol": "LEO"}, limit=5)

# 3. Fetch Sell Orders (Lowest ask first)
sell_orders = query_hive_engine("market", "sellBook", {"symbol": "LEO"}, limit=5)
```

## 3. Placing and Canceling Orders with `beem`

All trade actions are structured as JSON payloads sent via `hive.custom_json()` with `id="ssc-mainnet-hive"`.

### Buying Tokens (Limit Order)

```python
from beem import Hive
import json
import os

account_name = os.environ.get("HIVE_ACCOUNT")
active_key = os.environ.get("HIVE_ACTIVE_KEY")

hive = Hive(node=["https://api.hive.blog"], keys=[active_key])

buy_payload = {
    "contractName": "market",
    "contractAction": "buy",
    "contractPayload": {
        "symbol": "LEO",
        "quantity": "10.00000000",
        "price": "0.14500000"
    }
}

tx = hive.custom_json(
    id="ssc-mainnet-hive",
    json_data=buy_payload,
    required_active_auths=[account_name]
)
print(f"Buy order placed: TX {tx['trx_id']}")
```

### Selling Tokens (Limit Order)

```python
sell_payload = {
    "contractName": "market",
    "contractAction": "sell",
    "contractPayload": {
        "symbol": "LEO",
        "quantity": "10.00000000",
        "price": "0.15500000"
    }
}

tx = hive.custom_json(
    id="ssc-mainnet-hive",
    json_data=sell_payload,
    required_active_auths=[account_name]
)
print(f"Sell order placed: TX {tx['trx_id']}")
```

### Canceling an Order

```python
cancel_payload = {
    "contractName": "market",
    "contractAction": "cancel",
    "contractPayload": {
        "type": "buy",  # or "sell"
        "id": "order_tx_id_from_book"
    }
}

tx = hive.custom_json(
    id="ssc-mainnet-hive",
    json_data=cancel_payload,
    required_active_auths=[account_name]
)
print(f"Order canceled: TX {tx['trx_id']}")
```

## 4. Hive Engine Token Transfers

Transferring Layer 2 tokens to another account uses the `tokens` contract:

```python
token_transfer_payload = {
    "contractName": "tokens",
    "contractAction": "transfer",
    "contractPayload": {
        "symbol": "LEO",
        "to": "recipient_user",
        "quantity": "5.00000000",
        "memo": "Payment for services"
    }
}

tx = hive.custom_json(
    id="ssc-mainnet-hive",
    json_data=token_transfer_payload,
    required_active_auths=[account_name]
)
print(f"Token transfer sent: TX {tx['trx_id']}")
```

## 5. Automated Market-Making Bot Strategy

A simple spread market maker bot:
1. Queries `buyBook` and `sellBook` for token `SYMBOL`.
2. Computes the highest bid `best_bid` and lowest ask `best_ask`.
3. If `spread = (best_ask - best_bid) / best_bid > MIN_PROFIT_SPREAD` (e.g. 2%):
   - Places a buy limit order just above `best_bid` (`best_bid + tick`).
   - Places a sell limit order just below `best_ask` (`best_ask - tick`).
4. Checks existing open orders: cancels orders that are outbid or unfilled after timeout.
5. Manages inventory limits: ensures bot doesn't accumulate more than max allocation in either `SWAP.HIVE` or the target token.

