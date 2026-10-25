import os
import threading
import time
import hmac
from collections import defaultdict, deque
from typing import Optional, Tuple
from datetime import datetime, timedelta
from flask import Flask, jsonify, request, Response
from my_ai.conversation import normalize_history

from peakebot import (
  _get_mcf_memory_store,
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

app = Flask(__name__)

# Initialize integration manager
integration_manager = IntegrationManager()

# Keep one generation at a time to avoid model state collisions.
_GENERATION_LOCK = threading.Lock()

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


@app.before_request
def _kickoff_ftp_startup_check() -> None:
  # Gunicorn has bound the listener; keep readiness requests fast during warm-up.
  _start_ftp_startup_sync()
  _start_model_warmup()
  if request.path != "/health":
    # Let the archive finish before handling real traffic.
    _FTP_STARTUP_SYNC_DONE.wait(timeout=_FTP_STARTUP_SYNC_TIMEOUT)


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


@app.get("/health")
def health() -> Response:
    return jsonify({"ok": True, "service": "peakebot-web"})


@app.get("/")
def index() -> Response:
    html = """<!doctype html>
<html>
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Harold Web</title>
  <style>
    :root {
      --bg: #0f172a;
      --panel: #111827;
      --text: #e5e7eb;
      --muted: #9ca3af;
      --accent: #22c55e;
      --error: #ef4444;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, Liberation Mono, monospace;
      background: radial-gradient(circle at top, #1f2937, var(--bg));
      color: var(--text);
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 16px;
    }
    .shell {
      width: min(900px, 100%);
      background: #0b1220;
      border: 1px solid #1f2937;
      border-radius: 14px;
      overflow: hidden;
      box-shadow: 0 24px 60px rgba(0,0,0,.45);
    }
    .bar {
      background: #0b1020;
      border-bottom: 1px solid #1f2937;
      padding: 10px 14px;
      display: flex;
      gap: 10px;
      align-items: center;
    }
    .dot { width: 10px; height: 10px; border-radius: 999px; }
    .d1 { background: #ef4444; }
    .d2 { background: #f59e0b; }
    .d3 { background: #22c55e; }
    .title { color: var(--muted); font-size: 13px; margin-left: 6px; }
    #log {
      height: 60vh;
      overflow: auto;
      padding: 14px;
      white-space: pre-wrap;
      line-height: 1.45;
      background: linear-gradient(180deg, #0b1220 0%, #0a1020 100%);
    }
    .u { color: #93c5fd; }
    .b { color: #86efac; }
    .e { color: var(--error); }
    .input {
      display: grid;
      grid-template-columns: 1fr auto auto;
      gap: 10px;
      border-top: 1px solid #1f2937;
      padding: 12px;
      background: #0b1020;
    }
    textarea {
      width: 100%;
      resize: vertical;
      min-height: 52px;
      max-height: 180px;
      background: #111827;
      color: var(--text);
      border: 1px solid #374151;
      border-radius: 8px;
      padding: 10px;
      font: inherit;
    }
    button {
      border: 0;
      background: var(--accent);
      color: #052e16;
      font-weight: 700;
      border-radius: 8px;
      padding: 0 16px;
      cursor: pointer;
    }
    #steer { background: #f59e0b; color: #451a03; }
    button:disabled { opacity: .6; cursor: not-allowed; }
    .hint {
      color: var(--muted);
      font-size: 12px;
      padding: 0 12px 12px;
    }
    #queue-status { color: var(--muted); font-size: 12px; padding: 0 12px 10px; }
  </style>
</head>
<body>
  <div class=\"shell\">
    <div class=\"bar\">
      <span class=\"dot d1\"></span>
      <span class=\"dot d2\"></span>
      <span class=\"dot d3\"></span>
      <span class=\"title\">Harold Public Terminal</span>
    </div>
    <div id=\"log\"></div>
    <div class=\"input\">
      <textarea id=\"prompt\" placeholder=\"Type your message...\"></textarea>
      <button id=\"send\">Send</button>
      <button id=\"steer\" title=\"Prioritize this instruction after the current reply\">Steer next</button>
    </div>
    <div id=\"queue-status\" aria-live=\"polite\">Ready.</div>
    <div class=\"hint\">Messages are sent in order. “Steer next” prioritizes guidance after Harold's current reply; it cannot change text already being generated. Avoid sensitive data.</div>
  </div>
  <script>
    const log = document.getElementById('log');
    const promptEl = document.getElementById('prompt');
    const sendBtn = document.getElementById('send');
    const steerBtn = document.getElementById('steer');
    const queueStatus = document.getElementById('queue-status');
    const conversationHistory = [];
    const messageQueue = [];
    const MAX_QUEUED_MESSAGES = 20;
    let processingQueue = false;
    let activeStatus = '';

    function addLine(cls, text) {
      const line = document.createElement('div');
      line.className = cls;
      line.textContent = text;
      log.appendChild(line);
      log.scrollTop = log.scrollHeight;
    }

    function updateQueueStatus(activeText = null) {
      if (activeText !== null) activeStatus = activeText;
      const pending = messageQueue.length;
      if (processingQueue) {
        queueStatus.textContent = activeStatus + (pending ? ` · ${pending} queued` : '');
      } else {
        queueStatus.textContent = pending ? `${pending} queued` : 'Ready.';
      }
    }

    function enqueuePrompt(steer = false) {
      const prompt = promptEl.value.trim();
      if (!prompt) return;
      if (messageQueue.length >= MAX_QUEUED_MESSAGES) {
        addLine('e', `Queue is full (maximum ${MAX_QUEUED_MESSAGES} waiting messages).`);
        return;
      }
      promptEl.value = '';
      const item = {prompt, steer};
      if (steer) {
        messageQueue.unshift(item);
        addLine('u', 'You (steering next): ' + prompt);
      } else {
        messageQueue.push(item);
        addLine('u', 'You: ' + prompt);
      }
      updateQueueStatus();
      void processQueue();
    }

    async function processQueue() {
      if (processingQueue) return;
      processingQueue = true;
      while (messageQueue.length) {
        const item = messageQueue.shift();
        updateQueueStatus(item.steer ? 'Applying steering instruction…' : 'Harold is responding…');
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
            addLine('e', `Server returned a non-JSON response (HTTP ${res.status}). ${detail || 'Please retry shortly.'}`);
          }
          if (data !== null) {
            if (!res.ok) {
              addLine('e', 'Error: ' + (data.error || 'Request failed'));
            } else {
              addLine('b', 'Harold: ' + data.response);
              conversationHistory.push(
                {role: 'user', content: item.prompt},
                {role: 'assistant', content: data.response}
              );
              if (conversationHistory.length > 12) conversationHistory.splice(0, conversationHistory.length - 12);
            }
          }
        } catch (err) {
          addLine('e', 'Network error: ' + err.message);
        }
        updateQueueStatus();
      }
      processingQueue = false;
      activeStatus = '';
      updateQueueStatus();
      promptEl.focus();
    }

    sendBtn.addEventListener('click', () => enqueuePrompt(false));
    steerBtn.addEventListener('click', () => enqueuePrompt(true));
    promptEl.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        enqueuePrompt(false);
      }
    });

    addLine('b', 'Harold: Online. Ask me anything.');
  </script>
</body>
</html>
"""
    return Response(html, mimetype="text/html")


@app.get("/admin")
def admin_index() -> Response:
    ok, error = _admin_enabled_and_configured()
    if not ok:
        return error, 503

    html = """<!doctype html>
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


@app.route("/api/chat", methods=["POST", "OPTIONS"])
def api_chat() -> Response:
    if request.method == "OPTIONS":
        return jsonify({"ok": True})
    # Optional API key for chat: when CHAT_API_KEY is set, callers must present
    # it via X-Api-Key so different apps get separate rate limits and access
    # control instead of sharing one public bucket.
    if CHAT_API_KEY:
        incoming = (request.headers.get("X-Api-Key", "") or "").strip()
        if not incoming or not hmac.compare_digest(incoming, CHAT_API_KEY):
            return jsonify({"error": "unauthorized"}), 401

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
        response = generate_response(prompt, conversation_history=history)
      except Exception as exc:
        return jsonify({"error": f"generation failed: {exc}"}), 500

    return jsonify({"response": response})


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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
