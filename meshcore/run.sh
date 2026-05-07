#!/usr/bin/with-contenv bashio
# shellcheck shell=bash
set -e

export HOME=/data
export PYTHONUNBUFFERED=1
export PATH="/opt/meshcore-venv/bin:${PATH}"

TRANSPORT="$(bashio::config 'transport')"
SERIAL_PORT="$(bashio::config 'serial_port')"
BAUDRATE="$(bashio::config 'baudrate')"
SERIAL_CX_DELAY="$(bashio::config 'serial_cx_delay')"
BLE_ADDRESS="$(bashio::config 'ble_address')"
BLE_PIN="$(bashio::config 'ble_pin')"
DEBUG="$(bashio::config 'debug')"

mkdir -p /data/.meshcore-gui

ARGS=()
if [ "${TRANSPORT}" = "ble" ]; then
  ARGS+=("${BLE_ADDRESS}" "--ble-pin" "${BLE_PIN}")
  bashio::log.info "Starting MeshCore GUI over BLE: ${BLE_ADDRESS}"
else
  ARGS+=("${SERIAL_PORT}" "--baud=${BAUDRATE}" "--serial-cx-dly=${SERIAL_CX_DELAY}")
  bashio::log.info "Starting MeshCore GUI over serial: ${SERIAL_PORT} @ ${BAUDRATE}"
fi

ARGS+=("--port=8081")

if bashio::var.true "${DEBUG}"; then
  ARGS+=("--debug-on")
  bashio::log.info "Debug logging is enabled"
fi

bashio::log.info "Listening on port 8081"
bashio::log.info "Persistent MeshCore GUI data is stored under /data/.meshcore-gui"

cd /opt/meshcore-gui
exec python3 meshcore_gui.py "${ARGS[@]}"
