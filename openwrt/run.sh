#!/bin/sh
set -e

OPTIONS="/data/options.json"

# ---------------------------------------------------------------------------
# Read add-on options and export as environment variables expected by the
# upstream openwrt-docker image.  All keys must match config.yaml schema.
# ---------------------------------------------------------------------------
if [ -f "$OPTIONS" ]; then
    WAN_IF=$(jq -r '.wan_if // "host"' "$OPTIONS")
    LAN_IF=$(jq -r '.lan_if // "veth"' "$OPTIONS")
    FORWARD_LUCI=$(jq -r 'if .forward_luci then "true" else "false" end' "$OPTIONS")
    CPU_COUNT=$(jq -r '.cpu_count // 1' "$OPTIONS")
    RAM_COUNT=$(jq -r '.ram_count // 256' "$OPTIONS")
    DEBUG=$(jq -r 'if .debug then "true" else "false" end' "$OPTIONS")
else
    echo "WARNING: /data/options.json not found, using defaults"
    WAN_IF="host"
    LAN_IF="veth"
    FORWARD_LUCI="true"
    CPU_COUNT=1
    RAM_COUNT=256
    DEBUG="false"
fi

export WAN_IF LAN_IF FORWARD_LUCI CPU_COUNT RAM_COUNT DEBUG

echo "==> OpenWrt add-on configuration"
echo "    WAN_IF       = $WAN_IF"
echo "    LAN_IF       = $LAN_IF"
echo "    FORWARD_LUCI = $FORWARD_LUCI"
echo "    CPU_COUNT    = $CPU_COUNT"
echo "    RAM_COUNT    = $RAM_COUNT MB"
echo "    DEBUG        = $DEBUG"

# ---------------------------------------------------------------------------
# The upstream image declares VOLUME /storage, so Docker creates that
# directory before our CMD runs.  Prefer a bind mount (needs SYS_ADMIN /
# Protection mode off); fall back to a periodic copy-sync if unavailable.
# ---------------------------------------------------------------------------
mkdir -p /data/storage

if mount --bind /data/storage /storage 2>/dev/null; then
    echo "==> Storage bind-mounted from /data/storage"
else
    echo "==> Bind mount unavailable - using copy-sync (disable Protection mode for full persistence)"
    # Restore any previously saved data into the volume
    if [ -n "$(ls -A /data/storage 2>/dev/null)" ]; then
        cp -a /data/storage/. /storage/
    fi
    # Background loop: flush /storage -> /data/storage every 60 seconds
    ( while sleep 60; do cp -a /storage/. /data/storage/ 2>/dev/null || true; done ) &
fi

# ---------------------------------------------------------------------------
# Hand off to the upstream openwrt-docker entrypoint.
# ---------------------------------------------------------------------------
exec /run/init_container.sh
