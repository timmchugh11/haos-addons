#!/bin/sh
set -e

echo "==> Starting Hostapd AP web manager on port 8080..."
exec gunicorn --bind 0.0.0.0:8080 --workers 1 --threads 4 --chdir /web 'app:app'
