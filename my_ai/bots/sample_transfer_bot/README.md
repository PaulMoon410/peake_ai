# Sample Transfer Bot

Payment/deposit watcher and automated transfer bot

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
2. Fill in your Hive account name and private **Active Key**.
3. Run the bot:
   ```sh
   python3 transfer_bot.py
   ```

## Security Note

- **Active Key**: Always keep private keys secret. Never commit `.env` to git repositories.
