#!/usr/bin/env bash
set -Eeuo pipefail

if [[ -f /usr/lib/bashio/bashio.sh ]]; then
  # shellcheck source=/dev/null
  source /usr/lib/bashio/bashio.sh
fi

# s6-overlay v3 stores the Docker container environment as files rather than
# exporting them to the shell. Load any vars that aren't already in the environment.
if [[ -d /run/s6/container_environment ]]; then
  for _s6_file in /run/s6/container_environment/*; do
    [[ -f "$_s6_file" ]] || continue
    _s6_var="$(basename "$_s6_file")"
    if [[ -z "${!_s6_var:-}" ]]; then
      export "${_s6_var}=$(cat "$_s6_file")"
    fi
  done
  unset _s6_file _s6_var
fi

has_bashio() {
  declare -F bashio::log.info >/dev/null 2>&1
}

log_info() {
  if has_bashio; then
    bashio::log.info "$*"
  else
    echo "[INFO] $*"
  fi
}

log_warn() {
  if has_bashio; then
    bashio::log.warning "$*"
  else
    echo "[WARN] $*"
  fi
}

read_option() {
  local key="$1"
  local fallback="$2"
  local value=""

  if has_bashio; then
    value="$(bashio::config "$key" 2>/dev/null || true)"
  fi

  if [[ -z "$value" ]] || [[ "$value" == "null" ]]; then
    if [[ -f /data/options.json ]]; then
      value="$(jq -r --arg key "$key" '.[$key] // empty' /data/options.json 2>/dev/null || true)"
    fi
  fi

  echo "${value:-$fallback}"
}

BLUETOOTH_MAC="$(read_option bluetooth_mac "AA:BB:CC:DD:EE:FF")"
RFCOMM_CHANNEL="$(read_option rfcomm_channel "1")"
DEBUG="$(read_option debug "true")"

export BLUETOOTH_MAC
export RFCOMM_CHANNEL
export DEBUG

run_or_warn() {
  local description="$1"
  shift
  log_info "$description"
  "$@" || log_warn "$description failed with exit code $?"
}

log_info "Garmin GLO2 GPS add-on starting"
log_info "Configured MAC: ${BLUETOOTH_MAC}"
log_info "Configured RFCOMM channel: ${RFCOMM_CHANNEL}"
log_info "Publish method: Home Assistant Core API"

run_or_warn "uname -a" uname -a

log_info "Loaded Bluetooth kernel modules:"
if command -v lsmod >/dev/null 2>&1; then
  lsmod | grep -E 'rfcomm|bluetooth|btusb|bnep' || log_warn "No matching Bluetooth modules shown by lsmod"
else
  log_warn "lsmod is not available"
fi

run_or_warn "bluetoothctl show" bluetoothctl show
run_or_warn "bluetoothctl devices Paired" bluetoothctl devices Paired
run_or_warn "bluetoothctl info ${BLUETOOTH_MAC}" bluetoothctl info "${BLUETOOTH_MAC}"

log_info "Python Bluetooth socket test"
python3 - <<'PY'
import socket

print("AF_BLUETOOTH:", hasattr(socket, "AF_BLUETOOTH"))
for proto_name in ["BTPROTO_HCI", "BTPROTO_RFCOMM"]:
    print(proto_name, getattr(socket, proto_name, None))

try:
    s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
    print("RFCOMM socket OK")
    s.close()
except Exception as err:
    print("RFCOMM socket failed:", repr(err))
PY

run_or_warn "bluetoothctl trust ${BLUETOOTH_MAC}" bluetoothctl trust "${BLUETOOTH_MAC}"

log_info "Attempting bluetoothctl connect ${BLUETOOTH_MAC}"
bluetoothctl connect "${BLUETOOTH_MAC}" || log_warn "bluetoothctl connect failed; this can be normal until the serial channel is opened"

log_info "Checking supervisor token environment:"
printenv | grep -i 'token\|supervisor\|hassio' | sed 's/=.*/=<redacted>/' || log_warn "No token/supervisor vars found in environment"

log_info "Starting Garmin GLO 2 NMEA reader"
exec python3 /garmin_glo2.py
