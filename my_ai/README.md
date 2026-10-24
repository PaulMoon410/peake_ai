# Pocket AI

A small personal assistant using Qwen2.5-Coder 0.5B locally with llama.cpp. It has no Python package dependencies. It can answer questions, search the web when asked, remember notes you explicitly save, and generate simple websites for local preview.

## Start

This computer is Linux x86_64. The local CPU runtime and model are installed in this folder. Start the assistant with:

```sh
cd ~/Desktop/AI/my_ai
python3 assistant.py
```

The assistant starts the local model server when first needed and stops it when you exit. The runtime stays inside this folder; no administrator password or system-wide installation is needed. The model file is about 429 MB. Memory use while running is higher and depends on context length.

If you need to reinstall the runtime or model later:

```sh
mkdir -p runtime models
curl -fL https://github.com/ggml-org/llama.cpp/releases/download/b11206/llama-b11206-bin-ubuntu-x64.tar.gz | tar -xz -C runtime
curl -fL 'https://huggingface.co/Qwen/Qwen2.5-Coder-0.5B-Instruct-GGUF/resolve/main/qwen2.5-coder-0.5b-instruct-q4_0.gguf?download=true' -o models/qwen2.5-coder-0.5b-instruct-q4_0.gguf
```

## Commands

- Ordinary messages are handled as conversation first: the assistant uses recent turns, interprets simple/colloquial wording, and asks a short clarification when important context is missing. It does not automatically browse on every message.
- `/search current Python release` searches the web, then gives a conversational answer before a short Sources line. Follow-up searches such as `/search what about its memory use` carry forward the previous user topic instead of searching the fragment alone.
- `/site portfolio | Make a simple portfolio for a beginner programmer` creates `sites/portfolio/index.html`.
- `/preview portfolio` serves that folder at `http://127.0.0.1:8000` and opens it in a browser.
- `/learn I prefer Python examples` saves a concise note in `memory.jsonl`; simple rules place it in a category.
- `/learn @pref I prefer dark mode #style` uses the memory language prefix `@pref` and semantic tags `#style`.
- `/learn @proj:Website The site uses SQLite rel:Backend` saves under `Projects/Website` with explicit relation tracking.
- `/learn Projects/Website | The portfolio site uses a dark theme` saves it under a chosen category path.
- `/learn Finance/Markets | Historical observation | https://source.example/report` stores a source link with unverified provenance.
- `/recall query` inspects matching notes, match scores, vocabulary terms, and associative graph links.
- `/forget ID_OR_TEXT` removes a note from local memory and updates the remote FTP store if enabled.
- `/import path/to/notes.md` parses and chunks markdown or text documentation into structured memories.
- `/bot list` lists available Hive bot generator templates (curation, posting, transfers, engine_trader).
- `/bot create TYPE NAME` scaffolds a complete, production-ready Hive bot into `my_ai/bots/`.
- `/code TASK` starts an Ollama-powered coding agent for this project. It can list/read project files, show a diff and ask before writing, and ask before running the fixed Python unittest suite. It cannot run arbitrary shell commands.
- `/memory` displays categorized notes as a readable folder tree with note IDs.
- `/check` runs a small arithmetic probe and reports model response time and memory index status.
- `/sync` merges the FTP shard archive into the bounded local cache and uploads cache-only notes.
- `/quit` exits.

### Hive Blockchain & Hive Engine Bot Generator

Pocket AI includes specialized knowledge and scaffolding tools for building bots on the Hive blockchain and Hive Engine (Layer 2):

- **Key Security Hierarchy**:
  - **Posting Key**: Used for social actions (publishing posts on PeakD/Ecency, automated upvoting, curation). Cannot move funds.
  - **Active Key**: Used for financial operations (HIVE/HBD transfers, savings, exchange deposits, and Hive Engine DEX trading/smart contracts).
  - **Owner Key**: Cold recovery key — never used in bots.
