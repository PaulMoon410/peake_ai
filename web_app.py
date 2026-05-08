import os
import threading
import time
from collections import defaultdict, deque
from flask import Flask, jsonify, request, Response

from peakebot import generate_response

app = Flask(__name__)

# Keep one generation at a time to avoid model state collisions.
_GENERATION_LOCK = threading.Lock()

# Lightweight in-memory per-IP rate limiter for public testing.
_RATE_WINDOW_SECONDS = 60
_RATE_LIMIT_REQUESTS = 15
_REQUEST_LOG = defaultdict(deque)


def _check_rate_limit(client_ip: str) -> bool:
    now = time.time()
    q = _REQUEST_LOG[client_ip]
    while q and now - q[0] > _RATE_WINDOW_SECONDS:
        q.popleft()
    if len(q) >= _RATE_LIMIT_REQUESTS:
        return False
    q.append(now)
    return True


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
