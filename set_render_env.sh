#!/bin/bash
# This script sets the ADMIN_API_KEY on your Render deployment
# Prerequisites: 
#   1. Install Render CLI: npm install -g @render-com/cli
#   2. Authenticate: render login
#   3. Run this script: bash set_render_env.sh

SERVICE_ID="your-service-id-here"
ADMIN_KEY="admin-secret-key-$(date +%s)"

echo "Setting ADMIN_API_KEY=$ADMIN_KEY on Render..."

# Set the environment variable
render env set ADMIN_API_KEY "$ADMIN_KEY" --service-id "$SERVICE_ID"

echo "✅ Done! Your admin key is: $ADMIN_KEY"
echo "Visit: https://dashboard.render.com to verify"
