# Deploying Admin Panel to Render

## Problem
The admin panel code is on your local machine but **hasn't been deployed to your Render instance yet**. That's why `/admin` doesn't work on your live service.

## Solution: Three Steps

### Step 1: Commit Code to GitHub
```powershell
cd "C:\Users\Moon\Desktop\PeakeCoin\Peakebot AI"

# Stage all changes
git add peakebot.py web_app.py base_knowledge_overrides.json growth_profile.json

# Commit
git commit -m "Add admin panel with secure knowledge insertion and learning control"

# Push to your repository
git push origin main
```

### Step 2: Connect Render to Your GitHub Repo (If Not Done)
1. Go to [Render Dashboard](https://dashboard.render.com)
2. Select your PeakeBot service
3. Go to **Settings** tab
4. Verify the Git repository is connected to `https://github.com/PaulMoon410/fps.git`
5. Verify Deploy branch is set to `main`

### Step 3: Set Environment Variables on Render
1. Go to your PeakeBot service in [Render Dashboard](https://dashboard.render.com)
2. Click **Environment** tab
3. Add these two new variables:
   ```
   ADMIN_PANEL_ENABLED = true
   ADMIN_API_KEY = your-secret-key-here
   ```
   (Replace `your-secret-key-here` with a strong random string, e.g., `admin_key_xY9kL2mQ7pR4wN8bV1cD5e3f`)

4. Click **Save**

### Step 4: Trigger Deployment
Once you save environment variables, Render will automatically redeploy your service (takes ~2-3 minutes).

Or manually trigger by:
1. Clicking **Manual Deploy** on your Render service
2. Or pushing code: `git push origin main`

## Verify It Worked
After ~3 minutes, visit:
```
https://your-peakebot-url.onrender.com/admin
```

You should see the PeakeBot Admin Panel login screen.

## Using the Admin Panel
1. Enter your `ADMIN_API_KEY` value (the secret key you set in Step 3)
2. The key is stored in browser **localStorage only** (not sent to server on every request)
3. Available actions:
   - **Insert Knowledge**: Add new Q&A pairs the bot references
   - **Queue Learning Topic**: Ask bot to research topics in background
   - **View Status**: See metrics (interactions, learning runs, pending items)
   - **View Knowledge**: Browse all Q&A pairs (base + custom)
   - **Force Sync**: Manually flush FTP uploads and learning batches

## Troubleshooting

### Admin panel still shows 503 error
- **Cause**: `ADMIN_PANEL_ENABLED` not set to `true` or `ADMIN_API_KEY` is empty
- **Fix**: Check Render environment variables, save, and wait for redeployment

### Getting "Unauthorized" when entering key
- **Cause**: Key doesn't match `ADMIN_API_KEY` env variable (case-sensitive)
- **Fix**: Verify the exact string in Render environment matches what you're entering

### Service crashes after deployment
- **Cause**: Checkout the logs in Render dashboard
- **Fix**: Run locally first: `python -m pytest -xvs web_app.py` or `python -c "import web_app; print('OK')"`

## Next Steps
Once deployed, you can:
1. Add base knowledge at runtime without redeployment
2. Queue learning topics for background research
3. View real-time learning metrics
4. Force sync with FTP storage anytime
