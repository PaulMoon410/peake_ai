Harold Render Deployment

What you get
- Public URL access for others through Render
- Browser chat window at /
- JSON API at /api/chat
- Health endpoint at /health
- One integrated Harold chat: natural conversation, follow-up context, MCF3 memory recall, and answer-first web research
- Existing Hive bot, admin panel, base knowledge, and FTP learning flows remain in the same service

Important
- Render free web services do not provide a guaranteed static IP.
- You should use the Render HTTPS URL, not a fixed IP.

Deploy steps
1. Push this repo to GitHub.
2. Keep the existing Render Web Service connected to this repo and deploy its main branch.
3. Render uses the existing render.yaml settings:
   - Build: pip install -r requirements.txt
   - Start: gunicorn -w 1 -k gthread -b 0.0.0.0:$PORT web_app:app
4. Open your service URL and test.

Local test
1. Install deps:
   python -m pip install -r requirements.txt
2. Run:
   python web_app.py
3. Open:
   http://127.0.0.1:10000

Notes
- This setup includes a basic per-IP rate limiter.
- For production, add persistent session/auth controls and stronger abuse protection.

Admin Panel (Safe Runtime Updates)
- URL: /admin
- Protected by API key header (X-Admin-Key) from browser UI.

Set these environment variables on Render:
- ADMIN_PANEL_ENABLED=true
- ADMIN_API_KEY=<strong-random-secret>

Optional FTP runtime variables:
- FTP_HOST=ftp.geocities.ws
- FTP_USER=<your-user>
- FTP_PASS=<your-password>
- FTP_BASE_DIR=/
- FTP_UPLOAD_BATCH_SIZE=3

No Render start-command change is needed: the current `web_app:app` process now hosts the integrated experience. The existing PeakeBot/Harold FTP settings are reused; do not put credentials in `render.yaml` or commit them to GitHub.

Pocket AI's MCF3 recall uses the same FTP credentials and base directory, but writes to its own archive file so it does not overwrite the existing PeakeBot archive:
- Default archive: pocket-ai-memory.jsonl (plus numbered shards as capped files fill)
- Optional MEMORY_FTP_PATH overrides that archive filename/path.
- Optional MEMORY_FTP_MAX_BYTES sets the maximum shard size (default 32 KiB; allowed range 1–64 KiB).
- Render's local working cache is kept under /tmp and retains at most 50 MCF3 records by default; set MEMORY_LOCAL_CACHE_RECORDS to adjust the count.
- The web chat sends only the current browser conversation's last six turns to the model. New conversations start with a fresh context.
- Render runs the repository's small NumPy neural language model, bootstrapped from `create_training_data()`; it is not a pretrained GPT-class model, so answer quality is limited and all research claims still need sources.
- Model checkpoints are stored as versioned compressed NPZ archives (not executable pickle) and the persistent checkpoint is `language_model_brain.npz` in the configured FTP base directory. FTP loading is capped at 64 MiB; if no compatible checkpoint exists, the app trains a bootstrap model and attempts to upload it.
- The startup log reports FTP brain load/save outcomes. Existing legacy `.pkl` checkpoints are intentionally not unpickled; a new NPZ checkpoint is bootstrapped instead.
- Users can explicitly ask Harold to remember a preference or project fact. Do not save passwords, private keys, recovery phrases, or API tokens.
- Explicit `/search ...` requests and questions the language model cannot answer confidently use the existing multi-source verifier, then ask the model to explain the evidence naturally instead of returning the raw link list.
- Conversation turns are sent by the browser as untrusted context (limited to six turns); MCF3 retrieval is also added as unverified context. Do not enter private secrets in the public chat.

What admin can do safely:
- Insert base knowledge entries (topic + answer) at runtime
- Queue learning topics
- Trigger sync flush
- View growth status and knowledge list

What admin cannot do:
- Execute shell commands
- Edit arbitrary files
- Run arbitrary Python code

Branding note: The assistant is named Harold. The existing Render service identifier remains `peakebot-web` to avoid creating or renaming a service during this code update.
