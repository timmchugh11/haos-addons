#!/usr/bin/env bash
set -Eeuo pipefail

if [[ -f /usr/lib/bashio/bashio.sh ]]; then
  source /usr/lib/bashio/bashio.sh
fi

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

DELAY_SECONDS="$(read_option delay_seconds "10")"
export DELAY_SECONDS

log_info "Entity Remover add-on starting"
log_info "Will wait ${DELAY_SECONDS}s then delete configured entities"

exec python3 /entity_remover.py
