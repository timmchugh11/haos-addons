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

mkdir -p /data/.meshcore

if [ "${TRANSPORT}" = "ble" ]; then
  export MESHCORE_DEVICE="${BLE_ADDRESS}"
  bashio::log.info "Starting MeshCore GUI over BLE: ${BLE_ADDRESS}"
else
  export MESHCORE_DEVICE="${SERIAL_PORT}"
  bashio::log.info "Starting MeshCore GUI over serial: ${SERIAL_PORT} @ ${BAUDRATE}"
fi

export MESHCORE_TRANSPORT="${TRANSPORT}"
export MESHCORE_BAUDRATE="${BAUDRATE}"
export MESHCORE_SERIAL_CX_DELAY="${SERIAL_CX_DELAY}"
export MESHCORE_BLE_PIN="${BLE_PIN}"
export MESHCORE_DEBUG="${DEBUG}"

if bashio::var.true "${DEBUG}"; then
  bashio::log.info "Debug logging is enabled"
fi

bashio::log.info "Listening on port 8081"
bashio::log.info "Persistent MeshCore data is stored under /data/.meshcore"

cd /app
exec uvicorn app:app --host 0.0.0.0 --port 8081
