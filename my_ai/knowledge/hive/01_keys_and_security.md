# Hive Blockchain Keys and Security Guide

The Hive blockchain uses a role-based key hierarchy. Choosing the right key is the most critical security rule for bot developers.

## The Key Hierarchy

Hive accounts have four distinct private keys derived from a master password:

1. **Posting Key (Private Posting Key)**:
   - Used for social operations: publishing posts (`comment`), replying to posts, upvoting/downvoting (`vote`), following, and reblogging (`custom_json`).
   - **Crucial Security Rule**: The Posting Key CANNOT transfer funds, withdraw savings, change account recovery, or trade on Hive Engine.
   - Always use the Posting Key for posting bots, auto-voters, and curation tools. If a posting bot's key is compromised, your funds remain 100% safe.

2. **Active Key (Private Active Key)**:
   - Used for financial and wallet operations: transferring HIVE and HBD (`transfer`), powering up (`transfer_to_vesting`), savings deposits/withdrawals, witness voting, and executing smart contract operations on Hive Engine.
   - Hive Engine trading (buy/sell orders, token transfers) requires the **Active Key** because Layer 2 contracts move assets.
   - Keep active keys strictly in `.env` files or encrypted keyrings (like Hive Keychain or `beempy`). Never hardcode private active keys in source code.

3. **Owner Key (Private Owner Key)**:
   - The master account recovery key. It can reset all other keys.
   - **Never use the Owner Key in any bot, script, or server.** Store it cold (offline on paper or hardware).

4. **Memo Key (Private Memo Key)**:
   - Used only for encrypting and decrypting private transfer memos prefixed with `#`.

## Best Practices for Bot Key Storage

- Store keys in environment variables:
  - `HIVE_ACCOUNT=your_bot_account`
  - `HIVE_POSTING_KEY=5K...`
  - `HIVE_ACTIVE_KEY=5J...`
- Load with `os.environ.get("HIVE_POSTING_KEY")`.
- When sharing or publishing code, add `.env` and `*.key` to `.gitignore`.
- Run trading and transfer bots on a dedicated sub-account with limited balances rather than your primary personal account with high savings or stake.

