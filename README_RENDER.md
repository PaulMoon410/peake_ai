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
