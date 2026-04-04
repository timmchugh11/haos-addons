#!/usr/bin/with-contenv bashio

# Persistent data directory (always mounted at /data)
HIST_DIR="/data/copyparty"
mkdir -p "${HIST_DIR}"

# Check for an advanced config file placed in the addon_config directory
# (/config inside the container, mapped from /addon_configs/<slug>/)
CONFIG_FILE="/config/copyparty.conf"
if [ -f "${CONFIG_FILE}" ]; then
    bashio::log.info "Found config file at ${CONFIG_FILE}; using it directly."
    exec python3 -m copyparty \
        --hist "${HIST_DIR}" \
        -c "${CONFIG_FILE}"
fi

# ── Simple mode: build arguments from add-on options ──────────────────────────

ARGS="-p 3923"
ARGS="${ARGS} --hist ${HIST_DIR}"
# Tell copyparty it is behind the HA Supervisor reverse proxy so it trusts
# the X-Forwarded-For header and keeps WebSocket connections stable.
ARGS="${ARGS} --rproxy 1 --xff-hdr x-forwarded-for"

# Mount the HA /share and /media directories
HAS_AUTH=false

if bashio::config.has_value 'username' && bashio::config.has_value 'password'; then
    USERNAME=$(bashio::config 'username')
    PASSWORD=$(bashio::config 'password')
    # Validate: neither value may contain a colon (copyparty uses colon as delimiter)
    if [[ "${USERNAME}" == *:* ]] || [[ "${PASSWORD}" == *:* ]]; then
        bashio::log.fatal "username and password must not contain a colon (:)"
        exit 1
    fi
    bashio::log.info "Configuring authentication for user: ${USERNAME}"
    ARGS="${ARGS} -a ${USERNAME}:${PASSWORD}"
    ARGS="${ARGS} -v /share:/share:rw,${USERNAME}"
    ARGS="${ARGS} -v /media:/media:r,${USERNAME}"
    ARGS="${ARGS} -v /homeassistant:/config:r,${USERNAME}"
    HAS_AUTH=true
else
    bashio::log.warning "No username/password set — copyparty will be open to everyone on your network!"
    ARGS="${ARGS} -v /share:/share:rw"
    ARGS="${ARGS} -v /media:/media:r"
    ARGS="${ARGS} -v /homeassistant:/config:r"
fi

# Append any user-supplied extra flags
if bashio::config.has_value 'extra_args'; then
    EXTRA=$(bashio::config 'extra_args')
    ARGS="${ARGS} ${EXTRA}"
fi

bashio::log.info "Starting copyparty on port 3923..."
bashio::log.debug "Command: python3 -m copyparty ${ARGS}"

# shellcheck disable=SC2086
exec python3 -m copyparty ${ARGS}
