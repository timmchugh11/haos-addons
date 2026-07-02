#!/usr/bin/with-contenv bashio
# shellcheck shell=bash
set -e

TARGET_URL=$(bashio::config 'target_url')
PRESERVE_HOST=$(bashio::config 'preserve_host')
REWRITE_ABSOLUTE_PATHS=$(bashio::config 'rewrite_absolute_paths')
SSL_VERIFY=$(bashio::config 'ssl_verify')

case "${TARGET_URL}" in
  http://*|https://*)
    ;;
  *)
    bashio::log.fatal "target_url must start with http:// or https://"
    exit 1
    ;;
esac

if [[ "${TARGET_URL}" =~ ^(https?://[^/]+) ]]; then
  TARGET_ORIGIN="${BASH_REMATCH[1]}"
else
  bashio::log.fatal "Could not parse target_url origin from ${TARGET_URL}"
  exit 1
fi

if [ "${PRESERVE_HOST}" = "true" ]; then
  HOST_HEADER='$host'
else
  HOST_HEADER='$proxy_host'
fi

if [ "${SSL_VERIFY}" = "true" ]; then
  PROXY_SSL_VERIFY="on"
else
  PROXY_SSL_VERIFY="off"
fi

SUB_FILTERS=""
if [ "${REWRITE_ABSOLUTE_PATHS}" = "true" ]; then
  SUB_FILTERS="
        proxy_set_header Accept-Encoding \"\";
        sub_filter_once off;
        sub_filter_types *;
        sub_filter \"${TARGET_ORIGIN}\" \"\$external_proto://\$host\$http_x_ingress_path\";
        sub_filter \"href=\\\"/\" \"href=\\\"\$http_x_ingress_path/\";
        sub_filter \"src=\\\"/\" \"src=\\\"\$http_x_ingress_path/\";
        sub_filter \"action=\\\"/\" \"action=\\\"\$http_x_ingress_path/\";
        sub_filter \"\\\"/api2/\" \"(window.location.pathname.endsWith('/') ? window.location.pathname.slice(0,-1) : window.location.pathname) + \\\"/api2/\";
        sub_filter \"'/api2/\" \"(window.location.pathname.endsWith('/') ? window.location.pathname.slice(0,-1) : window.location.pathname) + '/api2/\";
        sub_filter \"\\\"/pve2/\" \"(window.location.pathname.endsWith('/') ? window.location.pathname.slice(0,-1) : window.location.pathname) + \\\"/pve2/\";
        sub_filter \"'/pve2/\" \"(window.location.pathname.endsWith('/') ? window.location.pathname.slice(0,-1) : window.location.pathname) + '/pve2/\";
        sub_filter \"\\\"/novnc/\" \"(window.location.pathname.endsWith('/') ? window.location.pathname.slice(0,-1) : window.location.pathname) + \\\"/novnc/\";
        sub_filter \"'/novnc/\" \"(window.location.pathname.endsWith('/') ? window.location.pathname.slice(0,-1) : window.location.pathname) + '/novnc/\";
        sub_filter \"\\\"/xtermjs/\" \"(window.location.pathname.endsWith('/') ? window.location.pathname.slice(0,-1) : window.location.pathname) + \\\"/xtermjs/\";
        sub_filter \"'/xtermjs/\" \"(window.location.pathname.endsWith('/') ? window.location.pathname.slice(0,-1) : window.location.pathname) + '/xtermjs/\";
        sub_filter \"url(/\" \"url(\$http_x_ingress_path/\";"
fi

cat > /etc/nginx/http.d/default.conf <<EOF
map \$http_upgrade \$connection_upgrade {
    default upgrade;
    '' close;
}

map \$http_x_forwarded_proto \$external_proto {
    default \$http_x_forwarded_proto;
    '' https;
}

server {
    listen 8099 default_server;
    server_name _;

    access_log /dev/stdout;
    error_log /dev/stderr info;

    proxy_http_version 1.1;
    proxy_buffering off;
    proxy_read_timeout 3600s;
    proxy_send_timeout 3600s;

    location / {
        proxy_pass ${TARGET_URL};
        proxy_set_header Host ${HOST_HEADER};
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection \$connection_upgrade;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Host \$host;
        proxy_set_header X-Forwarded-Proto \$external_proto;
        proxy_set_header X-Forwarded-Ssl on;
        proxy_set_header X-Forwarded-Port 443;
        proxy_set_header X-Forwarded-Prefix \$http_x_ingress_path;
        proxy_ssl_server_name on;
        proxy_ssl_verify ${PROXY_SSL_VERIFY};
        proxy_redirect ${TARGET_ORIGIN}/ \$external_proto://\$host\$http_x_ingress_path/;
        proxy_redirect ~^(/.*)\$ \$http_x_ingress_path\$1;${SUB_FILTERS}
    }
}
EOF

bashio::log.info "Proxying Home Assistant ingress to ${TARGET_URL}"
bashio::log.info "Target origin: ${TARGET_ORIGIN}"
bashio::log.info "Preserve Host header: ${PRESERVE_HOST}"
bashio::log.info "Rewrite absolute paths: ${REWRITE_ABSOLUTE_PATHS}"
bashio::log.info "Upstream SSL verification: ${SSL_VERIFY}"

exec nginx -g 'daemon off;'