- **Templates Available via `/bot create`**:
  - `curation` — Auto-upvoting and curation bot for PeakD/Ecency with voting power (VP) threshold and 5-minute curation delay.
  - `posting` — Automated markdown blog publisher with tagging and metadata.
  - `transfers` — Payment and deposit listener streaming incoming transfers with memo handling.
  - `engine_trader` — Hive Engine DEX limit order and spread market maker bot (`SWAP.HIVE` vs Layer 2 tokens like `LEO`, `DEC`, `SPS`).
- **Comprehensive Hive Knowledge Base**: Ingested in `my_ai/knowledge/hive/` covering key security, social frontends (Ecency, PeakD), financial operations, Hive Engine RPC querying, and Python `beem` integration.

### Memory Language (MCF3) and Recall Engine

The assistant uses **Memory Compact Format 3 (MCF3)**:
- **Natural Conversational Learning**: Phrases like `"Remember that I use Ubuntu 24.04"` or `"Please note that I prefer 4-space indentation"` are automatically detected and saved.
- **Directives & Categories**: Use `@pref`, `@proj[:Subproject]`, `@work`, `@tool`, `@finance`, or `* rule` to route notes automatically.
- **Semantic Tags & Relations**: Embed `#tag` for concept anchors and `rel:Target` or `-> Target` to explicitly bridge related knowledge.
- **Porter Stemmer FTS5**: Search uses SQLite FTS5 with `porter unicode61` stemming. FTP recall builds its search index in memory only, so the archive is not copied into Render's persistent storage.
- **Full Stopword Filtering**: Prevents common pronouns and function words (*it*, *is*, *my*, *to*, *in*, etc.) from generating false positive recall hits.
- **History Isolation**: Chat queries recall memories using only the current user message, preventing prior conversational turns from polluting search results.
- **FTP Archive**: Stores the shared MCF3 archive in sequential JSONL files, rotating before any file exceeds the configured per-file cap. Notes are limited to 500 characters. Existing `memory.md` notes are imported automatically the first time the store is created.

## FTP knowledge storage

When configured, FTP is the long-term shared archive; Render keeps only a small rolling cache and a temporary in-memory search index. Set these environment variables before starting the assistant. Use the FTP hostname and base file path given by the hosting provider; the path must be writable. The first `/learn` or `/sync` initializes the archive. Notes append to `MEMORY_FTP_PATH`; when that file reaches its limit, new notes go into sequential files such as `pocket-ai-memory.jsonl.000001`. Retrieval scans the shards without persisting the full archive locally.

```sh
export MEMORY_FTP_HOST='FTP host from your provider'
export MEMORY_FTP_USER='your FTP username'
read -rsp 'FTP password: ' MEMORY_FTP_PASSWORD; export MEMORY_FTP_PASSWORD; echo
export MEMORY_FTP_PATH='pocket-ai-memory.jsonl'
export MEMORY_FTP_TLS=1
# Maximum bytes per FTP shard (default 32 KiB; supported range 1–64 KiB).
export MEMORY_FTP_MAX_BYTES=16384
# Maximum notes retained in the persistent local cache (default 50).
export MEMORY_LOCAL_CACHE_RECORDS=50
python3 assistant.py
```

The per-file cap defaults to 32 KiB; configured values above 64 KiB are refused, and each record is capped at 4 KiB. Set `MEMORY_FTP_MAX_BYTES` below the provider's verified maximum file size. `MEMORY_LOCAL_CACHE_RECORDS` limits persistent local notes to the newest 50 by default. `/sync` can read the archive but keeps only that bounded subset on Render; `/forget` can remove notes even after they have left the local cache. The implementation supports up to 10,000 sequential FTP shards as a safety bound. Confirm the provider's current account, traffic, and file rules. Concurrent writes are not atomic, so sync from one device at a time. Ordinary FTP sends passwords and notes without encryption; use FTPS if supported. Never store credentials, private keys, or sensitive information in the archive.

### MCF3 knowledge store and Ollama coding agent

The assistant's knowledge is not stored in Ollama or learned into model weights. **MCF3 is the note language and retrieval format**: it stores categorized notes with tags, explicit `rel:` links, provenance, and compact JSONL records. When FTP is configured, its sequential capped files hold the shared remote archive. The local JSONL/SQLite files are a bounded rolling cache and search index; `/sync` merges with FTP but keeps only the newest configured number of notes locally. New `/learn` notes are cached and uploaded, and `/forget` updates the remote archive.

