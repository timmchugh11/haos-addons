#!/usr/bin/with-contenv bashio
# shellcheck shell=bash
set -e

bashio::log.info "Starting Starlink GUI..."

# Read add-on options set by the user in HA
DISH_HOST=$(bashio::config 'dish_host')
DISH_PORT=$(bashio::config 'dish_port')
ROUTER_HOST=$(bashio::config 'router_host')
ROUTER_PORT=$(bashio::config 'router_port')

export DISH_HOST DISH_PORT ROUTER_HOST ROUTER_PORT

bashio::log.info "Dish:   ${DISH_HOST}:${DISH_PORT}"
bashio::log.info "Router: ${ROUTER_HOST}:${ROUTER_PORT}"
bashio::log.info "Listening on port 3000"

exec node /app/server.js
