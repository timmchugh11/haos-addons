#!/usr/bin/with-contenv bashio
# shellcheck shell=bash
set -e

bashio::log.info "Starting Starlink GUI..."

# Read add-on options set by the user in HA
DISH_HOST=$(bashio::config 'dish_host')
DISH_PORT=$(bashio::config 'dish_port')
ROUTER_HOST=$(bashio::config 'router_host')
ROUTER_PORT=$(bashio::config 'router_port')
OPENWRT_FILL_ROUTER_BLANKS=$(bashio::config 'openwrt_fill_router_blanks')
OPENWRT_HOST=$(bashio::config 'openwrt_host')
OPENWRT_PROTOCOL=$(bashio::config 'openwrt_protocol')
OPENWRT_USERNAME=$(bashio::config 'openwrt_username')
OPENWRT_PASSWORD=$(bashio::config 'openwrt_password')

export DISH_HOST DISH_PORT ROUTER_HOST ROUTER_PORT
export OPENWRT_FILL_ROUTER_BLANKS OPENWRT_HOST OPENWRT_PROTOCOL OPENWRT_USERNAME OPENWRT_PASSWORD

bashio::log.info "Dish:   ${DISH_HOST}:${DISH_PORT}"
bashio::log.info "Router: ${ROUTER_HOST}:${ROUTER_PORT}"
bashio::log.info "OpenWrt fill: ${OPENWRT_FILL_ROUTER_BLANKS} (host: ${OPENWRT_HOST})"
bashio::log.info "Listening on port 3000"
bashio::log.info "Publishing Lovelace card to /homeassistant/www/starlink-gui/starlink-combined-card.js"

install -D -m 0644 /app/public/starlink-combined-card.js /homeassistant/www/starlink-gui/starlink-combined-card.js

exec node /app/server.js