Normal assistant prompts query FTP directly when it is configured, falling back to the local cache if the server is unavailable. The `/code` agent can list memory categories and make repeated, task-directed MCF3 searches, including category/tag/relation searches; the recall process follows associative links. This FTP retrieval is read-only and does not sync or persist remote-only notes to the local cache. The model decides when further recall is useful, and all saved notes remain unverified context rather than authoritative facts.

This is a shared, categorized knowledge graph hosted as an FTP JSONL archive—not a peer-to-peer mesh network. Notes and relation links form the knowledge mesh; the current client discovers associations during recall. Each archive file stays within its configured byte cap, while additional sequential files grow the remote archive.

The regular assistant continues to use its bundled llama.cpp model. The separate `/code` mode uses Ollama's local chat API and tool calling. Install/start Ollama, then download the default tool-capable model:

```sh
ollama pull qwen3:4b
```

On Linux, if Ollama is not already running as a service, start it in a separate terminal with `ollama serve`. The `ollama` command must be installed and available on your PATH before pulling the model.

Start Pocket AI as usual and enter a task, for example `/code inspect the memory tests and fix any failing behavior`. If Ollama is not running, start its service before using `/code`. Set `POCKET_AI_CODE_MODEL` to use a different locally available tool-capable model, or `POCKET_AI_OLLAMA_URL` to change the API URL.

If FTP memory is configured, `/code` asks permission to query it for that coding task (read-only). The model can then request categories and more searches as needed. If you decline, it uses local cached memory. Project knowledge files under `knowledge/` remain readable by the agent.

The agent is restricted to this project folder. It blocks common secret files and generated/dependency/model directories, shows the complete proposed diff and requires confirmation before each write, and requires separate approval to run `python -m unittest discover -s tests`. It has no general-purpose shell tool. Review every change; model-generated edits can still be incorrect.

### Multi-device knowledge sharing and future mesh

At present this is a **central shared knowledge archive**, not a peer-to-peer mesh: devices retrieve and append notes to the configured FTP shard set. FTP hosting does not provide per-device identity or protect against poisoned uploads. Every incoming note remains unverified user context. A future peer mesh would need authenticated device identities, signed/versioned records, deduplication, quotas, provenance, and human review before spreading claims.

### Cross-platform executable

The Python assistant is being kept platform-aware, but the included llama.cpp runtime is Linux x86_64 only. A distributable for each Windows/macOS/Linux and CPU architecture needs its matching llama.cpp server binary and libraries plus the model. Put it in `runtime/<platform>-<architecture>/bin/llama-server` (Windows uses `llama-server.exe`), or set `POCKET_AI_LLAMA_SERVER` and `POCKET_AI_MODEL` to the bundled file paths. The GGUF model can be shared where the target hardware supports it; the native runtime cannot. A genuine one-click installer/auto-updater and a peer mesh are not implemented yet.

## Privacy and limits

Chat and model inference run locally. `/search` sends the search words to DuckDuckGo; results are supplied to the local model for summarizing. When configured, FTP stores shared MCF3 notes remotely; Render retains only the bounded local cache. The assistant only creates website files in its `sites/` folder and does not run generated code. A 0.5B model can make mistakes, so review generated code and pages.


## Read-only Hive bot status

Pocket AI can ask the private Render market bot for a current, read-only status snapshot. It does not receive a Hive key and cannot control orders.

Before starting Pocket AI, set:

```sh
export HIVE_BOT_STATUS_URL=https://YOUR-RENDER-SERVICE.onrender.com/ai/v1/status
export HIVE_BOT_STATUS_TOKEN='the-token-configured-as-AI_STATUS_API_TOKEN-on-Render'
```

Then use `/hive-status` to summarize the latest snapshot, or `/hive-status your question` to ask about it. The status URL must use HTTPS. Keep the bearer token in environment settings and never commit it or paste it into chat. A missing or stale snapshot is reported as unavailable; the command does not submit any trading actions.
