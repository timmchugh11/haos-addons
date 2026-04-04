#!/bin/sh
set -e

echo "==> Starting Hostapd AP web manager on port 8080..."
exec python3 /web/app.py
