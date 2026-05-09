# Quick validation script to test admin panel locally
# Run this to verify everything works before deploying to Render

import os
from web_app import app

# Test 1: Check if ADMIN_API_KEY can be set
print("=" * 60)
print("ADMIN PANEL SETUP VALIDATION")
print("=" * 60)

# Simulate what Render will do
os.environ["ADMIN_PANEL_ENABLED"] = "true"
os.environ["ADMIN_API_KEY"] = "test-admin-secret-key"

from importlib import reload
import web_app as web_module
reload(web_module)

print(f"\n1. ADMIN_PANEL_ENABLED: {web_module.ADMIN_PANEL_ENABLED}")
print(f"2. ADMIN_API_KEY configured: {bool(web_module.ADMIN_API_KEY)}")

if not web_module.ADMIN_PANEL_ENABLED:
    print("   ❌ ADMIN_PANEL_ENABLED is False")
    exit(1)

if not web_module.ADMIN_API_KEY:
    print("   ❌ ADMIN_API_KEY is empty")
    exit(1)

print("\n✅ Environment variables are set correctly!")

# Test 2: Try accessing the admin endpoint
print("\nTesting /admin endpoint...")
test_client = app.test_client()
response = test_client.get("/admin")

if response.status_code == 200:
    print(f"   ✅ GET /admin returned 200")
    if b"PeakeBot Admin Panel" in response.data:
        print(f"   ✅ Admin panel HTML found")
    else:
        print(f"   ❌ Admin panel HTML not found")
        exit(1)
elif response.status_code == 503:
    print(f"   ❌ GET /admin returned 503 - API key not configured")
    print(f"      Make sure ADMIN_API_KEY env var is set on Render")
    exit(1)
else:
    print(f"   ❌ GET /admin returned {response.status_code}")
    print(f"      Response: {response.data[:200]}")
    exit(1)

# Test 3: Try authenticated API call
print("\nTesting authenticated API endpoint...")
response = test_client.get(
    "/api/admin/status",
    headers={"X-Admin-Key": "test-admin-secret-key"}
)

if response.status_code == 200:
    print(f"   ✅ GET /api/admin/status returned 200 with auth")
else:
    print(f"   ❌ GET /api/admin/status returned {response.status_code}")
    exit(1)

print("\n" + "=" * 60)
print("✅ ALL TESTS PASSED!")
print("=" * 60)
print("\nRender Setup:")
print("1. Set ADMIN_PANEL_ENABLED = true")
print("2. Set ADMIN_API_KEY = <your-secret-key>")
print("3. Redeploy")
print("4. Visit /admin and enter the key value")
