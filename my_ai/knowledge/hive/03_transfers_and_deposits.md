# Hive Financial Automation: Transfers, Deposits, and Savings Guide

Hive has zero transaction fees (gas fees) and 3-second block times, making it ideal for micro-transactions, automated deposits, tip bots, and payment gateways. All financial movements require the **Active Key**.

## 1. Transfer Fundamentals

- Assets supported on Layer 1: `HIVE` and `HBD` (Hive Backed Dollar).
- **Format rule**: Asset amounts must be formatted with exactly 3 decimal places (e.g. `"1.000 HIVE"`, `"0.500 HBD"`).
- **Memos**: Plaintext memo (e.g. `"order_12345"`, `"exchange deposit ID"`) or encrypted memo starting with `#`.

### Sending a Transfer with Python (`beem`)

```python
from beem import Hive
from beem.account import Account
import os

account_name = os.environ.get("HIVE_ACCOUNT")
active_key = os.environ.get("HIVE_ACTIVE_KEY")

hive = Hive(node=["https://api.hive.blog"], keys=[active_key])
acc = Account(account_name, blockchain_instance=hive)

# Transfer 1.000 HIVE to @recipient with a memo
tx = acc.transfer(
    to="recipient_account",
    amount=1.000,
    asset="HIVE",
    memo="Payment for Order #42"
)
print(f"Transfer confirmed: TX ID {tx.get('trx_id')}")
```

## 2. Savings and Power Up Operations

1. **Powering Up (`transfer_to_vesting`)**:
   Converts liquid HIVE into staked Hive Power (HP) for increased voting influence and resource credits:
   ```python
   acc.transfer_to_vesting(amount=5.000, to=account_name)
   ```

2. **Deposit into Savings (`transfer_to_savings`)**:
   HBD in savings earns interest (currently set by witnesses, typically around 15-20% APR).
   ```python
   acc.transfer_to_savings(amount=10.000, asset="HBD", memo="Savings deposit")
   ```

3. **Withdraw from Savings (`transfer_from_savings`)**:
   Requires a 3-day safety cooldown period before funds arrive in liquid wallet:
   ```python
   acc.transfer_from_savings(amount=10.000, asset="HBD", request_id=1)
   ```

## 3. Automated Deposit and Payment Listener Bot

A payment listener bot streams operations on the blockchain, filtering for inbound `transfer` transactions addressed to your bot's account:

```python
from beem.blockchain import Blockchain
from beem import Hive
import os

bot_account = os.environ.get("HIVE_ACCOUNT", "mybotaccount")
hive = Hive(node=["https://api.hive.blog", "https://api.deathwing.me"])
chain = Blockchain(blockchain_instance=hive)

print(f"Monitoring incoming transfers for @{bot_account}...")

# Stream blocks and filter transfer operations
for op in chain.stream(opNames=["transfer"]):
    if op.get("to") == bot_account:
        sender = op.get("from")
        amount = op.get("amount")  # e.g. "5.000 HIVE" or "2.500 HBD"
        memo = op.get("memo", "").strip()
        
        print(f"Payment received! From: @{sender}, Amount: {amount}, Memo: {memo}")
        
        # Process order based on memo
        if memo.startswith("order:"):
            order_id = memo.split(":", 1)[1]
            print(f"Processing Order #{order_id} for @{sender}")
        else:
            print(f"Unrecognized memo: {memo}")
```

### Safety Rules for Payment Gateways:
- Always verify that `op['to'] == bot_account`.
- Check asset name (`HIVE` vs `HBD`) and parse numeric amount safely (`float(amount.split()[0])`).
- Wait for 1 irreversible block or at least 2 confirmations (6 seconds) before fulfilling high-value orders to prevent micro-fork race conditions.

