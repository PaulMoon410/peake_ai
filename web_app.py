import os
import threading
import time
import hmac
from collections import defaultdict, deque
from flask import Flask, jsonify, request, Response

from peakebot import (
  generate_response,
  add_base_knowledge_entry,
  list_base_knowledge_entries,
  queue_learning_topic,
  get_growth_snapshot,
  get_ftp_status,
  flush_sync_tasks,
)

app = Flask(__name__)

# Keep one generation at a time to avoid model state collisions.
_GENERATION_LOCK = threading.Lock()

# Lightweight in-memory per-IP rate limiter for public testing.
_RATE_WINDOW_SECONDS = 60
_RATE_LIMIT_REQUESTS = 15
_REQUEST_LOG = defaultdict(deque)
_ADMIN_RATE_WINDOW_SECONDS = 60
_ADMIN_RATE_LIMIT_REQUESTS = 40
_ADMIN_REQUEST_LOG = defaultdict(deque)

ADMIN_PANEL_ENABLED = os.getenv("ADMIN_PANEL_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "")


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


def _admin_enabled_and_configured() -> tuple[bool, Response | None]:
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
  <title>PeakeBot Web</title>
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
      grid-template-columns: 1fr auto;
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
    button:disabled { opacity: .6; cursor: not-allowed; }
    .hint {
      color: var(--muted);
      font-size: 12px;
      padding: 0 12px 12px;
    }
  </style>
</head>
<body>
  <div class=\"shell\">
    <div class=\"bar\">
      <span class=\"dot d1\"></span>
      <span class=\"dot d2\"></span>
      <span class=\"dot d3\"></span>
      <span class=\"title\">PeakeBot Public Terminal</span>
    </div>
    <div id=\"log\"></div>
    <div class=\"input\">
      <textarea id=\"prompt\" placeholder=\"Type your message...\"></textarea>
      <button id=\"send\">Send</button>
    </div>
    <div class=\"hint\">Public test instance. Avoid sensitive data.</div>
  </div>
  <script>
    const log = document.getElementById('log');
    const promptEl = document.getElementById('prompt');
    const sendBtn = document.getElementById('send');

    function addLine(cls, text) {
      const line = document.createElement('div');
      line.className = cls;
      line.textContent = text;
      log.appendChild(line);
      log.scrollTop = log.scrollHeight;
    }

    async function sendPrompt() {
      const prompt = promptEl.value.trim();
      if (!prompt) return;
      addLine('u', 'You: ' + prompt);
      promptEl.value = '';
      sendBtn.disabled = true;
      try {
        const res = await fetch('/api/chat', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({prompt})
        });
        const data = await res.json();
        if (!res.ok) {
          addLine('e', 'Error: ' + (data.error || 'Request failed'));
        } else {
          addLine('b', 'PeakeBot: ' + data.response);
        }
      } catch (err) {
        addLine('e', 'Network error: ' + err.message);
      } finally {
        sendBtn.disabled = false;
        promptEl.focus();
      }
    }

    sendBtn.addEventListener('click', sendPrompt);
    promptEl.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendPrompt();
      }
    });

    addLine('b', 'PeakeBot: Online. Ask me anything.');
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
  <title>PeakeBot Admin</title>
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
    <h1>PeakeBot Admin Panel</h1>
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


@app.post("/api/chat")
def api_chat() -> Response:
    payload = request.get_json(silent=True) or {}
    prompt = str(payload.get("prompt", "")).strip()
    if not prompt:
        return jsonify({"error": "prompt is required"}), 400

    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
    if not _check_rate_limit(client_ip):
        return jsonify({"error": "rate limit exceeded; try again shortly"}), 429

    with _GENERATION_LOCK:
        try:
            response = generate_response(prompt)
        except Exception as exc:
            return jsonify({"error": f"generation failed: {exc}"}), 500

    return jsonify({"response": response})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
