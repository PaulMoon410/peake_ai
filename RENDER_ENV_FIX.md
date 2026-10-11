# RENDER SETUP: Fix "ADMIN_API_KEY is not configured"

## What's Wrong
Your admin panel code is working (✅ verified locally), but Render doesn't have the `ADMIN_API_KEY` environment variable set.

## Quick Fix (2 Minutes)

### Step 1: Get Your Render Service ID
1. Go to: https://dashboard.render.com
2. Click your **PeakeBot** service (blue name at top)
3. In URL bar, copy the ID: `https://dashboard.render.com/services/srv_XXXXXXXXXXXXXXXX`
   - Your service ID is the part after `/services/`

### Step 2: Set Environment Variable via Render Dashboard
1. While on your PeakeBot service page, click **Environment** tab
2. Paste into search box if needed, or scroll to find variables
3. Click **Add Environment Variable** button (or pencil icon if editing existing)
4. Enter:
   - **Key** (left): `ADMIN_API_KEY`
   - **Value** (right): `my-peakebot-admin-key-secret` (any strong string you choose)
5. Click **Save Changes**

✅ **Render auto-redeploys** - wait 2-3 minutes

### Step 3: Verify It Works
1. After redeployment completes, visit:
   ```
   https://your-peakebot-url.onrender.com/admin
   ```

2. You should see a login form (no 503 error)

3. Enter the key value you set in Step 2

## If Still Getting 503 Error

**Check 1: Verify variable was saved**
- Render dashboard → Environment tab
- Look for `ADMIN_API_KEY` in the list
- If not there, click Add and try again

**Check 2: Verify redeployment completed**
- Click **Deployments** tab
- Should show a recent deploy with status ✅ Live
- If it says ❌ Build failed, click it to see error logs

**Check 3: Check web service logs**
- Click **Logs** tab
- Should show: `✅ Model loaded` and `🧠 Neural Language Model initialized`
- If it shows errors, screenshot and share

## Once Working

The admin panel gives you:
- `/admin`: Visual interface to manage bot
- `POST /api/admin/knowledge`: Add Q&A pairs without redeploying
- `POST /api/admin/learning-topic`: Queue topics for background research
- `GET /api/admin/status`: View learning progress metrics
- `POST /api/admin/flush-sync`: Force FTP sync and learning batches

## Reference: Local Validation
The admin panel **was tested locally and passes all checks**:
```
✅ ADMIN_PANEL_ENABLED: True
✅ ADMIN_API_KEY configured: True
✅ GET /admin → 200 (admin panel HTML served)
✅ GET /api/admin/status → 200 (with authentication)
```

Your Render deployment just needs the env var set.
