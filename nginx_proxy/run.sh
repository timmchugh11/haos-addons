#!/usr/bin/with-contenv bashio
# shellcheck shell=bash
set -e

TARGET_URL=$(bashio::config 'target_url')
PRESERVE_HOST=$(bashio::config 'preserve_host')
REWRITE_ABSOLUTE_PATHS=$(bashio::config 'rewrite_absolute_paths')

case "${TARGET_URL}" in
  http://*)
    ;;
  *)
    bashio::log.fatal "target_url must start with http:// for this add-on version"
    exit 1
    ;;
esac

if [ "${PRESERVE_HOST}" = "true" ]; then
  HOST_HEADER='$host'
else
  HOST_HEADER='$proxy_host'
fi

SUB_FILTERS=""
if [ "${REWRITE_ABSOLUTE_PATHS}" = "true" ]; then
  SUB_FILTERS='
        proxy_set_header Accept-Encoding "";
        sub_filter_once off;
        sub_filter_types text/html text/css application/javascript text/javascript;
        sub_filter "href=\"/" "href=\"$http_x_ingress_path/";
        sub_filter "src=\"/" "src=\"$http_x_ingress_path/";
        sub_filter "action=\"/" "action=\"$http_x_ingress_path/";
        sub_filter "url(/" "url($http_x_ingress_path/";'
fi

cat > /etc/nginx/http.d/default.conf <<EOF
map \$http_upgrade \$connection_upgrade {
    default upgrade;
    '' close;
}

server {
    listen 8099 default_server;
    server_name _;

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
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header X-Forwarded-Prefix \$http_x_ingress_path;
        proxy_redirect ~^(/.*)\$ \$http_x_ingress_path\$1;${SUB_FILTERS}
    }
}
EOF

bashio::log.info "Proxying Home Assistant ingress to ${TARGET_URL}"
bashio::log.info "Preserve Host header: ${PRESERVE_HOST}"
bashio::log.info "Rewrite absolute paths: ${REWRITE_ABSOLUTE_PATHS}"

exec nginx -g 'daemon off;'
