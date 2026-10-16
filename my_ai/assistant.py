#!/usr/bin/env python3
"""A tiny personal assistant backed by a local llama.cpp model and MCF3 memory."""

from __future__ import annotations

import atexit
import json
import os
import platform
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from html.parser import HTMLParser
from pathlib import Path

# Setup terminal history if readline is available
try:
    import readline
    histfile = os.path.expanduser("~/.pocket_ai_history")
    try:
        readline.read_history_file(histfile)
    except (FileNotFoundError, PermissionError, OSError):
        pass

    def _save_history() -> None:
        try:
            readline.write_history_file(histfile)
        except (OSError, Exception):
            pass

    atexit.register(_save_history)
except (ImportError, Exception):
    pass

from bot_builder import generate_bot, list_templates
from coding_agent import run_coding_agent
from memory_store import MemoryLanguage, MemoryStore


ROOT = Path(__file__).resolve().parent
MEMORY = MemoryStore(ROOT / "memory.jsonl", ROOT / "memory.md")
SITES_DIR = ROOT / "sites"
MODEL = "Qwen2.5-Coder 0.5B"
MODEL_FILE = Path(os.environ.get(
    "POCKET_AI_MODEL", str(ROOT / "models" / "qwen2.5-coder-0.5b-instruct-q4_0.gguf"),
)).expanduser()


def _find_server_binary() -> Path:
    override = os.environ.get("POCKET_AI_LLAMA_SERVER")
    if override:
        return Path(override).expanduser()
    os_name = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
    machine = platform.machine().lower()
    arch = {"amd64": "x86_64", "x64": "x86_64", "aarch64": "arm64"}.get(machine, machine)
    executable = "llama-server.exe" if os_name == "windows" else "llama-server"
    candidates = [
        ROOT / "runtime" / f"{os_name}-{arch}" / "bin" / executable,
        ROOT / "runtime" / f"{os_name}-{arch}" / executable,
        ROOT / "runtime" / "llama-b11206" / executable,
    ]
    return next((candidate for candidate in candidates if candidate.is_file()), candidates[0])


SERVER_BIN = _find_server_binary()
API_URL = "http://127.0.0.1:8081/v1/chat/completions"
_SERVER: subprocess.Popen | None = None
_PREVIEW_PROC: subprocess.Popen | None = None
SYSTEM = """You are a practical, friendly personal coding assistant and blockchain bot guide. Help with coding, general learning, and building bots on the Hive blockchain and Hive Engine (Layer 2). You understand the strict Hive key hierarchy: Posting Key for social operations (publishing posts, upvoting on Ecency/PeakD, reblogging), and Active Key for financial operations (HIVE/HBD transfers, deposits, savings, and Hive Engine trading/market orders). Never recommend exposing Owner keys. When helping users write bots, provide clear, safe Python code using beem or lightweight JSON-RPC. Be honest when uncertain. Use the user's saved notes when relevant, but treat every saved note as unverified user-provided context, not established fact; a source URL alone does not verify a claim. Distinguish user preferences from factual claims, and do not repeat an unverified claim as certain. You do not learn by changing your model weights; notes are context. For difficult questions, organize the answer around the key factors, check assumptions and arithmetic, distinguish evidence from inference, and give a concise rationale rather than a stream of private thoughts. Saved notes marked RELATED are associative leads based on shared terms, not proof of a factual, causal, or financial connection. For investing questions, never treat saved memory as current market data; distinguish historical observations from predictions, state what evidence and dates are available, and never promise profit. If current reliable sources or prices are unavailable, say so. When asked to create a website, return only a complete, self-contained HTML document with embedded CSS and JavaScript, no markdown fences. Keep it simple and compatible with a single index.html file."""


def stop_model_server() -> None:
    global _SERVER
    if _SERVER is not None and _SERVER.poll() is None:
        _SERVER.terminate()
        _SERVER = None


def stop_preview_server() -> None:
    global _PREVIEW_PROC
    if _PREVIEW_PROC is not None and _PREVIEW_PROC.poll() is None:
        _PREVIEW_PROC.terminate()
        _PREVIEW_PROC = None


