import os
from pathlib import Path
import re
import threading
import time
import hmac
import ftplib
from collections import defaultdict, deque
from typing import Optional, Tuple
from datetime import datetime, timedelta
from flask import Flask, jsonify, request, Response, send_from_directory
from werkzeug.utils import secure_filename
from PIL import Image, ImageFilter, ImageEnhance, ImageOps
import tool_events
import agent_tools
from my_ai.conversation import normalize_history

# Load .env if present (no external dependency).
_env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.isfile(_env_path):
    for _line in open(_env_path).read().splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _k, _v = _line.split("=", 1)
        os.environ.setdefault(_k.strip(), _v.strip())

from peakebot import (
  _query_ai_providers_for_self_talk,
  _get_mcf_memory_store,
  _ftp_connect_for_upload,
  _ftp_store_binary,
  _resolved_ftp_base_dir,
  _handle_code_generation_request,
  warm_language_model,
  generate_response,
  add_base_knowledge_entry,
  list_base_knowledge_entries,
  queue_learning_topic,
  get_growth_snapshot,
  get_ftp_status,
  flush_sync_tasks,
  startup_ftp_sync,
  trading_advise,
  trading_learn_mechanism,
  trading_record_outcome,
  trading_record_lesson,
  trading_summary,
)
from my_ai.integrations.integration_manager import IntegrationManager
from my_ai.memory_organizer import sync_and_organize, HttpRecallCoordinator
from my_ai.daily_ecency_poster import start_daily_poster, post_daily_update
from my_ai import harold_waves


app = Flask(__name__)

# Initialize integration manager
integration_manager = IntegrationManager()

# Keep one generation at a time to avoid model state collisions.
_GENERATION_LOCK = threading.Lock()

from ollama_adapter import register_ollama_adapter
from peakebot import _get_language_model

register_ollama_adapter(
    app, lambda: CHAT_API_KEY, lambda client: _check_rate_limit(client),
    _GENERATION_LOCK, _get_language_model,
)

from response_coordinator import register_response_coordinator
from peakebot import _ai_chat_completion

register_response_coordinator(
    app, lambda: CHAT_API_KEY, lambda client: _check_rate_limit(client),
    _GENERATION_LOCK, _ai_chat_completion,
)

# Lightweight in-memory per-IP rate limiter for public testing.
_RATE_WINDOW_SECONDS = 60
_RATE_LIMIT_REQUESTS = 15
_REQUEST_LOG = defaultdict(deque)
_ADMIN_RATE_WINDOW_SECONDS = 60
_ADMIN_RATE_LIMIT_REQUESTS = 40
_ADMIN_REQUEST_LOG = defaultdict(deque)
_FTP_STARTUP_SYNC_LOCK = threading.Lock()
_FTP_STARTUP_SYNC_STARTED = False
_FTP_STARTUP_SYNC_DONE = threading.Event()
_FTP_STARTUP_SYNC_RESULT: dict = {}
_FTP_STARTUP_SYNC_TIMEOUT = float(os.getenv("FTP_STARTUP_SYNC_TIMEOUT", "25"))
_FTP_STARTUP_SYNC_RETRY_SECONDS = int(os.getenv("FTP_STARTUP_SYNC_RETRY_SECONDS", "120"))
_FTP_STARTUP_SYNC_MAX_ATTEMPTS = int(os.getenv("FTP_STARTUP_SYNC_MAX_ATTEMPTS", "10"))
_MODEL_WARMUP_LOCK = threading.Lock()
_MODEL_WARMUP_STARTED = False

_LAST_USER_ACTIVITY = time.time()
_KEEPALIVE_THREAD_STARTED = False
_KEEPALIVE_LOCK = threading.Lock()

CHAT_API_KEY = os.getenv("CHAT_API_KEY", "").strip()
ADMIN_PANEL_ENABLED = os.getenv("ADMIN_PANEL_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "")

# ... rest of existing config
# The trading bot runs on the operator's machine and calls this service.
# It gets its own key so trading traffic can be rotated independently.
TRADING_API_KEY = os.getenv("TRADING_API_KEY", "") or ADMIN_API_KEY
_TRADING_RATE_WINDOW_SECONDS = 60
_TRADING_RATE_LIMIT_REQUESTS = 120
_TRADING_REQUEST_LOG = defaultdict(deque)


def _start_ftp_startup_sync() -> None:
  """Archive local logs/notes to FTP in the background, retrying until it lands.

  Render's disk is ephemeral, so a backlog that only exists locally is lost on
  the next deploy. The first request waits (briefly) for this to finish so a
  chat turn can never outrun the archive.
  """
  global _FTP_STARTUP_SYNC_STARTED
  with _FTP_STARTUP_SYNC_LOCK:
    if _FTP_STARTUP_SYNC_STARTED:
      return
    _FTP_STARTUP_SYNC_STARTED = True

  def run() -> None:
    global _FTP_STARTUP_SYNC_RESULT
    backoff = _FTP_STARTUP_SYNC_RETRY_SECONDS
    attempt = 0
    try:
      store = _get_mcf_memory_store()
      mode = "explicit FTPS" if store.ftp_tls else "plain FTP"
      print(
        f"[startup] MCF3 FTP archive: {store.ftp_host}:21 via {mode}; passive mode if possible. "
        "SFTP is not used. This run uploads local session logs and notes and pulls "
        "remote knowledge down, so it does test upload permission.",
        flush=True,
      )
    except Exception as exc:
      print(f"[startup] FTP transport probe skipped: {type(exc).__name__}", flush=True)
    while True:
      attempt += 1
      try:
        report = startup_ftp_sync()
      except Exception as exc:
        print(f"[startup] FTP sync raised {type(exc).__name__}: {exc}", flush=True)
        report = {"ok": False, "errors": [f"{type(exc).__name__}: {exc}"]}
      with _FTP_STARTUP_SYNC_LOCK:
        _FTP_STARTUP_SYNC_RESULT = report
      if attempt == 1:
        _FTP_STARTUP_SYNC_DONE.set()
      if report.get("ok") or attempt >= _FTP_STARTUP_SYNC_MAX_ATTEMPTS:
        return
      # FTP may not be reachable yet at boot; keep retrying with backoff.
      print(f"[startup] FTP sync incomplete, retrying in {backoff}s.", flush=True)
      time.sleep(backoff)
      backoff = min(backoff * 2, 900)

  threading.Thread(target=run, name="ftp-startup-sync", daemon=True).start()


def _start_model_warmup() -> None:
  """Initialize/train/load the own model in background after Gunicorn binds."""
  global _MODEL_WARMUP_STARTED
  with _MODEL_WARMUP_LOCK:
    if _MODEL_WARMUP_STARTED:
      return
    _MODEL_WARMUP_STARTED = True

  def warm() -> None:
    print("[startup] Own language model warm-up started in background.", flush=True)
    warm_language_model()


  threading.Thread(target=warm, name="model-warmup", daemon=True).start()


def _get_mcf_store_for_poster():
  """Return the MCF memory store for the daily poster, or None if unavailable."""
  try:
    return _get_mcf_memory_store()
  except Exception:
    return None


def _start_daily_ecency_poster() -> None:
  """Start the daily Ecency/Hive community poster in the background."""
  start_daily_poster(store_getter=_get_mcf_store_for_poster)


def _wave_text(prompt: str) -> str:
  import peakebot
  reply = peakebot._ai_chat_completion(prompt, "")
  return str((reply or {}).get("answer") or "")


def _start_harold_waves() -> None:
  """Start the once-a-day Hive Wave poster (no-op until Hive credentials exist)."""
  harold_waves.start_waves_poster(generate=_wave_text)


@app.before_request
def _kickoff_ftp_startup_check() -> None:
  # Gunicorn has bound the listener; keep readiness requests fast during warm-up.
  _start_ftp_startup_sync()
  _start_model_warmup()
  _start_daily_ecency_poster()
  _start_harold_waves()
  _start_keepalive_learning()

  if request.path != "/health":
      _touch_user_activity()
  if request.path != "/health":
    # Let the archive finish before handling real traffic.
    _FTP_STARTUP_SYNC_DONE.wait(timeout=_FTP_STARTUP_SYNC_TIMEOUT)


def _touch_user_activity() -> None:
    global _LAST_USER_ACTIVITY
    _LAST_USER_ACTIVITY = time.time()


def _start_keepalive_learning() -> None:
    global _KEEPALIVE_THREAD_STARTED
    with _KEEPALIVE_LOCK:
        if _KEEPALIVE_THREAD_STARTED:
            return
        _KEEPALIVE_THREAD_STARTED = True

    def run() -> None:
        port = os.getenv("PORT", "10000")
        base = os.getenv("RENDER_EXTERNAL_URL", f"http://127.0.0.1:{port}").rstrip("/")
        while True:
            time.sleep(60)
            try:
                import urllib.request
                urllib.request.urlopen(f"{base}/health", timeout=10).read()
            except Exception:
                pass
            if time.time() - _LAST_USER_ACTIVITY >= 60:
                try:
                    from my_ai.harold.agent import HaroldAgent
                    from peakebot import _get_mcf_memory_store
                    store = _get_mcf_memory_store()
                    agent = HaroldAgent(store)
                    agent.learn(topic_limit=2)
                    try:
                        from my_ai.memory_organizer import sync_and_organize
                        sync_and_organize()
                    except Exception:
                        pass
                    print("[keepalive] idle learning pass complete", flush=True)
                except Exception as exc:
                    print(f"[keepalive] learning failed: {type(exc).__name__}: {exc}", flush=True)

    threading.Thread(target=run, name="keepalive-learning", daemon=True).start()


def _check_rate_limit(client_ip: str) -> bool:
    now = time.time()
    q = _REQUEST_LOG[client_ip]
    while q and now - q[0] > _RATE_WINDOW_SECONDS:
        q.popleft()
    if len(q) >= _RATE_LIMIT_REQUESTS:
        return False
    q.append(now)
    return True


def _check_admin_rate_limit(client_ip: str) -> bool:
    now = time.time()
    q = _ADMIN_REQUEST_LOG[client_ip]
    while q and now - q[0] > _ADMIN_RATE_WINDOW_SECONDS:
        q.popleft()
    if len(q) >= _ADMIN_RATE_LIMIT_REQUESTS:
        return False
    q.append(now)
    return True


def _admin_enabled_and_configured() -> Tuple[bool, Optional[Response]]:
    if not ADMIN_PANEL_ENABLED:
        return False, jsonify({"error": "admin panel disabled"})
    if not ADMIN_API_KEY:
        return False, jsonify({"error": "ADMIN_API_KEY is not configured"})
    return True, None


def _is_admin_authorized(req) -> bool:
    incoming = (req.headers.get("X-Admin-Key", "") or "").strip()
    if not incoming or not ADMIN_API_KEY:
        return False
    return hmac.compare_digest(incoming, ADMIN_API_KEY)


@app.after_request
def _add_cors_headers(response: Response) -> Response:
    """Allow other Render apps (and browser frontends) to call this API."""
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Admin-Key, X-Trading-Key, X-Api-Key"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response


@app.get("/api/memory")
def api_memory_list() -> Response:
    try:
        store = _get_mcf_memory_store()
        return jsonify({"ok": True, "records": store.all_records()})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.post("/api/memory")
def api_memory_add() -> Response:
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"ok": False, "error": "text required"}), 400
    try:
        store = _get_mcf_memory_store()
        rec = store.add(text, category=data.get("category", "API"), source=data.get("source", "api"))
        return jsonify({"ok": True, "record": rec})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.get("/health")
