PeakeBot Render Deployment

What you get
- Public URL access for others through Render
- Browser chat window at /
- JSON API at /api/chat
- Health endpoint at /health

Important
- Render free web services do not provide a guaranteed static IP.
- You should use the Render HTTPS URL, not a fixed IP.

Deploy steps
1. Push this repo to GitHub.
2. In Render, create a new Web Service from the repo.
3. Render will detect render.yaml, then use:
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

What admin can do safely:
- Insert base knowledge entries (topic + answer) at runtime
- Queue learning topics
- Trigger sync flush
- View growth status and knowledge list

What admin cannot do:
- Execute shell commands
- Edit arbitrary files
- Run arbitrary Python code