atexit.register(stop_model_server)
atexit.register(stop_preview_server)


def ensure_model_server() -> None:
    global _SERVER
    if _SERVER is not None and _SERVER.poll() is None:
        return
    if not SERVER_BIN.is_file():
        raise RuntimeError(f"Local llama.cpp runtime is missing: {SERVER_BIN}. See README.md.")
    if not MODEL_FILE.is_file():
        raise RuntimeError(f"Local model is missing: {MODEL_FILE}. See README.md.")
    threads = max(1, (os.cpu_count() or 4) - 1)
    _SERVER = subprocess.Popen(
        [str(SERVER_BIN), "--model", str(MODEL_FILE), "--ctx-size", "4096",
         "--threads", str(threads), "--host", "127.0.0.1", "--port", "8081", "--no-webui"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + 180
    while time.time() < deadline:
        if _SERVER.poll() is not None:
            raise RuntimeError("The local model server stopped during startup. Check README.md for setup details.")
        try:
            with urllib.request.urlopen("http://127.0.0.1:8081/health", timeout=2):
                return
        except urllib.error.URLError:
            time.sleep(0.5)
    raise RuntimeError("The local model server did not become ready within 3 minutes.")


class SearchResults(HTMLParser):
    """Extract DuckDuckGo result titles, links, and snippets without dependencies."""

    def __init__(self) -> None:
        super().__init__()
        self.items: list[dict[str, str]] = []
        self._current: dict[str, str] | None = None
        self._capture: str | None = None
        self._snippet_tag: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs = dict(attrs)
        classes = (attrs.get("class") or "").split()
        if tag == "a" and "result__a" in classes:
            raw_url = attrs.get("href") or ""
            if "uddg=" in raw_url:
                match = re.search(r"uddg=([^&]+)", raw_url)
                if match:
                    raw_url = urllib.parse.unquote(match.group(1))
            self._current = {"url": raw_url, "title": ""}
            self._capture = "title"
        elif "result__snippet" in classes:
            if self.items:
                self._current = self.items[-1]
            self._capture = "snippet"
            self._snippet_tag = tag

    def handle_data(self, data: str) -> None:
        if self._capture == "title" and self._current is not None:
            self._current["title"] += data
        elif self._capture == "snippet" and self._current is not None:
            self._current["snippet"] = self._current.get("snippet", "") + data

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._current is not None and self._capture == "title":
            self.items.append(self._current)
            self._current = None
            self._capture = None
        elif self._capture == "snippet" and tag == self._snippet_tag:
            self._capture = None
            self._current = None
            self._snippet_tag = None


def ask_model(prompt: str, system: str = SYSTEM, query_for_memory: str | None = "") -> str:
    """Send prompt to local llama.cpp model.
    
    If query_for_memory is provided, memory recall is targeted to that specific query,
    avoiding history pollution. If query_for_memory is None, memory recall is skipped.
    """
    notes = ""
    if query_for_memory is not None:
        search_target = query_for_memory if query_for_memory else prompt
        if MEMORY.ftp_configured:
            try:
                notes = MEMORY.relevant_remote(search_target)
            except Exception:
                notes = MEMORY.relevant(search_target)
        else:
            notes = MEMORY.relevant(search_target)

    full_system = system + (
        "\n\nRelevant saved notes (RELATED entries are associative leads, not verified conclusions):\n" + notes
        if notes else ""
    )
    ensure_model_server()
    payload = json.dumps({
        "model": "local",
        "messages": [
            {"role": "system", "content": full_system},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "temperature": 0.3,
        "max_tokens": 2048,
    }).encode("utf-8")
    request = urllib.request.Request(
        API_URL, data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            result = json.loads(response.read().decode("utf-8"))
        return result["choices"][0]["message"]["content"].strip()
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not connect to the local model server: {exc}") from exc


def search_web(query: str) -> list[dict[str, str]]:
    url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 personal-assistant"})
    with urllib.request.urlopen(request, timeout=20) as response:
        page = response.read().decode("utf-8", errors="replace")
    parser = SearchResults()
    parser.feed(page)
    return parser.items[:5]


def safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:48]
    if not slug:
        raise ValueError("Give the website a short name using letters or numbers.")
    return slug


def create_site(name: str, description: str) -> Path:
    folder = SITES_DIR / safe_slug(name)
    folder.mkdir(parents=True, exist_ok=True)
    prompt = (
        "Create a polished, responsive single-page website. User's request: "
        + description
        + " Return just valid, complete HTML. Put CSS in a style element. "
          "Do not use external libraries, images, or fonts. Include accessible labels."
    )
    page = ask_model(prompt, query_for_memory=None)
    page = re.sub(r"^```(?:html)?\s*|\s*```$", "", page.strip(), flags=re.I)
    if "<html" not in page.lower() and "<!doctype html" not in page.lower():
        raise RuntimeError("The model did not return a complete HTML page. Try a simpler request.")
    target = folder / "index.html"
    target.write_text(page + "\n", encoding="utf-8")
    return target


def show_help() -> None:
    print("""Commands:
  /search words...             Search the internet, then summarize results
  /site NAME | DESCRIPTION    Create a local website in my_ai/sites/NAME
  /preview NAME               Preview that website at http://localhost:8000
  /learn [CATEGORY] | NOTE    Save note (supports @pref, @proj, #tags, rel:target)
  /recall words...             Inspect memory recall scores and associative leads
  /forget ID or text           Delete a note from memory (updates FTP if enabled)
  /import filepath             Import notes from a markdown or text file
  /bot list                    List Hive bot templates (curation, posting, transfers, trader)
  /bot create TYPE NAME        Generate a ready-to-run Hive bot into my_ai/bots/NAME
    /code TASK                    Coding agent via Ollama; edits and tests need approval
  /memory                      Show categorized memory folder tree
  /check                       Check model, recall, and a small reasoning probe
    /sync                        Merge FTP shards into the bounded local cache
  /help                        Show these commands
  /quit                        Exit

Hive Bot Generator:
  /bot create curation my_voter        Auto-voting bot for PeakD/Ecency
  /bot create posting my_publisher     Markdown blog publisher
  /bot create transfers my_pay_bot     Payment/deposit watcher
  /bot create engine_trader my_dex     Hive Engine DEX trading bot

Memory Language (MCF3):
  @pref I prefer dark mode #style           Save under Preferences/ with tags
  @proj:Website Uses SQLite rel:Backend     Save under Projects/Website with relations
  Remember that I use Ubuntu 24.04          Natural conversational auto-saving""")


def ftp_configuration_warning(memory: MemoryStore = MEMORY) -> str | None:
    """Explain when memory is falling back to the local cache instead of FTP."""
    missing = [
        name for name, value in (
            ("MEMORY_FTP_HOST", memory.ftp_host),
            ("MEMORY_FTP_USER", memory.ftp_user),
            ("MEMORY_FTP_PASSWORD", memory.ftp_password),
        ) if not value
    ]
    if not missing:
        return None
    return (
        "WARNING: FTP memory is not connected (missing " + ", ".join(missing) + "). "
        "Notes are local-only and may be evicted from the bounded cache."
    )


def main() -> int:
    print(f"Pocket AI · {MODEL} · type /help for commands")
    warning = ftp_configuration_warning()
    if warning:
        print(warning)
    history: list[tuple[str, str]] = []

    natural_remember_patterns = (
        re.compile(r"^(?:please\s+)?remember(?:\s+that)?[:\s]+(.+)$", re.IGNORECASE),
        re.compile(r"^(?:please\s+)?keep\s+in\s+mind(?:\s+that)?[:\s]+(.+)$", re.IGNORECASE),
        re.compile(r"^(?:please\s+)?note(?:\s+that)?[:\s]+(.+)$", re.IGNORECASE),
    )

    while True:
        try:
            line = input("\nYou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line == "/quit":
            break
        if line == "/help":
            show_help()
            continue

        if line.startswith("/learn "):
            value = line[len("/learn "):].strip()
            category = None
            source = ""
            if "|" in value:
                parts = value.split("|", 2)
                category, value = parts[0], parts[1]
                if len(parts) == 3:
                    source = parts[2].strip()
                category = category.strip() or None
            note = value.strip()
            if note:
                try:
                    record = MEMORY.add(note, category, source)
                    if record is None:
                        print("That note is already saved.")
                        continue
                    print(f"Saved [{record['i']}] under Memory/{record['c']}/.")
                    if MEMORY.ftp_configured:
                        try:
                            MEMORY.upload(record)
                            print("Synced to the FTP memory file.")
                        except Exception as exc:
                            print(f"Local note kept; FTP upload failed: {exc}")
                    else:
                        print("FTP is not configured; this note is only in the bounded local cache.")
                except Exception as exc:
                    print(f"Could not save memory: {exc}")
            continue

        if line.startswith("/recall ") or line == "/recall":
            query = line[len("/recall"):].strip()
            if not query:
                print("Usage: /recall words... (e.g. /recall python, /recall cat:Preferences, /recall #darkmode)")
                continue
            diag = MEMORY.recall_details(query)
            print(f"Memory recall for {query!r} ({diag['total_records']} total notes indexed):")
            if diag["terms"]:
                print(f"  Vocabulary terms: {', '.join(diag['terms'])}")
            if diag["category_filter"]:
                print(f"  Category filter: {diag['category_filter']}")
            direct = diag["direct"]
            if direct:
                print(f"\n  Direct matches ({len(direct)}):")
                for item in direct:
                    src = f" [src: {item['source']}]" if item["source"] else ""
                    print(f"    • [{item['id']}] Memory/{item['category']}/: {item['note']}{src}")
            else:
                print("\n  Direct matches: none")
            related = diag["related"]
            if related:
                print(f"\n  Associative leads ({len(related)}):")
                for item in related:
                    via = ", ".join(item["via"][:3])
                    print(f"    • [{item['id']}] Memory/{item['category']}/ (via {via}): {item['note']}")
            continue

        if line.startswith("/forget "):
            target = line[len("/forget "):].strip()
            if not target:
                print("Usage: /forget NOTE_ID or /forget search words")
                continue
            removed = MEMORY.remove(target)
            if removed:
                print(f"Removed memory [{removed['i']}] from Memory/{removed['c']}/: {removed['n']}")
            else:
                print(f"No memory matching {target!r} found. Use /recall or /memory to check notes.")
            continue

        if line.startswith("/import "):
            path_str = line[len("/import "):].strip()
            target_file = Path(path_str).expanduser()
            if not target_file.is_file():
                print(f"File not found: {path_str}")
                continue
            try:
                count = MEMORY.import_file(target_file, category_prefix="Docs")
                print(f"Imported {count} notes from {target_file.name} under Memory/Docs/.")
            except Exception as exc:
                print(f"Import failed: {exc}")
            continue

        if line.startswith("/bot"):
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "list":
                print("Available Hive Bot Templates:")
                for t in list_templates():
                    print(f"  • {t['type']:15} [{t['key_required']:12}] {t['description']}")
                print("\nCreate with: /bot create <type> <name>")
                continue
            elif len(parts) >= 4 and parts[1] == "create":
                b_type, b_name = parts[2], parts[3]
                try:
                    dest = generate_bot(b_type, b_name)
                    print(f"Bot created successfully in: {dest}")
                    print(f"1. cd {dest}")
                    print("2. cp .env.example .env (and configure your credentials)")
                    print("3. python3 *.py")
                except Exception as exc:
                    print(f"Failed to create bot: {exc}")
                continue
            else:
                print("Usage:")
                print("  /bot list")
                print("  /bot create <curation|posting|transfers|engine_trader> <name>")
                continue

        if line == "/code" or line.startswith("/code "):
            task = line[len("/code"):].strip()
            if not task:
                print("Usage: /code describe a change, bug fix, or coding task")
                continue
            memory_recall = MEMORY.relevant
            memory_categories = lambda: sorted({str(record.get("c", "Knowledge")) for record in MEMORY.records})
            if MEMORY.ftp_configured:
                try:
                    use_remote = input("Allow this coding task to search the FTP-backed MCF3 knowledge graph (read-only)? [Y/n] ")
                    if use_remote.strip().casefold() not in {"n", "no"}:
                        memory_recall = MEMORY.relevant_remote
                        memory_categories = MEMORY.remote_categories
                except (EOFError, KeyboardInterrupt):
                    print("FTP memory access disabled for this task.")
            try:
                run_coding_agent(task, ROOT, memory_recall, memory_categories)
            except Exception as exc:
                print(f"Coding agent unavailable: {exc}")
            continue

        if line == "/memory":
            print(MEMORY.tree())
            continue

        if line == "/check":
            print("Session check (a quick consistency probe, not a measure of intelligence):")
            print(f"Memory: {len(MEMORY.records)} notes indexed; categorized recall is ready.")
            started = time.monotonic()
            try:
                answer = ask_model("Reply with only the number: what is 17 + 25?", query_for_memory=None)
                passed = bool(re.search(r"\b42\b", answer))
                print(f"Model: {'PASS' if passed else 'CHECK'} · arithmetic probe returned {answer[:120]!r}")
                print(f"Probe time: {time.monotonic() - started:.1f}s")
            except Exception as exc:
                print(f"Model: UNAVAILABLE · {exc}")
            continue

        if line == "/sync":
            try:
                remote_added, uploaded = MEMORY.sync()
                print(f"Memory sync complete: {remote_added} downloaded, {uploaded} uploaded.")
            except Exception as exc:
                print(f"Memory sync failed: {exc}")
            continue

        if line.startswith("/search "):
            query = line[len("/search "):].strip()
            try:
                results = search_web(query)
                if not results:
                    print("No results returned. Try different search words.")
                    continue
                sources = "\n".join(
                    f"{i}. {item.get('title', '').strip()}\n"
                    f"   {item.get('snippet', '').strip()}\n"
                    f"   URL: {item.get('url', '')}"
                    for i, item in enumerate(results, 1)
                )
                print("AI> " + ask_model(
                    f"Answer this question using these current search results. "
                    f"Cite sources by title and URL. Say if the results don't establish the answer.\n\n"
                    f"Question: {query}\n\nSearch results:\n{sources}",
                    query_for_memory=query,
                ))
            except Exception as exc:
                print(f"Search failed: {exc}")
            continue

        if line.startswith("/site "):
            value = line[len("/site "):]
            if "|" not in value:
                print("Usage: /site NAME | describe the website you want")
                continue
            name, description = value.split("|", 1)
            try:
                path = create_site(name.strip(), description.strip())
                print(f"Created {path}")
                print(f"Preview with: /preview {safe_slug(name)}")
            except Exception as exc:
                print(f"Website creation failed: {exc}")
            continue

        if line.startswith("/preview "):
            slug = safe_slug(line[len("/preview "):].strip())
            folder = SITES_DIR / slug
            if not (folder / "index.html").is_file():
                print(f"No website named {slug!r}. Create one with /site first.")
                continue

            stop_preview_server()
            global _PREVIEW_PROC
            _PREVIEW_PROC = subprocess.Popen(
                [sys.executable, "-m", "http.server", "8000", "--bind", "127.0.0.1"],
                cwd=folder, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            time.sleep(0.4)
            if _PREVIEW_PROC.poll() is not None:
                print("Preview server couldn't start; port 8000 may already be in use.")
                continue
            threading.Thread(target=_PREVIEW_PROC.wait, daemon=True).start()
            address = "http://127.0.0.1:8000"
            print(f"Preview server running at {address}.")
            try:
                webbrowser.open(address)
            except Exception:
                pass
            continue

        # Check for natural conversational memory trigger
        for pattern in natural_remember_patterns:
            match = pattern.match(line)
            if match:
                fact = match.group(1).strip()
                if fact:
                    try:
                        record = MEMORY.add(fact)
                        if record:
                            print(f"[Learned and saved to Memory/{record['c']}/]")
                    except Exception:
                        pass
                break

        context = "\n".join(f"You: {u}\nAssistant: {a}" for u, a in history[-3:])
        prompt = (context + "\n" if context else "") + "You: " + line + "\nAssistant:"
        try:
            answer = ask_model(prompt, query_for_memory=line)
            print("AI> " + answer)
            history.append((line, answer))
        except Exception as exc:
            print(f"AI unavailable: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