def health_check() -> Response:
    """Simple health check endpoint."""
    return jsonify({"status": "ok"})

@app.get("/")
def index() -> Response:
    html = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
  <title>Harold AI · Terminal</title>
  <style>
    :root {
      --bg: #090d16;
      --surface: #0f172a;
      --surface-card: #141e33;
      --border: rgba(255, 255, 255, 0.08);
      --border-focus: #3b82f6;
      --text: #f1f5f9;
      --text-muted: #94a3b8;
      --text-dim: #64748b;
      --accent: #10b981;
      --accent-glow: rgba(16, 185, 129, 0.2);
      --user-bubble: #1e293b;
      --bot-bubble: #111a2e;
      --warn: #f59e0b;
      --error: #ef4444;
      --purple: #a855f7;
      --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    html, body {
      height: 100%;
      background: var(--bg);
      color: var(--text);
      font-family: var(--sans);
      font-size: 14px;
      line-height: 1.5;
      -webkit-font-smoothing: antialiased;
    }
    body {
      display: flex;
      justify-content: center;
      align-items: center;
      padding: 12px;
    }
    .app-container {
      display: flex;
      flex-direction: column;
      width: 100%;
      max-width: 960px;
      height: 94vh;
      max-height: 900px;
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 16px;
      box-shadow: 0 20px 50px rgba(0, 0, 0, 0.5), 0 1px 0 rgba(255, 255, 255, 0.05) inset;
      overflow: hidden;
      position: relative;
    }
    /* Top Bar */
    .top-bar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 12px 18px;
      background: rgba(15, 23, 42, 0.85);
      backdrop-filter: blur(8px);
      border-bottom: 1px solid var(--border);
      z-index: 10;
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 10px;
      font-weight: 600;
      letter-spacing: -0.01em;
    }
    .status-dot {
      width: 9px;
      height: 9px;
      border-radius: 50%;
      background: var(--accent);
      box-shadow: 0 0 10px var(--accent);
      transition: background 0.3s, box-shadow 0.3s;
    }
    .status-dot.busy {
      background: var(--warn);
      box-shadow: 0 0 10px var(--warn);
      animation: pulse 1.5s infinite;
    }
    @keyframes pulse {
      0%, 100% { opacity: 1; }
      50% { opacity: 0.4; }
    }
    .brand-title {
      color: var(--text);
      font-size: 14px;
      font-weight: 600;
    }
    .brand-subtitle {
      color: var(--text-dim);
      font-size: 12px;
      font-family: var(--mono);
      margin-left: 2px;
    }
    .top-actions {
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .btn-ghost {
      background: rgba(255, 255, 255, 0.04);
      color: var(--text-muted);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 5px 11px;
      font-size: 12px;
      font-family: var(--sans);
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      transition: all 0.15s ease;
    }
    .btn-ghost:hover {
      background: rgba(255, 255, 255, 0.08);
      color: var(--text);
      border-color: rgba(255, 255, 255, 0.15);
    }
    .btn-ghost.active {
      background: rgba(168, 85, 247, 0.15);
      border-color: rgba(168, 85, 247, 0.4);
      color: #d8b4fe;
    }
    /* Main Area with Drawer */
    .main-body {
      display: flex;
      flex: 1;
      min-height: 0;
      position: relative;
      overflow: hidden;
    }
    /* Chat stream */
    .chat-view {
      flex: 1;
      display: flex;
      flex-direction: column;
      min-width: 0;
      overflow: hidden;
    }
    #log {
      flex: 1;
      overflow-y: auto;
      padding: 20px 20px 10px;
      display: flex;
      flex-direction: column;
      gap: 14px;
      scroll-behavior: smooth;
    }
    #log::-webkit-scrollbar { width: 6px; }
    #log::-webkit-scrollbar-thumb { background: rgba(255, 255, 255, 0.1); border-radius: 4px; }
    /* Message Bubbles */
    .msg-row {
      display: flex;
      flex-direction: column;
      max-width: 86%;
      animation: fadeIn 0.2s cubic-bezier(0.16, 1, 0.3, 1);
    }
    @keyframes fadeIn {
      from { opacity: 0; transform: translateY(4px); }
      to { opacity: 1; transform: translateY(0); }
    }
    .msg-row.user {
      align-self: flex-end;
    }
    .msg-row.bot {
      align-self: flex-start;
    }
    .msg-author {
      font-size: 11px;
      font-weight: 600;
      color: var(--text-dim);
      margin-bottom: 4px;
      padding: 0 4px;
    }
    .msg-row.user .msg-author {
      align-self: flex-end;
      color: #93c5fd;
    }
    .msg-row.bot .msg-author {
      color: #6ee7b7;
    }
    .msg-bubble {
      padding: 12px 16px;
      border-radius: 12px;
      word-break: break-word;
      line-height: 1.55;
      font-size: 13.5px;
      white-space: pre-wrap;
    }
    .msg-row.user .msg-bubble {
      background: var(--user-bubble);
      color: #f8fafc;
      border: 1px solid rgba(255, 255, 255, 0.08);
      border-bottom-right-radius: 4px;
    }
    .msg-row.bot .msg-bubble {
      background: var(--bot-bubble);
      color: var(--text);
      border: 1px solid var(--border);
      border-bottom-left-radius: 4px;
    }
    .msg-row.error .msg-bubble {
      background: rgba(239, 68, 68, 0.1);
      border: 1px solid rgba(239, 68, 68, 0.25);
      color: #fca5a5;
    }
    /* Tool Events */
    .tool-card {
      align-self: flex-start;
      margin: -4px 0 2px 2px;
      font-family: var(--mono);
      font-size: 11.5px;
      background: rgba(255, 255, 255, 0.02);
      border: 1px solid var(--border);
      border-radius: 8px;
      overflow: hidden;
      max-width: 90%;
    }
    .tool-card summary {
      padding: 6px 10px;
      cursor: pointer;
      list-style: none;
      display: flex;
      align-items: center;
      gap: 6px;
      color: var(--text-muted);
      user-select: none;
    }
    .tool-card summary::-webkit-details-marker { display: none; }
    .tool-card summary:hover {
      background: rgba(255, 255, 255, 0.03);
      color: var(--text);
    }
    .tool-card .status-icon {
      font-weight: bold;
    }
    .tool-card .status-icon.ok { color: var(--accent); }
    .tool-card .status-icon.err { color: var(--error); }
    .tool-card pre {
      padding: 8px 10px;
      background: rgba(0, 0, 0, 0.3);
      color: var(--text-dim);
      font-size: 11px;
      border-top: 1px solid var(--border);
      white-space: pre-wrap;
      max-height: 140px;
      overflow-y: auto;
    }
    /* Warning Banner */
    #startup-warning {
      display: none;
      padding: 8px 16px;
      background: rgba(245, 158, 11, 0.12);
      border-bottom: 1px solid rgba(245, 158, 11, 0.2);
      color: #fbbf24;
      font-size: 12px;
      align-items: center;
      gap: 8px;
    }
    /* Side Panel / Self-talk */
    #selftalkPanel {
      width: 320px;
      background: #090e1a;
      border-left: 1px solid var(--border);
      display: none;
      flex-direction: column;
      animation: slideIn 0.2s ease-out;
    }
    @keyframes slideIn {
      from { transform: translateX(20px); opacity: 0; }
      to { transform: translateX(0); opacity: 1; }
    }
    .st-bar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 12px 14px;
      border-bottom: 1px solid var(--border);
      font-size: 12px;
      font-weight: 600;
      color: #d8b4fe;
    }
    #selftalkLog {
      flex: 1;
      overflow-y: auto;
      padding: 12px;
      display: flex;
      flex-direction: column;
      gap: 8px;
      font-size: 12px;
      line-height: 1.45;
    }
    .st-turn {
      padding: 8px 10px;
      border-radius: 6px;
      background: rgba(255, 255, 255, 0.02);
      border: 1px solid var(--border);
    }
    .st-turn.critic {
      border-color: rgba(251, 191, 36, 0.2);
      color: #fde68a;
      font-style: italic;
    }
    .st-turn.learner {
      color: #c4b5fd;
    }
    .st-turn.instructor {
      color: #93c5fd;
    }
    .st-topic-tag {
      font-size: 11px;
      color: var(--text-dim);
      text-transform: uppercase;
      letter-spacing: 0.05em;
      margin: 6px 0 2px;
      text-align: center;
    }
    /* Bottom Input Section */
    .bottom-section {
      border-top: 1px solid var(--border);
      background: rgba(15, 23, 42, 0.7);
      padding: 12px 16px 14px;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .input-row {
      display: flex;
      gap: 8px;
      align-items: flex-end;
    }
    .textarea-wrapper {
      flex: 1;
      position: relative;
    }
    textarea {
      width: 100%;
      min-height: 44px;
      max-height: 160px;
      background: #090e1a;
      color: var(--text);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 11px 14px;
      font-family: inherit;
      font-size: 13.5px;
      line-height: 1.45;
      resize: none;
      outline: none;
      transition: border-color 0.15s, box-shadow 0.15s;
    }
    textarea:focus {
      border-color: var(--border-focus);
      box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.2);
    }
    .action-btn {
      height: 44px;
      padding: 0 16px;
      border-radius: 10px;
      border: 0;
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      transition: all 0.15s;
      user-select: none;
    }
    .btn-send {
      background: var(--accent);
      color: #022c22;
    }
    .btn-send:hover {
      background: #059669;
      box-shadow: 0 2px 10px var(--accent-glow);
    }
    .btn-steer {
      background: rgba(245, 158, 11, 0.15);
      border: 1px solid rgba(245, 158, 11, 0.3);
      color: #fde68a;
      padding: 0 12px;
    }
    .btn-steer:hover {
      background: rgba(245, 158, 11, 0.25);
    }
    button:disabled {
      opacity: 0.5;
      cursor: not-allowed;
      box-shadow: none !important;
    }
    .footer-bar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-size: 11.5px;
      color: var(--text-dim);
      padding: 0 2px;
    }
    .footer-hints code {
      font-family: var(--mono);
      background: rgba(255, 255, 255, 0.05);
      padding: 1px 4px;
      border-radius: 4px;
    }
    #queue-status {
      font-weight: 500;
      transition: color 0.2s;
    }
    #queue-status.busy {
      color: var(--warn);
    }
    @media (max-width: 640px) {
      body { padding: 0; }
      .app-container { height: 100vh; max-height: none; border-radius: 0; border: 0; }
      #selftalkPanel { position: absolute; right: 0; top: 0; bottom: 0; width: 85%; z-index: 20; box-shadow: -10px 0 30px rgba(0,0,0,0.5); }
      .btn-steer span { display: none; }
    }

    /* Code blocks */
    .code-wrap { position: relative; margin: 12px 0; border: 1px solid var(--border); border-radius: 10px; overflow: hidden; background: #090e1a; }
    .code-wrap pre { margin: 0; padding: 14px; overflow-x: auto; font-size: 13px; line-height: 1.5; }
    .code-wrap code { font-family: var(--mono); color: #e2e8f0; }
    .code-copy { position: absolute; top: 8px; right: 8px; background: #1e293b; border: 1px solid var(--border); color: var(--text); padding: 4px 10px; border-radius: 6px; font-size: 12px; cursor: pointer; }
    .code-copy:hover { background: #334155; }

    /* Images */
    .msg-image-wrap { margin: 12px 0; text-align: center; }
    .msg-image { max-width: 100%; max-height: 400px; border-radius: 10px; border: 1px solid var(--border); cursor: pointer; }
    .msg-image:hover { filter: brightness(1.1); }
    .msg-image-cap { font-size: 12px; color: var(--text-dim); margin-top: 6px; }

    /* Videos */
    .msg-video-wrap { margin: 12px 0; text-align: center; }
    .msg-video-cap { font-size: 12px; color: var(--text-dim); margin-top: 6px; }

    /* Audio */
    .msg-audio-wrap { margin: 12px 0; }
    .msg-audio-cap { font-size: 12px; color: var(--text-dim); margin-top: 6px; }

    /* Image upload button */
    .img-upload-btn { background: #1e293b; border: 1px solid var(--border); color: var(--text); padding: 0 12px; border-radius: 8px; font-size: 13px; cursor: pointer; margin-left: 8px; }
    .img-upload-btn:hover { background: #334155; }
    #imgInput { display: none; }

    /* Image action buttons */
    .img-actions { display: flex; gap: 6px; justify-content: center; margin-top: 6px; flex-wrap: wrap; }
    .img-btn { background: #1e293b; border: 1px solid var(--border); color: var(--text); padding: 4px 10px; border-radius: 6px; font-size: 11px; cursor: pointer; }
    .img-btn:hover { background: #334155; }
    .img-btn.primary { background: var(--accent); border-color: var(--accent); color: #000; }
    .img-btn.primary:hover { background: #4ade80; }

    /* Image edit modal */
    .modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.85); z-index: 1000; display: none; align-items: center; justify-content: center; padding: 20px; }
    .modal-overlay.open { display: flex; }
    .modal { background: var(--panel); border: 1px solid var(--border); border-radius: 12px; width: min(90vw, 800px); max-height: 90vh; display: flex; flex-direction: column; overflow: hidden; }
    .modal-header { display: flex; justify-content: space-between; align-items: center; padding: 14px 16px; border-bottom: 1px solid var(--border); }
    .modal-title { font-weight: 600; font-size: 15px; }
    .modal-close { background: transparent; border: none; color: var(--text); font-size: 20px; cursor: pointer; }
    .modal-body { flex: 1; overflow: auto; padding: 16px; display: flex; flex-direction: column; gap: 16px; align-items: center; }
    .modal-image { max-width: 100%; max-height: 50vh; border-radius: 8px; border: 1px solid var(--border); }
    .modal-controls { padding: 14px 16px; border-top: 1px solid var(--border); background: #0b1220; display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
    .ctrl-group { display: flex; flex-direction: column; gap: 6px; }
    .ctrl-label { font-size: 11px; color: var(--text-dim); }
    .ctrl-row { display: flex; gap: 8px; align-items: center; }
    input[type=range] { width: 140px; }
    input[type=number] { width: 60px; background: #090e1a; color: var(--text); border: 1px solid var(--border); border-radius: 6px; padding: 4px 6px; font-size: 12px; }

  </style>
</head>
<body>
  <div class="app-container">
    <!-- Top Nav -->
    <header class="top-bar">
      <div class="brand">
        <span class="status-dot" id="statusDot"></span>
        <div>
          <span class="brand-title">Harold</span>
          <span class="brand-subtitle">v1</span>
        </div>
      </div>
      <div class="top-actions">
        <button class="btn-ghost" id="clearBtn" title="Clear chat view">Clear</button>
        <button class="btn-ghost" id="selftalkToggle" title="Toggle Harold Self-Talk">Self-Talk</button>
      </div>
    </header>

    <div id="startup-warning">
      <span>⏳</span> Harold is warming up internal models. First response can take 30–60 seconds...
    </div>

    <!-- Main Workspace -->
    <div class="main-body">
      <!-- Main Chat Area -->
      <section class="chat-view">
        <div id="log"></div>

        <!-- Input Bar -->
        <footer class="bottom-section">
          <div class="input-row">
            <div class="textarea-wrapper">
              <textarea id="prompt" placeholder="Message Harold... (Enter to send, Shift+Enter for newline)" rows="1"></textarea>
            </div>
            <button class="action-btn btn-steer" id="steer" title="Prioritize guidance next">Steer</button>
            <button class="action-btn btn-send" id="send">Send</button>
            <button class="action-btn img-upload-btn" id="imgUploadBtn" title="Upload image">📷</button>
            <input type="file" id="imgInput" accept="image/*" />
          </div>
          <div class="footer-bar">
            <span id="queue-status">Ready</span>
            <div class="footer-hints">
              Try <code>/selftalk</code> · <code>/status</code>
            </div>
          </div>
        </footer>
      </section>

      <!-- Self-Talk Drawer -->
      <aside id="selftalkPanel">
        <div class="st-bar">
          <span>Continuous Self-Talk</span>
          <button class="btn-ghost" id="closeStBtn" style="padding: 2px 7px; font-size: 11px;">✕</button>
        </div>
        <div id="selftalkLog"></div>
      </aside>
    </div>
  </div>

  <script>
    const log = document.getElementById('log');
    const promptEl = document.getElementById('prompt');
    const sendBtn = document.getElementById('send');
    const steerBtn = document.getElementById('steer');
    const queueStatus = document.getElementById('queue-status');
    const statusDot = document.getElementById('statusDot');
    const startupWarning = document.getElementById('startup-warning');
    const selftalkPanel = document.getElementById('selftalkPanel');
    const selftalkToggle = document.getElementById('selftalkToggle');
    const closeStBtn = document.getElementById('closeStBtn');
    const clearBtn = document.getElementById('clearBtn');
    const selftalkLog = document.getElementById('selftalkLog');

    const conversationHistory = [];
    const messageQueue = [];
    const MAX_QUEUED_MESSAGES = 20;
    let processingQueue = false;

    // Auto-resizing textarea
    promptEl.addEventListener('input', () => {
      promptEl.style.height = 'auto';
      promptEl.style.height = Math.min(promptEl.scrollHeight, 160) + 'px';
    });

    function addMessage(role, text) {
      const row = document.createElement('div');
      row.className = 'msg-row ' + role;

      const author = document.createElement('div');
      author.className = 'msg-author';
      author.textContent = role === 'user' ? 'You' : (role === 'error' ? 'System' : 'Harold');

      const bubble = document.createElement('div');
      bubble.className = 'msg-bubble';

      // Parse code blocks ```lang ... ``` and images ![alt](url)
      const parts = [];
      let remaining = text;
      const codeBlockRe = /```(\w*)\n([\s\S]*?)```/g;
      const imageRe = /!\[([^\]]*)\]\(([^)]+)\)/g;

      let lastIdx = 0;
      let m;
      const tokens = [];

      // Find all code blocks and image/video/audio tags
      let events = [];
      let re;
      re = /```(\w*)\n([\s\S]*?)```/g;
      while ((m = re.exec(text))) {
        events.push({ type: 'code', start: m.index, end: re.lastIndex, lang: m[1] || 'text', code: m[2] });
      }
      re = /!\[([^\]]*)\]\(([^)]+)\)/g;
      while ((m = re.exec(text))) {
        const url = m[2];
        const lower = url.toLowerCase();
        let mediaType = 'image';
        if (lower.match(/\.(gif|mp4|webm|avi)(\?.*)?$/)) mediaType = 'video';
        else if (lower.match(/\.(wav|mp3|ogg|flac)(\?.*)?$/)) mediaType = 'audio';
        events.push({ type: mediaType, start: m.index, end: re.lastIndex, alt: m[1], url: url });
      }
      events.sort((a, b) => a.start - b.start);

      let cursor = 0;
      for (const ev of events) {
        if (ev.start > cursor) {
          const txt = document.createTextNode(text.slice(cursor, ev.start));
          tokens.push({ type: 'text', node: txt });
        }
        if (ev.type === 'code') {
          tokens.push({ type: 'code', lang: ev.lang, code: ev.code });
        } else if (ev.type === 'image') {
          tokens.push({ type: 'image', alt: ev.alt, url: ev.url });
        }
        cursor = ev.end;
      }
      if (cursor < text.length) {
        tokens.push({ type: 'text', node: document.createTextNode(text.slice(cursor)) });
      }

      for (const t of tokens) {
        if (t.type === 'text') {
          bubble.appendChild(t.node);
        } else if (t.type === 'code') {
          const pre = document.createElement('pre');
          pre.className = 'code-block';
          const code = document.createElement('code');
          code.className = 'lang-' + t.lang;
          code.textContent = t.code;
          pre.appendChild(code);

          const copy = document.createElement('button');
          copy.className = 'code-copy';
          copy.textContent = 'Copy';
          copy.onclick = () => {
            navigator.clipboard.writeText(t.code);
            copy.textContent = 'Copied!';
            setTimeout(() => copy.textContent = 'Copy', 1500);
          };

          const wrap = document.createElement('div');
          wrap.className = 'code-wrap';
          wrap.appendChild(pre);
          wrap.appendChild(copy);
          bubble.appendChild(wrap);
        } else if (t.type === 'video') {
          const vidWrap = document.createElement('div');
          vidWrap.className = 'msg-video-wrap';
          const vid = document.createElement('video');
          vid.src = t.url.startsWith('http') ? t.url : (t.url.startsWith('/') ? t.url : '/' + t.url);
          vid.alt = t.alt || 'video';
          vid.className = 'msg-video';
          vid.controls = true;
          vid.autoplay = true;
          vid.muted = true;
          vid.style.maxWidth = '100%';
          vid.style.maxHeight = '400px';
          vid.style.borderRadius = '10px';
          vid.style.border = '1px solid var(--border)';
          vidWrap.appendChild(vid);

          const actions = document.createElement('div');
          actions.className = 'img-actions';

          const dlBtn = document.createElement('button');
          dlBtn.className = 'img-btn';
          dlBtn.textContent = 'Download';
          dlBtn.onclick = () => {
            const a = document.createElement('a');
            a.href = vid.src;
            a.download = t.alt || 'video.gif';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
          };
          actions.appendChild(dlBtn);

          vidWrap.appendChild(actions);

          const cap = document.createElement('div');
          cap.className = 'msg-video-cap';
          cap.textContent = t.alt || 'Video';
          vidWrap.appendChild(cap);
          bubble.appendChild(vidWrap);
        } else if (t.type === 'audio') {
          const audWrap = document.createElement('div');
          audWrap.className = 'msg-audio-wrap';
          const aud = document.createElement('audio');
          aud.src = t.url.startsWith('http') ? t.url : (t.url.startsWith('/') ? t.url : '/' + t.url);
          aud.controls = true;
          aud.autoplay = true;
          aud.muted = false;
          aud.style.width = '100%';
          audWrap.appendChild(aud);

          const actions = document.createElement('div');
          actions.className = 'img-actions';

          const dlBtn = document.createElement('button');
          dlBtn.className = 'img-btn';
          dlBtn.textContent = 'Download';
          dlBtn.onclick = () => {
            const a = document.createElement('a');
            a.href = aud.src;
            a.download = t.alt || 'audio.wav';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
          };
          actions.appendChild(dlBtn);

          audWrap.appendChild(actions);

          const cap = document.createElement('div');
          cap.className = 'msg-audio-cap';
          cap.textContent = t.alt || 'Audio';
          audWrap.appendChild(cap);
          bubble.appendChild(audWrap);
        } else if (t.type === 'image') {
      }

      row.appendChild(author);
      row.appendChild(bubble);
      log.appendChild(row);
      log.scrollTop = log.scrollHeight;
    }

    function addToolLine(ev) {
      const card = document.createElement('details');
      card.className = 'tool-card';
      const head = document.createElement('summary');
      const ok = ev.status === 'ok';

      const icon = document.createElement('span');
      icon.className = 'status-icon ' + (ok ? 'ok' : 'err');
      icon.textContent = ok ? '✓' : '✗';
      head.appendChild(icon);

      const ms = typeof ev.duration_ms === 'number' ? ` (${ev.duration_ms}ms)` : '';
      head.appendChild(document.createTextNode(' Tool: ' + (ev.label || ev.name) + ms));
      card.appendChild(head);

      const pre = document.createElement('pre');
      const args = Object.entries(ev.args || {}).map(([k, v]) => `${k}: ${v}`).join('\n');
      pre.textContent = (args ? args + '\n' : '') + (ev.summary ? '→ ' + ev.summary : '');
      card.appendChild(pre);

      log.appendChild(card);
      log.scrollTop = log.scrollHeight;
    }

    // Self-talk drawer
    function toggleSelfTalkPanel() {
      const show = selftalkPanel.style.display !== 'flex';
      selftalkPanel.style.display = show ? 'flex' : 'none';
      selftalkToggle.classList.toggle('active', show);
    }
    selftalkToggle.addEventListener('click', toggleSelfTalkPanel);
    closeStBtn.addEventListener('click', () => {
      selftalkPanel.style.display = 'none';
      selftalkToggle.classList.remove('active');
    });

    clearBtn.addEventListener('click', () => {
      log.innerHTML = '';
      addMessage('bot', 'Conversation cleared. Ready for your query.');
    });

    const SELF_TALK_POLL_MS = 4000;
    let selfTalkIndex = 0;
    let selfTalkTimer = null;
    let selfTalkTopic = '';

    function addSelftalkLine(cls, text) {
      const turn = document.createElement('div');
      turn.className = 'st-turn ' + cls;
      turn.textContent = text;
      selftalkLog.appendChild(turn);
      selftalkLog.scrollTop = selftalkLog.scrollHeight;
    }

    function renderSelfTalkTurn(turn) {
      const role = turn.role || '?';
      if (role === 'system') return;
      const label = {instructor: 'Instructor', learner: 'Learner', critic: 'Critic'}[role] || role;
      const topic = turn.topic || '';
      if (topic && topic !== selfTalkTopic) {
        selfTalkTopic = topic;
        const tag = document.createElement('div');
        tag.className = 'st-topic-tag';
        tag.textContent = 'Topic: ' + topic;
        selftalkLog.appendChild(tag);
      }
      const checked = (turn.agreement > 1) ? ` [${turn.agreement} agreed]` : '';
      const via = turn.provider && role !== 'critic' ? ` (${turn.provider})` : '';
      addSelftalkLine(role, `${label}${via}${checked}: ${turn.text}`);
    }

    async function pollSelfTalk() {
      try {
        const res = await fetch(`/api/selftalk/thread?after=${selfTalkIndex}`);
        if (!res.ok) return;
        const data = await res.json();
        for (const turn of (data.turns || [])) renderSelfTalkTurn(turn);
        if (typeof data.next === 'number') selfTalkIndex = data.next;
      } catch (_err) {}
    }

    function startSelfTalkPolling() {
      if (selfTalkTimer !== null) return;
      selfTalkTimer = setInterval(pollSelfTalk, SELF_TALK_POLL_MS);
      void pollSelfTalk();
    }

    function updateQueueStatus(activeText = null) {
      const pending = messageQueue.length;
      if (processingQueue) {
        statusDot.className = 'status-dot busy';
        queueStatus.className = 'busy';
        queueStatus.textContent = activeText || (pending ? `Generating (${pending} queued)` : 'Generating...');
      } else {
        statusDot.className = 'status-dot';
        queueStatus.className = '';
        queueStatus.textContent = pending ? `${pending} queued` : 'Ready';
      }
    }

    function enqueuePrompt(steer = false) {
      const prompt = promptEl.value.trim();
      if (!prompt) return;
      if (messageQueue.length >= MAX_QUEUED_MESSAGES) {
        addMessage('error', `Queue is full (max ${MAX_QUEUED_MESSAGES} messages).`);
        return;
      }
      promptEl.value = '';
      promptEl.style.height = 'auto';

      const item = {prompt, steer};
      if (steer) {
        messageQueue.unshift(item);
        addMessage('user', '⚡ Steering: ' + prompt);
      } else {
        messageQueue.push(item);
        addMessage('user', prompt);
      }
      updateQueueStatus();
      void processQueue();
    }

    async function processQueue() {
      if (processingQueue) return;
      processingQueue = true;
      if (startupWarning) startupWarning.style.display = 'flex';

      while (messageQueue.length) {
        const item = messageQueue.shift();
        updateQueueStatus(item.steer ? 'Applying steering instruction...' : 'Harold is generating reply...');
        try {
          const res = await fetch('/api/chat', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({prompt: item.prompt, history: conversationHistory.slice(-12)})
          });
          const responseText = await res.text();
          let data = null;
          try {
            data = JSON.parse(responseText);
          } catch (_parseError) {
            const detail = responseText.replace(/\s+/g, ' ').trim().slice(0, 240);
            addMessage('error', `Server returned non-JSON (HTTP ${res.status}). ${detail || 'Please retry shortly.'}`);
          }
          if (data !== null) {
            if (!res.ok) {
              addMessage('error', 'Error: ' + (data.error || 'Request failed'));
            } else {
              (data.tools || []).forEach(addToolLine);
              addMessage('bot', data.response);
              if (/^\/selftalk\b/i.test(item.prompt)) startSelfTalkPolling();
              conversationHistory.push(
                {role: 'user', content: item.prompt},
                {role: 'assistant', content: data.response}
              );
              if (conversationHistory.length > 12) conversationHistory.splice(0, conversationHistory.length - 12);
            }
          }
        } catch (err) {
          addMessage('error', 'Network error: ' + err.message);
        }
        updateQueueStatus();
      }

      processingQueue = false;
      if (startupWarning) startupWarning.style.display = 'none';
      updateQueueStatus();
      promptEl.focus();
    }

    // Init
    startSelfTalkPolling();
    sendBtn.addEventListener('click', () => enqueuePrompt(false));
    steerBtn.addEventListener('click', () => enqueuePrompt(true));
    promptEl.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        enqueuePrompt(false);
      }
    });

    addMessage('bot', 'Harold online. Fast, memory-linked AI assistant ready.');

    // Image upload
    const imgUploadBtn = document.getElementById('imgUploadBtn');
    const imgInput = document.getElementById('imgInput');
    imgUploadBtn.addEventListener('click', () => imgInput.click());
    imgInput.addEventListener('change', async () => {
      const file = imgInput.files[0];
      if (!file) return;
      const form = new FormData();
      form.append('file', file);
      imgUploadBtn.disabled = true;
      imgUploadBtn.textContent = '⏳';
      try {
        const res = await fetch('/api/images/upload', { method: 'POST', body: form });
        const data = await res.json();
        if (data.url) {
          promptEl.value = (promptEl.value ? promptEl.value + '\n' : '') + '![Image](' + data.url + ')';
        } else {
          addMessage('error', 'Upload failed: ' + (data.error || 'unknown'));
        }
      } catch (err) {
        addMessage('error', 'Upload error: ' + err.message);
      } finally {
        imgUploadBtn.disabled = false;
        imgUploadBtn.textContent = '📷';
        imgInput.value = '';
      }
    });

    // Image edit modal
    const modalOverlay = document.createElement('div');
    modalOverlay.className = 'modal-overlay';
    modalOverlay.innerHTML = `
      <div class="modal">
        <div class="modal-header">
          <span class="modal-title">Edit Image</span>
          <button class="modal-close">&times;</button>
        </div>
        <div class="modal-body">
          <img class="modal-image" id="modalImage" alt="Editing preview" />
        </div>
        <div class="modal-controls">
          <div class="ctrl-group">
            <span class="ctrl-label">Action</span>
            <select id="editAction">
              <option value="grayscale">Grayscale</option>
              <option value="invert">Invert</option>
              <option value="blur">Blur</option>
              <option value="sharpen">Sharpen</option>
              <option value="resize">Resize</option>
              <option value="crop">Crop</option>
              <option value="brighten">Brighten</option>
              <option value="contrast">Contrast</option>
            </select>
          </div>
          <div class="ctrl-row">
            <span class="ctrl-label">Width</span>
            <input type="number" id="editWidth" placeholder="px" />
          </div>
          <div class="ctrl-row">
            <span class="ctrl-label">Height</span>
            <input type="number" id="editHeight" placeholder="px" />
          </div>
          <div class="ctrl-row">
            <span class="ctrl-label">Factor</span>
            <input type="range" id="editFactor" min="0.1" max="3.0" step="0.1" value="1.2" />
            <span id="editFactorVal">1.2</span>
          </div>
          <div class="ctrl-row">
            <span class="ctrl-label">Left</span>
            <input type="number" id="editLeft" placeholder="px" />
          </div>
          <div class="ctrl-row">
            <span class="ctrl-label">Top</span>
            <input type="number" id="editTop" placeholder="px" />
          </div>
          <div class="ctrl-row">
            <span class="ctrl-label">Right</span>
            <input type="number" id="editRight" placeholder="px" />
          </div>
          <div class="ctrl-row">
            <span class="ctrl-label">Bottom</span>
            <span class="ctrl-label">Bottom</span>
            <input type="number" id="editBottom" placeholder="px" />
          </div>
          <button class="img-btn primary" id="applyEditBtn">Apply Edit</button>
          <button class="img-btn" id="downloadEditBtn" style="display:none">Download Result</button>
        </div>
      </div>
    `;
    document.body.appendChild(modalOverlay);

    let currentModalUrl = '';
    let currentModalResult = '';

    document.querySelector('.modal-close').onclick = () => {
      modalOverlay.classList.remove('open');
    };
    modalOverlay.onclick = (e) => {
      if (e.target === modalOverlay) modalOverlay.classList.remove('open');
    };

    const editActionSelect = document.getElementById('editAction');
    const editFactorInput = document.getElementById('editFactor');
    const editFactorVal = document.getElementById('editFactorVal');
    editFactorInput.oninput = () => { editFactorVal.textContent = editFactorInput.value; };

    document.getElementById('applyEditBtn').onclick = async () => {
      if (!currentModalUrl) return;
      const action = editActionSelect.value;
      const width = document.getElementById('editWidth').value || undefined;
      const height = document.getElementById('editHeight').value || undefined;
      const left = document.getElementById('editLeft').value || undefined;
      const top = document.getElementById('editTop').value || undefined;
      const right = document.getElementById('editRight').value || undefined;
      const bottom = document.getElementById('editBottom').value || undefined;
      const factor = parseFloat(editFactorInput.value);

      const payload = { url: currentModalUrl, action };
      if (width) payload.width = parseInt(width);
      if (height) payload.height = parseInt(height);
      if (left !== undefined) payload.left = parseInt(left);
      if (top !== undefined) payload.top = parseInt(top);
      if (right !== undefined) payload.right = parseInt(right);
      if (bottom !== undefined) payload.bottom = parseInt(bottom);
      if (factor) payload.factor = factor;

      try {
        const res = await fetch('/api/images/edit', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
        const data = await res.json();
        if (data.url) {
          currentModalResult = data.url;
          document.getElementById('modalImage').src = data.url + '?t=' + Date.now();
          document.getElementById('downloadEditBtn').style.display = 'inline-block';
          addMessage('bot', 'Edited image: ![Edited](' + data.url + ')');
        } else {
          addMessage('error', 'Edit failed: ' + (data.error || 'unknown'));
        }
      } catch (err) {
        addMessage('error', 'Edit error: ' + err.message);
      }
    };

    document.getElementById('downloadEditBtn').onclick = () => {
      if (!currentModalResult) return;
      const a = document.createElement('a');
      a.href = currentModalResult;
      a.download = 'edited-image.png';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    };

    window.openImageModal = function(url, alt) {
      currentModalUrl = url;
      currentModalResult = '';
      document.getElementById('modalImage').src = url;
      document.getElementById('downloadEditBtn').style.display = 'none';
      modalOverlay.classList.add('open');
    };
  </script>
</body>
</html>"""
    return Response(html, mimetype="text/html")


@app.get("/admin")
def admin_index() -> Response:
    ok, error = _admin_enabled_and_configured()
    if not ok:
        return error, 503

    html = r"""<!doctype html>
<html>
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Harold Admin</title>
  <style>
    :root {
      --bg: #0b1220;
      --panel: #101826;
      --text: #e5e7eb;
      --muted: #94a3b8;
      --accent: #22c55e;
      --danger: #ef4444;
      --border: #243044;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, Liberation Mono, monospace;
      background: radial-gradient(circle at top, #17243a, var(--bg));
      color: var(--text);
      min-height: 100vh;
      padding: 20px;
    }
    .container { width: min(980px, 100%); margin: 0 auto; }
    h1 { margin: 0 0 16px; font-size: 20px; }
    .grid {
      display: grid;
      grid-template-columns: 1fr;
      gap: 14px;
    }
    .card {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 14px;
    }
    .row { display: grid; grid-template-columns: 1fr; gap: 8px; margin-bottom: 10px; }
    label { color: var(--muted); font-size: 12px; }
    input, textarea {
      width: 100%;
      background: #0a111e;
      color: var(--text);
      border: 1px solid #2c3a52;
      border-radius: 8px;
      padding: 10px;
      font: inherit;
    }
    textarea { min-height: 110px; resize: vertical; }
    button {
      border: 0;
      background: var(--accent);
      color: #052e16;
      font-weight: 700;
      padding: 10px 14px;
      border-radius: 8px;
      cursor: pointer;
      margin-right: 8px;
      margin-bottom: 8px;
    }
    .danger { background: var(--danger); color: white; }
    pre {
      background: #0a111e;
      border: 1px solid #2c3a52;
      border-radius: 8px;
      padding: 10px;
      white-space: pre-wrap;
      word-break: break-word;
      margin: 0;
      min-height: 80px;
    }
    .small { font-size: 12px; color: var(--muted); }
  </style>
</head>
<body>
  <div class=\"container\">
    <h1>Harold Admin Panel</h1>
    <div class=\"grid\">
      <div class=\"card\">
        <div class=\"row\">
          <label>Admin API Key</label>
          <input id=\"adminKey\" type=\"password\" placeholder=\"Enter ADMIN_API_KEY\" />
        </div>
        <button id=\"saveKey\">Save Key in This Browser</button>
        <button class=\"danger\" id=\"clearKey\">Clear Key</button>
        <div class=\"small\">Key stays in this browser localStorage only. Never expose it publicly.</div>
      </div>

      <div class=\"card\">
        <h3>Insert Knowledge Entry</h3>
        <div class=\"row\">
          <label>Topic</label>
          <input id=\"topic\" placeholder=\"e.g., transformers\" />
        </div>
        <div class=\"row\">
          <label>Answer</label>
          <textarea id=\"answer\" placeholder=\"Provide concise, factual answer text...\"></textarea>
        </div>
        <button id=\"addKnowledge\">Add Knowledge</button>
      </div>

      <div class=\"card\">
        <h3>Queue Learning Topic</h3>
        <div class=\"row\">
          <label>Topic</label>
          <input id=\"learnTopic\" placeholder=\"e.g., distributed systems\" />
        </div>
        <button id=\"queueTopic\">Queue Topic</button>
        <button id=\"flushSync\">Force Sync Flush</button>
      </div>

      <div class=\"card\">
        <h3>Status</h3>
        <button id=\"refreshStatus\">Refresh Status</button>
        <button id=\"ftpStatus\">FTP Status</button>
        <button id=\"listKnowledge\">List Knowledge</button>
        <pre id=\"output\">Ready.</pre>
      </div>
    </div>
  </div>

  <script>
    const out = document.getElementById('output');
    const keyInput = document.getElementById('adminKey');

    function show(obj) {
      out.textContent = typeof obj === 'string' ? obj : JSON.stringify(obj, null, 2);
    }

    function getKey() {
      return localStorage.getItem('peakebot_admin_key') || '';
    }

    function setKey(k) {
      localStorage.setItem('peakebot_admin_key', k || '');
    }

    async function api(path, method = 'GET', body = null) {
      const key = getKey().trim();
      if (!key) throw new Error('Admin key is required');
      const headers = {'X-Admin-Key': key};
      if (body) headers['Content-Type'] = 'application/json';
      const res = await fetch(path, {
        method,
        headers,
        body: body ? JSON.stringify(body) : undefined
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.error || ('HTTP ' + res.status));
      }
      return data;
    }

    keyInput.value = getKey();

    document.getElementById('saveKey').onclick = () => {
      setKey(keyInput.value.trim());
      show('Admin key saved in this browser.');
    };

    document.getElementById('clearKey').onclick = () => {
      setKey('');
      keyInput.value = '';
      show('Admin key cleared.');
    };

    document.getElementById('addKnowledge').onclick = async () => {
      try {
        const topic = document.getElementById('topic').value.trim();
        const answer = document.getElementById('answer').value.trim();
        const data = await api('/api/admin/knowledge', 'POST', {topic, answer});
        show(data);
      } catch (e) {
        show('Error: ' + e.message);
      }
    };

    document.getElementById('queueTopic').onclick = async () => {
      try {
        const topic = document.getElementById('learnTopic').value.trim();
        const data = await api('/api/admin/learning-topic', 'POST', {topic});
        show(data);
      } catch (e) {
        show('Error: ' + e.message);
      }
    };

    document.getElementById('flushSync').onclick = async () => {
      try {
        const data = await api('/api/admin/flush-sync', 'POST');
        show(data);
      } catch (e) {
        show('Error: ' + e.message);
      }
    };

    document.getElementById('refreshStatus').onclick = async () => {
      try {
        const data = await api('/api/admin/status');
        show(data);
      } catch (e) {
        show('Error: ' + e.message);
      }
    };

    document.getElementById('listKnowledge').onclick = async () => {
      try {
        const data = await api('/api/admin/knowledge');
        show(data);
      } catch (e) {
        show('Error: ' + e.message);
      }
    };

      document.getElementById('ftpStatus').onclick = async () => {
        try {
          const data = await api('/api/admin/ftp-status');
          show(data);
        } catch (e) {
          show('Error: ' + e.message);
        }
      };
  </script>
</body>
</html>
"""
    return Response(html, mimetype="text/html")


@app.get("/api/admin/status")
def admin_status() -> Response:
    ok, error = _admin_enabled_and_configured()
    if not ok:
        return error, 503
    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
    if not _check_admin_rate_limit(client_ip):
        return jsonify({"error": "admin rate limit exceeded"}), 429
    if not _is_admin_authorized(request):
        return jsonify({"error": "unauthorized"}), 401
    return jsonify(get_growth_snapshot())


@app.get("/api/admin/knowledge")
def admin_list_knowledge() -> Response:
    ok, error = _admin_enabled_and_configured()
    if not ok:
        return error, 503
    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
    if not _check_admin_rate_limit(client_ip):
        return jsonify({"error": "admin rate limit exceeded"}), 429
    if not _is_admin_authorized(request):
        return jsonify({"error": "unauthorized"}), 401
    return jsonify({"items": list_base_knowledge_entries(limit=300)})


@app.post("/api/admin/knowledge")
def admin_add_knowledge() -> Response:
    ok, error = _admin_enabled_and_configured()
    if not ok:
        return error, 503
    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
    if not _check_admin_rate_limit(client_ip):
        return jsonify({"error": "admin rate limit exceeded"}), 429
    if not _is_admin_authorized(request):
        return jsonify({"error": "unauthorized"}), 401
    payload = request.get_json(silent=True) or {}
    topic = str(payload.get("topic", "")).strip()
    answer = str(payload.get("answer", "")).strip()
    try:
        saved = add_base_knowledge_entry(topic, answer)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"ok": True, "saved": saved})


@app.post("/api/admin/learning-topic")
def admin_queue_learning_topic() -> Response:
    ok, error = _admin_enabled_and_configured()
    if not ok:
        return error, 503
    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
    if not _check_admin_rate_limit(client_ip):
        return jsonify({"error": "admin rate limit exceeded"}), 429
    if not _is_admin_authorized(request):
        return jsonify({"error": "unauthorized"}), 401
    payload = request.get_json(silent=True) or {}
    topic = str(payload.get("topic", "")).strip()
    try:
        queue_learning_topic(topic)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"ok": True, "queued_topic": topic})


@app.post("/api/admin/flush-sync")
def admin_flush_sync() -> Response:
    ok, error = _admin_enabled_and_configured()
    if not ok:
        return error, 503
    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
    if not _check_admin_rate_limit(client_ip):
        return jsonify({"error": "admin rate limit exceeded"}), 429
    if not _is_admin_authorized(request):
        return jsonify({"error": "unauthorized"}), 401
    try:
        flush_sync_tasks()
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    return jsonify({"ok": True, "message": "sync tasks flushed"})


@app.post("/api/admin/archive-sync")
def admin_archive_sync() -> Response:
    """Force an archive sync: push local session logs/notes to FTP and pull knowledge down."""
    ok, error = _admin_enabled_and_configured()
    if not ok:
        return error, 503
    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
    if not _check_admin_rate_limit(client_ip):
        return jsonify({"error": "admin rate limit exceeded"}), 429
    if not _is_admin_authorized(request):
        return jsonify({"error": "unauthorized"}), 401
    try:
        report = startup_ftp_sync()
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
    return jsonify({"ok": bool(report.get("ok")), "report": report})


@app.post("/api/admin/organize-memory")
def admin_organize_memory() -> Response:
    """Force a memory organization pass: deduplicate, re-categorize, consolidate,
    and build an organized knowledge base on the FTP ``Harold`` directory."""
    ok, error = _admin_enabled_and_configured()
    if not ok:
        return error, 503
    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
    if not _check_admin_rate_limit(client_ip):
        return jsonify({"error": "admin rate limit exceeded"}), 429
    if not _is_admin_authorized(request):
        return jsonify({"error": "unauthorized"}), 401
    try:
        store = _get_mcf_memory_store()
        http = HttpRecallCoordinator()
        report = sync_and_organize(store, force=True, http=http)
        return jsonify({"ok": True, "report": report})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.post("/api/admin/post-daily-update")
def admin_post_daily_update() -> Response:
    """Force-post the daily Ecency/Hive community update on demand."""
    ok, error = _admin_enabled_and_configured()
    if not ok:
        return error, 503
    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
    if not _check_admin_rate_limit(client_ip):
        return jsonify({"error": "admin rate limit exceeded"}), 429
    if not _is_admin_authorized(request):
        return jsonify({"error": "unauthorized"}), 401
    try:
        store = _get_mcf_memory_store()
        result = post_daily_update(store)
        return jsonify({"ok": bool(result.get("ok")), "result": result})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.post("/api/admin/post-wave")
def admin_post_wave() -> Response:
    """Post (or dry-run) Harold's daily Hive Wave. Duplicate guards still apply."""
    ok, error = _admin_enabled_and_configured()
    if not ok:
        return error, 503
    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
    if not _check_admin_rate_limit(client_ip):
        return jsonify({"error": "admin rate limit exceeded"}), 429
    if not _is_admin_authorized(request):
        return jsonify({"error": "unauthorized"}), 401
    payload = request.get_json(silent=True) or {}
    try:
        result = harold_waves.maybe_post_wave(generate=_wave_text, dry_run=bool(payload.get("dry_run", True)))
        return jsonify({"ok": bool(result.get("ok")), "result": result})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.get("/api/admin/ftp-status")
def admin_ftp_status() -> Response:
    ok, error = _admin_enabled_and_configured()
    if not ok:
        return error, 503
    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
    if not _check_admin_rate_limit(client_ip):
        return jsonify({"error": "admin rate limit exceeded"}), 429
    if not _is_admin_authorized(request):
        return jsonify({"error": "unauthorized"}), 401
    return jsonify(get_ftp_status())


def _message_text(content) -> str:
    if isinstance(content, list):
        return "\n".join(
            str(part.get("text", "")) for part in content if isinstance(part, dict)
        ).strip()
    return str(content or "").strip()


@app.route("/v1/models", methods=["GET"])
def openai_models() -> Response:
    return jsonify({"object": "list", "data": [{"id": "harold", "object": "model", "owned_by": "harold"}]})


@app.route("/v1/chat/completions", methods=["POST", "OPTIONS"])
def openai_chat_completions() -> Response:
    """OpenAI-compatible wrapper so IDE extensions can use Harold as a model."""
    if request.method == "OPTIONS":
        return jsonify({"ok": True})
    if CHAT_API_KEY:
        incoming = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        if not hmac.compare_digest(incoming, CHAT_API_KEY):
            return jsonify({"error": {"message": "invalid api key", "type": "auth"}}), 401

    payload = request.get_json(silent=True) or {}
    messages = payload.get("messages")
    if not isinstance(messages, list):
        return jsonify({"error": {"message": "messages is required", "type": "invalid_request"}}), 400
    turns = [
        {"role": m.get("role"), "content": _message_text(m.get("content"))}
        for m in messages
        if isinstance(m, dict) and m.get("role") in {"user", "assistant"}
    ]
    last_msg = messages[-1] if messages else {}
    last_role = last_msg.get("role") if isinstance(last_msg, dict) else None
    if last_role not in {"user", "assistant", "tool"}:
        return jsonify({"error": {"message": "last message must be user, assistant, or tool", "type": "invalid_request"}}), 400
    if last_role == "user" and not _message_text(last_msg.get("content")):
        return jsonify({"error": {"message": "last user message must be non-empty", "type": "invalid_request"}}), 400

    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
    if not _check_rate_limit(client_ip):
        return jsonify({"error": {"message": "rate limit exceeded", "type": "rate_limit"}}), 429

    tools = payload.get("tools") or []
    if not isinstance(tools, list):
        tools = []

    tool_calls = None
    tool_log = []
    if tools:
        system_prompt, user_prompt = agent_tools.build_prompt(messages, tools)
        with _GENERATION_LOCK:
            try:
                result = _query_ai_providers_for_self_talk([("system", system_prompt), ("user", user_prompt)], purpose="single")
                text = next(iter(result.get("answers", {}).values()), "")
                if not text:
                    raise RuntimeError("no provider returned a response")
            except Exception as exc:
                return jsonify({"error": {"message": f"generation failed: {exc}", "type": "server_error"}}), 500
    else:
        user_msgs = [m for m in messages if isinstance(m, dict) and m.get("role") == "user"]
        prompt = _message_text(user_msgs[-1].get("content")) if user_msgs else ""
        history = normalize_history([m for m in messages if isinstance(m, dict) and m.get("role") in {"user", "assistant"}][:-1] if user_msgs else [])
        with _GENERATION_LOCK:
            try:
                with tool_events.capture() as tool_log:
                    text = generate_response(prompt, conversation_history=history)
            except Exception as exc:
                return jsonify({"error": {"message": f"generation failed: {exc}", "type": "server_error"}}), 500

    created = int(time.time())
    text = re.sub(r"\n*\(Answered via [^)]*\)\s*$", "", text).strip()
    if tools:
        tool_calls = agent_tools.parse_tool_calls(text, tools)
        if tool_calls:
            text = agent_tools.strip_tool_noise(text)
    else:
        tools_md = tool_events.format_markdown(tool_log)
        if tools_md:
            text = f"{tools_md}\n\n---\n\n{text}"
    completion_id = f"chatcmpl-harold-{created}"

    if payload.get("stream"):
        import json as _json

        def _sse():
            base = {"id": completion_id, "object": "chat.completion.chunk", "created": created, "model": "harold"}
            yield "data: " + _json.dumps({**base, "choices": [{"index": 0, "delta": {"role": "assistant", "content": text}, "finish_reason": None}]}) + "\n\n"
            yield "data: " + _json.dumps({**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}) + "\n\n"
            yield "data: [DONE]\n\n"

        return Response(_sse(), mimetype="text/event-stream")
    message = {"role": "assistant", "content": text}
    if tool_calls:
        message["tool_calls"] = tool_calls
        finish_reason = "tool_calls"
    else:
        finish_reason = "stop"

    if payload.get("stream"):
        import json as _json

        def _sse():
            base = {"id": completion_id, "object": "chat.completion.chunk", "created": created, "model": "harold"}
            delta = {"role": "assistant"}
            if text:
                delta["content"] = text
            if tool_calls:
                delta["tool_calls"] = [
                    {
                        "index": i,
                        "id": c["id"],
                        "type": "function",
                        "function": {
                            "name": c["function"]["name"],
                            "arguments": c["function"]["arguments"],
                        },
                    }
                    for i, c in enumerate(tool_calls)
                ]
            yield "data: " + _json.dumps({**base, "choices": [{"index": 0, "delta": delta, "finish_reason": None}]}) + "\n\n"
            yield "data: " + _json.dumps({**base, "choices": [{"index": 0, "delta": {}, "finish_reason": finish_reason}]}) + "\n\n"
            yield "data: [DONE]\n\n"

        return Response(_sse(), mimetype="text/event-stream")

    return jsonify({
        "id": completion_id,
        "object": "chat.completion",
        "created": created,
        "model": "harold",
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    })


@app.route("/api/chat", methods=["POST", "OPTIONS"])
def api_chat() -> Response:
    if request.method == "OPTIONS":
        return jsonify({"ok": True})

    payload = request.get_json(silent=True) or {}
    prompt = str(payload.get("prompt", "")).strip()
    if not prompt:
        return jsonify({"error": "prompt is required"}), 400

    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
    if not _check_rate_limit(client_ip):
        return jsonify({"error": "rate limit exceeded; try again shortly"}), 429

    history = normalize_history(payload.get("history", []))

    with _GENERATION_LOCK:
      try:
        with tool_events.capture() as tool_log:
          response = generate_response(prompt, conversation_history=history)
      except Exception as exc:
        return jsonify({"error": f"generation failed: {exc}"}), 500

    return jsonify({"response": response, "tools": tool_log})


# -- image endpoints -----------------------------------------------------------
IMAGE_DIR = os.path.join(os.path.dirname(__file__), "images")


def _ensure_image_dir() -> None:
    os.makedirs(IMAGE_DIR, exist_ok=True)


@app.get("/api/images")
def api_list_images() -> Response:
    _ensure_image_dir()
    result = []
    for root, _dirs, files in os.walk(IMAGE_DIR):
        for f in sorted(files):
            if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")):
                full = os.path.join(root, f)
                rel = os.path.relpath(full, IMAGE_DIR)
                result.append({
                    "path": rel,
                    "url": f"/images/{rel}",
                    "size": os.path.getsize(full),
                })
    return jsonify({"images": result})


@app.get("/images/<path:filename>")
def api_serve_image(filename: str) -> Response:
    _ensure_image_dir()
    return send_from_directory(IMAGE_DIR, filename)


@app.post("/api/images/upload")
def api_upload_image() -> Response:
    _ensure_image_dir()
    if "file" not in request.files:
        return jsonify({"error": "no file provided"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "no filename"}), 400
    safe = secure_filename(f.filename)
    if not safe.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")):
        return jsonify({"error": "unsupported image type"}), 400
    dest = os.path.join(IMAGE_DIR, safe)
    f.save(dest)
    return jsonify({"path": safe, "url": f"/images/{safe}", "size": os.path.getsize(dest)})


@app.post("/api/images/edit")
def api_edit_image() -> Response:
    _ensure_image_dir()
    payload = request.get_json(silent=True) or {}
    url = str(payload.get("url", "")).strip()
    action = str(payload.get("action", "")).strip()
    if not url or not action:
        return jsonify({"error": "url and action required"}), 400

    # Resolve URL to local file path
    local_path = None
    if url.startswith("/images/"):
        rel = url[len("/images/"):]
        local_path = os.path.join(IMAGE_DIR, rel)
    elif url.startswith("/"):
        local_path = url.lstrip("/")
    else:
        return jsonify({"error": "only local /images/ URLs supported"}), 400

    if not os.path.isfile(local_path):
        return jsonify({"error": "image not found"}), 404

    try:
        img = Image.open(local_path)
    except Exception as exc:
        return jsonify({"error": f"cannot open image: {exc}"}), 400

    try:
        if action == "resize":
            w = int(payload.get("width") or img.width)
            h = int(payload.get("height") or img.height)
            img = img.resize((w, h), Image.Resampling.LANCZOS)
        elif action == "crop":
            l = int(payload.get("left") or 0)
            t = int(payload.get("top") or 0)
            r = int(payload.get("right") or img.width)
            b = int(payload.get("bottom") or img.height)
            img = img.crop((l, t, r, b))
        elif action == "blur":
            r = float(payload.get("factor") or 2)
            img = img.filter(ImageFilter.GaussianBlur(radius=r))
        elif action == "sharpen":
            img = img.filter(ImageFilter.SHARPEN)
        elif action == "grayscale":
            img = img.convert("L").convert("RGB")
        elif action == "invert":
            img = ImageOps.invert(img.convert("RGB"))
        elif action == "brighten":
            f = float(payload.get("factor") or 1.2)
            img = ImageEnhance.Brightness(img).enhance(f)
        elif action == "contrast":
            f = float(payload.get("factor") or 1.2)
            img = ImageEnhance.Contrast(img).enhance(f)
        else:
            return jsonify({"error": f"unknown action: {action}"}), 400

        # Save as edited version
        base = os.path.splitext(os.path.basename(local_path))[0]
        ext = os.path.splitext(local_path)[1] or ".png"
        out_name = f"{base}_edited_{action}{ext}"
        out_path = os.path.join(IMAGE_DIR, out_name)
        img.save(out_path)

        return jsonify({"path": out_name, "url": f"/images/{out_name}", "size": os.path.getsize(out_path)})
    except Exception as exc:
        return jsonify({"error": f"edit failed: {exc}"}), 500


# -- video endpoints -----------------------------------------------------------
VIDEO_DIR = os.path.join(os.path.dirname(__file__), "videos")
MUSIC_DIR = os.path.join(os.path.dirname(__file__), "music")


def _ensure_video_dir() -> None:
    os.makedirs(VIDEO_DIR, exist_ok=True)


def _ensure_music_dir() -> None:
    os.makedirs(MUSIC_DIR, exist_ok=True)


@app.get("/api/videos")
def api_list_videos() -> Response:
    _ensure_video_dir()
    result = []
    for root, _dirs, files in os.walk(VIDEO_DIR):
        for f in sorted(files):
            if f.lower().endswith((".gif", ".mp4", ".webm", ".avi")):
                full = os.path.join(root, f)
                rel = os.path.relpath(full, VIDEO_DIR)
                result.append({
                    "path": rel,
                    "url": f"/videos/{rel}",
                    "size": os.path.getsize(full),
                })
    return jsonify({"videos": result})


@app.get("/videos/<path:filename>")
def api_serve_video(filename: str) -> Response:
    _ensure_video_dir()
    return send_from_directory(VIDEO_DIR, filename)


@app.get("/api/music")
def api_list_music() -> Response:
    _ensure_music_dir()
    result = []
    for root, _dirs, files in os.walk(MUSIC_DIR):
        for f in sorted(files):
            if f.lower().endswith((".wav", ".mp3", ".ogg", ".flac")):
                full = os.path.join(root, f)
                rel = os.path.relpath(full, MUSIC_DIR)
                result.append({
                    "path": rel,
                    "url": f"/music/{rel}",
                    "size": os.path.getsize(full),
                })
    return jsonify({"music": result})


@app.get("/music/<path:filename>")
def api_serve_music(filename: str) -> Response:
    _ensure_music_dir()
    return send_from_directory(MUSIC_DIR, filename)


# -- trading bridge endpoints ----------------------------------------------
# The trading bot runs locally and calls these over HTTP to ask Harold for
# guidance and to report outcomes back so Harold can learn what works.


def _is_trading_authorized(req) -> bool:
    incoming = (
        req.headers.get("X-Trading-Key", "")
        or req.headers.get("X-Admin-Key", "")
        or ""
    ).strip()
    if not incoming or not TRADING_API_KEY:
        return False
    return hmac.compare_digest(incoming, TRADING_API_KEY)


def _check_trading_rate_limit(client_ip: str) -> bool:
    now = time.time()
    window_start = now - _TRADING_RATE_WINDOW_SECONDS
    log = _TRADING_REQUEST_LOG[client_ip]
    while log and log[0] < window_start:
        log.popleft()
    if len(log) >= _TRADING_RATE_LIMIT_REQUESTS:
        return False
    log.append(now)
    return True


def _trading_guard(req):
    """Return an error Response when the caller is not allowed, else None."""
    if not TRADING_API_KEY:
        return jsonify({"error": "TRADING_API_KEY is not configured"}), 503
    if not _is_trading_authorized(req):
        return jsonify({"error": "unauthorized"}), 401
    client_ip = req.headers.get("X-Forwarded-For", req.remote_addr or "unknown").split(",")[0].strip()
    if not _check_trading_rate_limit(client_ip):
        return jsonify({"error": "rate limit exceeded; try again shortly"}), 429
    return None


@app.post("/api/trading/advise")
def api_trading_advise() -> Response:
    guard = _trading_guard(request)
    if guard is not None:
        return guard
    payload = request.get_json(silent=True) or {}
    context = payload.get("context") or {}
    if not isinstance(context, dict):
        return jsonify({"error": "context must be an object"}), 400
    question = str(payload.get("question", "")).strip()
    try:
        result = trading_advise(context, question)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": f"trading advice failed: {exc}"}), 500
    return jsonify(result)


@app.post("/api/trading/feedback")
def api_trading_feedback() -> Response:
    guard = _trading_guard(request)
    if guard is not None:
        return guard
    payload = request.get_json(silent=True) or {}
    key = str(payload.get("key", "")).strip()
    if not key:
        return jsonify({"error": "key is required"}), 400
    try:
        pnl = float(payload.get("pnl", 0) or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "pnl must be a number"}), 400
    try:
        if payload.get("lesson"):
            result = trading_record_lesson(
                key, str(payload["lesson"]),
                market=str(payload.get("market", "")),
                timeframe=str(payload.get("timeframe", "")),
            )
        else:
            result = trading_record_outcome(
                key, str(payload.get("outcome", "")),
                market=str(payload.get("market", "")),
                timeframe=str(payload.get("timeframe", "")),
                pnl=pnl,
                notes=str(payload.get("notes", "")),
            )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": f"trading feedback failed: {exc}"}), 500
    return jsonify(result)


@app.post("/api/trading/mechanism")
def api_trading_mechanism() -> Response:
    guard = _trading_guard(request)
    if guard is not None:
        return guard
    payload = request.get_json(silent=True) or {}
    key = str(payload.get("key", "")).strip()
    description = str(payload.get("description", "")).strip()
    tags = payload.get("tags") or []
    if not isinstance(tags, list):
        return jsonify({"error": "tags must be a list"}), 400
    try:
        result = trading_learn_mechanism(
            key, description,
            market=str(payload.get("market", "")),
            timeframe=str(payload.get("timeframe", "")),
            tags=[str(tag) for tag in tags],
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": f"mechanism learning failed: {exc}"}), 500
    return jsonify(result)


@app.get("/api/integrations/status")
def api_integrations_status() -> Response:
    """Get status of all integrations"""
    try:
        return jsonify(integration_manager.get_integration_status())
    except Exception as exc:
        return jsonify({"error": f"integration status check failed: {exc}"}), 500


@app.get("/api/quickbooks/financial-summary")
def api_quickbooks_summary() -> Response:
    """Get financial summary from QuickBooks"""
    days = request.args.get("days", 30, type=int)
    try:
        return jsonify(integration_manager.get_financial_summary(days))
    except Exception as exc:
        return jsonify({"error": f"QuickBooks summary failed: {exc}"}), 500


@app.post("/api/calendar/find-time")
def api_calendar_find_time() -> Response:
    """Find available time in Google Calendar"""
    payload = request.get_json(silent=True) or {}
    duration = float(payload.get("duration_hours", 1.0))
    search_days = int(payload.get("search_days", 7))
    try:
        return jsonify(integration_manager.find_meeting_time(duration, search_days))
    except Exception as exc:
        return jsonify({"error": f"Calendar time search failed: {exc}"}), 500


@app.post("/api/calendar/create-event")
def api_calendar_create_event() -> Response:
    """Create a new calendar event"""
    payload = request.get_json(silent=True) or {}
    summary = str(payload.get("summary", "")).strip()
    start_time = str(payload.get("start_time", "")).strip()
    duration = float(payload.get("duration_hours", 1.0))
    attendees = payload.get("attendees") or []
    
    if not summary:
        return jsonify({"error": "summary is required"}), 400
    if not start_time:
        return jsonify({"error": "start_time is required"}), 400
        
    try:
        return jsonify(integration_manager.schedule_business_meeting(
            summary, start_time, duration, attendees
        ))
    except Exception as exc:
        return jsonify({"error": f"Calendar event creation failed: {exc}"}), 500


@app.get("/api/trading/summary")
def api_trading_summary() -> Response:
    guard = _trading_guard(request)
    if guard is not None:
        return guard
    try:
        return jsonify(trading_summary())
    except Exception as exc:
        return jsonify({"error": f"trading summary failed: {exc}"}), 500


# -- code generation endpoints ----------------------------------------------
@app.get("/api/code/list")
def api_code_list() -> Response:
    """List files in the FTP code directory."""
    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
    if not _check_rate_limit(client_ip):
        return jsonify({"error": "rate limit exceeded; try again shortly"}), 429

    if not _ftp_model_credentials_configured():
        return jsonify({"error": "FTP is not configured"}), 503

    try:
        ftp = _ftp_connect_for_upload()
        try:
            base_dir = _resolved_ftp_base_dir().strip("/")
            files = []
            try:
                entries = ftp.nlst(base_dir or ".")
                for entry in entries:
                    name = entry.rsplit("/", 1)[-1]
                    if name and not name.startswith("."):
                        files.append(name)
            except ftplib.all_errors:
                pass
            return jsonify({"files": sorted(files)})
        finally:
            try:
                ftp.quit()
            except Exception:
                pass
    except Exception as exc:
        return jsonify({"error": f"FTP list failed: {exc}"}), 500


@app.post("/api/code/generate")
def api_code_generate() -> Response:
    """Ask Harold to generate code and upload it to FTP for download."""
    payload = request.get_json(silent=True) or {}
    prompt = str(payload.get("prompt", "")).strip()
    if not prompt:
        return jsonify({"error": "prompt is required"}), 400

    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
    if not _check_rate_limit(client_ip):
        return jsonify({"error": "rate limit exceeded; try again shortly"}), 429

    history = normalize_history(payload.get("history", []))

    try:
        response = _handle_code_generation_request(prompt)
    except Exception as exc:
        return jsonify({"error": f"code generation failed: {exc}"}), 500

    if not response:
        return jsonify({"error": "I didn't understand that as a code request. Try: 'write a python script to ...'"}), 400

    remember = None
    try:
        from peakebot import remember as _remember
        _remember(prompt, response)
    except Exception:
        pass

    return jsonify({"response": response})


@app.get("/api/code/download/<filename>")
def api_code_download(filename: str) -> Response:
    """Download a generated code file from FTP."""
    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
    if not _check_rate_limit(client_ip):
        return jsonify({"error": "rate limit exceeded; try again shortly"}), 429

    if not _ftp_model_credentials_configured():
        return jsonify({"error": "FTP is not configured"}), 503

    # Sanitize filename to prevent path traversal
    safe_name = re.sub(r"[^a-zA-Z0-9_.\-]", "_", filename)
    if safe_name != filename:
        return jsonify({"error": "invalid filename"}), 400

    try:
        ftp = _ftp_connect_for_upload()
        try:
            base_dir = _resolved_ftp_base_dir().strip("/")
            remote_name = f"{base_dir}/{safe_name}" if base_dir else safe_name
            import io as _io
            buf = _io.BytesIO()
            ftp.retrbinary(f"RETR {remote_name}", buf.write)
            buf.seek(0)
            data = buf.read()
        finally:
            try:
                ftp.quit()
            except Exception:
                pass

        ext = safe_name.rsplit(".", 1)[-1] if "." in safe_name else "txt"
        mime_map = {
            "py": "text/x-python",
            "js": "application/javascript",
            "sh": "text/x-shellscript",
            "html": "text/html",
            "css": "text/css",
            "sql": "text/sql",
            "go": "text/x-go",
            "rs": "text/x-rust",
            "java": "text/x-java",
            "cpp": "text/x-c++src",
            "rb": "text/x-ruby",
            "php": "text/x-php",
            "ts": "application/typescript",
            "txt": "text/plain",
        }
        mime = mime_map.get(ext, "application/octet-stream")
        return Response(
            data,
            mimetype=mime,
            headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
        )
    except ftplib.all_errors as exc:
        return jsonify({"error": f"FTP download failed: {exc}"}), 500
    except Exception as exc:
        return jsonify({"error": f"download failed: {exc}"}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
