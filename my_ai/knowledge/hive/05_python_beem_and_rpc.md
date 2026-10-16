# Hive Python Tools: beem Library and RPC Reference

## 1. Setting Up `beem` on Linux, macOS, and Windows

`beem` is the standard Python library for the Hive blockchain.

### Installation

```sh
pip install beem
```

If you encounter build errors on minimal systems or Windows, install prerequisite cryptographic dependencies:
```sh
# Debian / Ubuntu:
sudo apt-get install python3-dev libssl-dev

# macOS (Homebrew):
brew install openssl

# Windows:
pip install beem --prefer-binary
```

### Initializing `beem` with Failover Nodes

Public nodes can occasionally experience downtime or rate limiting. Always configure multiple fallback nodes:

```python
from beem import Hive

NODES = [
    "https://api.hive.blog",
    "https://api.deathwing.me",
    "https://hive-api.arcange.eu",
    "https://api.openhive.network"
]

hive = Hive(node=NODES, num_retries=5)
```

## 2. Zero-Dependency Hive RPC Queries

If you only need to read data (account balances, witness state, voting power, post content) without signing transactions, you don't even need `beem`. You can use Python's built-in `urllib`:

```python
import json
import urllib.request

HIVE_RPC = "https://api.hive.blog"

def hive_rpc(method: str, params: list) -> dict:
    payload = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params
    }).encode("utf-8")
    req = urllib.request.Request(HIVE_RPC, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as res:
        return json.loads(res.read().decode("utf-8")).get("result")

# Fetch account balances and voting power:
account_info = hive_rpc("condenser_api.get_accounts", [["alice"]])
if account_info:
    acc = account_info[0]
    print(f"HIVE Balance: {acc['balance']}")
    print(f"HBD Balance: {acc['hbd_balance']}")
    print(f"Voting Power: {acc['voting_power'] / 100:.2f}%")
```

## 3. Running 24/7 Bots on Any Platform

### Linux (Systemd Service or Tmux)
- In tmux: `tmux new -s hivebot` -> run `python3 bot.py` -> detach with `Ctrl+B, D`.
- Systemd service (`/etc/systemd/system/hivebot.service`):
  ```ini
  [Unit]
  Description=Hive Bot
  After=network.target

  [Service]
  User=moon
  WorkingDirectory=/home/moon/Desktop/AI/my_ai/bots/my_bot
  EnvironmentFile=/home/moon/Desktop/AI/my_ai/bots/my_bot/.env
  ExecStart=/usr/bin/python3 bot.py
  Restart=always
  RestartSec=10

  [Install]
  WantedBy=multi-user.target
  ```

### Windows
- Run in background via PowerShell or Windows Task Scheduler to auto-start on boot.
- Store keys securely in Windows Credential Manager or a local `.env`.

