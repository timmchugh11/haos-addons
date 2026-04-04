#!/bin/sh
set -e

OPTIONS="/data/options.json"

if [ ! -f "$OPTIONS" ]; then
    echo "ERROR: /data/options.json not found"
    exit 1
fi

INTERFACE=$(jq -r '.interface // "wlan0"' "$OPTIONS")
SSID=$(jq -r '.ssid // "HomeAssistant-AP"' "$OPTIONS")
PASSWORD=$(jq -r '.password' "$OPTIONS")
CHANNEL=$(jq -r '.channel // 6' "$OPTIONS")
COUNTRY=$(jq -r '.country_code // "US"' "$OPTIONS")

AP_IP="192.168.50.1"
DHCP_START="192.168.50.10"
DHCP_END="192.168.50.100"

echo "==> Hostapd AP configuration"
echo "    Interface : $INTERFACE"
echo "    SSID      : $SSID"
echo "    Channel   : $CHANNEL"
echo "    Country   : $COUNTRY"

echo "==> Checking adapter AP mode support..."
if iw dev "$INTERFACE" info >/dev/null 2>&1; then
    MODES=$(iw list 2>/dev/null | grep -A 20 "Supported interface modes" | grep "\* " || echo "    (unable to read)")
    echo "    Supported modes for $INTERFACE:"
    echo "$MODES"
    if echo "$MODES" | grep -q "\* AP"; then
        echo "    AP mode: SUPPORTED"
    else
        echo "    AP mode: NOT SUPPORTED - this adapter cannot be used as an access point"
        exit 1
    fi
else
    echo "    WARNING: interface $INTERFACE not found - check it is plugged in and the name is correct"
    exit 1
fi

# Put the interface into AP mode and assign an IP
ip link set "$INTERFACE" down
iw dev "$INTERFACE" set type ap 2>/dev/null || true
ip addr flush dev "$INTERFACE"
ip addr add "${AP_IP}/24" dev "$INTERFACE"
ip link set "$INTERFACE" up

# Enable IP forwarding — /proc/sys is read-only in the container but
# HAOS already has forwarding enabled on the host network namespace.

# NAT all AP client traffic out through whatever upstream interface has a default route
iptables -t nat -A POSTROUTING -s 192.168.50.0/24 ! -d 192.168.50.0/24 -j MASQUERADE 2>/dev/null || true

# ---------------------------------------------------------------------------
# hostapd config
# ---------------------------------------------------------------------------
cat > /tmp/hostapd.conf << EOF
interface=${INTERFACE}
driver=nl80211
ssid=${SSID}
hw_mode=g
channel=${CHANNEL}
country_code=${COUNTRY}
ieee80211n=1
wpa=2
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP
wpa_passphrase=${PASSWORD}
EOF

# ---------------------------------------------------------------------------
# dnsmasq config — bind only to the AP interface so we don't conflict with
# the HAOS DHCP server on other interfaces
# ---------------------------------------------------------------------------
cat > /tmp/dnsmasq.conf << EOF
interface=${INTERFACE}
bind-interfaces
dhcp-range=${DHCP_START},${DHCP_END},12h
dhcp-option=3,${AP_IP}
dhcp-option=6,1.1.1.1,8.8.8.8
EOF

# Start DHCP server in background
dnsmasq --conf-file=/tmp/dnsmasq.conf

echo "==> Starting hostapd..."
exec hostapd /tmp/hostapd.conf
