#!/usr/bin/with-contenv bashio
# shellcheck shell=bash
set -e

bashio::log.info "Starting Van Power 3D..."

export TITLE=$(bashio::config 'title')
export REFRESH_SECONDS=$(bashio::config 'refresh_seconds')
export SOLAR_VOLTAGE=$(bashio::config 'solar_voltage')
export SOLAR_AMP=$(bashio::config 'solar_amp')
export SOLAR_WATT=$(bashio::config 'solar_watt')
export BATTERY_VOLTAGE=$(bashio::config 'battery_voltage')
export BATTERY_AMP=$(bashio::config 'battery_amp')
export BATTERY_WATT=$(bashio::config 'battery_watt')
export GRID_VOLTAGE=$(bashio::config 'grid_voltage')
export GRID_AMP=$(bashio::config 'grid_amp')
export GRID_WATT=$(bashio::config 'grid_watt')
export ALTERNATOR_VOLTAGE=$(bashio::config 'alternator_voltage')
export ALTERNATOR_AMP=$(bashio::config 'alternator_amp')
export ALTERNATOR_WATT=$(bashio::config 'alternator_watt')
export BATTERY_PERCENT=$(bashio::config 'battery_percent')
export PORT=3050

bashio::log.info "Listening on port ${PORT}"
bashio::log.info "Solar voltage entity: ${SOLAR_VOLTAGE}"
bashio::log.info "Battery percent entity: ${BATTERY_PERCENT}"

exec node /app/server.js
