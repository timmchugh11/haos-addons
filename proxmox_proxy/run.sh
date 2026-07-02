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
        sub_filter \"${TARGET_ORIGIN}\" \"\$external_proto://\$host\$http_x_ingress_path\";
        sub_filter \"href=\\\"/\" \"href=\\\"./\";
        sub_filter \"src=\\\"/\" \"src=\\\"./\";
        sub_filter \"action=\\\"/\" \"action=\\\"./\";
        sub_filter \"href='/\" \"href='./\";
        sub_filter \"src='/\" \"src='./\";
        sub_filter \"action='/\" \"action='./\";
        sub_filter \"\\\"/novnc/\" \"\\\"./novnc/\";
        sub_filter \"'/novnc/\" \"'./novnc/\";
        sub_filter \"\\\"/xtermjs/\" \"\\\"./xtermjs/\";
        sub_filter \"'/xtermjs/\" \"'./xtermjs/\";
        sub_filter \"\\\"/api2/\" \"\\\"./api2/\";
        sub_filter \"'/api2/\" \"'./api2/\";
        sub_filter \"\\\"/pve2/\" \"\\\"./pve2/\";
        sub_filter \"'/pve2/\" \"'./pve2/\";
        sub_filter \"</head>\" \"<script>(function(){function b(){var p=window.location.pathname;if(p.endsWith('/'))p=p.slice(0,-1);return p;}function root(p){return p.indexOf('/api2/')===0||p.indexOf('/pve2/')===0||p.indexOf('/novnc/')===0||p.indexOf('/xtermjs/')===0;}function r(u){if(typeof u!=='string')return u;var o=window.location.origin;var w=(window.location.protocol==='https:'?'wss://':'ws://')+window.location.host;if(u.indexOf(o+'/?')===0)return o+b()+u.slice(o.length);if(u.indexOf(w+'/?')===0)return w+b()+u.slice(w.length);if(u.indexOf(o+'/')===0&&root(u.slice(o.length)))return o+b()+u.slice(o.length);if(u.indexOf(w+'/')===0&&root(u.slice(w.length)))return w+b()+u.slice(w.length);if(u.charAt(0)==='?')return b()+'/'+u;if(u.indexOf('/?')===0)return b()+u;if(u.charAt(0)==='/'&&root(u))return b()+u;return u;}window.__pve_ingress_base=b();window.__pve_ingress_rewrite=r;var xo=XMLHttpRequest.prototype.open;XMLHttpRequest.prototype.open=function(m,u){arguments[1]=r(u);return xo.apply(this,arguments);};var wo=window.open;window.open=function(u,n,f){return wo.call(this,r(u),n,f);};if(window.WebSocket){var WS=window.WebSocket;window.WebSocket=function(u,p){return new WS(r(u),p);};window.WebSocket.prototype=WS.prototype;}var sa=Element.prototype.setAttribute;Element.prototype.setAttribute=function(n,v){var k=String(n).toLowerCase();if(k==='src'||k==='href'||k==='action')v=r(v);return sa.call(this,n,v);};function ps(c,p){var d=Object.getOwnPropertyDescriptor(c.prototype,p);if(!d||!d.set)return;Object.defineProperty(c.prototype,p,{get:d.get,set:function(v){return d.set.call(this,r(v));}});}ps(HTMLIFrameElement,'src');ps(HTMLAnchorElement,'href');ps(HTMLFormElement,'action');document.addEventListener('click',function(e){var c=e.target&&e.target.closest;if(!c)return;var a=e.target.closest('a[href]');if(!a)return;var h=a.getAttribute('href');var nh=r(h);if(nh!==h)a.setAttribute('href',nh);},true);if(window.fetch){var fo=window.fetch;window.fetch=function(i,n){if(typeof i==='string')i=r(i);else if(i&&i.url)i=new Request(r(i.url),i);return fo.call(this,i,n);};}})();</script></head>\";
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
        proxy_set_header Origin ${TARGET_ORIGIN};
        proxy_set_header Sec-WebSocket-Protocol \$http_sec_websocket_protocol;
        proxy_set_header Sec-WebSocket-Extensions \$http_sec_websocket_extensions;
        proxy_set_header Sec-WebSocket-Key \$http_sec_websocket_key;
        proxy_set_header Sec-WebSocket-Version \$http_sec_websocket_version;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Host \$host;
        proxy_set_header X-Forwarded-Proto \$external_proto;
        proxy_set_header X-Forwarded-Ssl on;
        proxy_set_header X-Forwarded-Port 443;
        proxy_set_header X-Forwarded-Prefix \$http_x_ingress_path;
        proxy_hide_header Service-Worker-Allowed;
        add_header Cache-Control "no-store";
        add_header X-Proxmox-Proxy "1" always;
        add_header X-Proxmox-Upstream-Status \$upstream_status always;
        add_header X-Proxmox-Upstream-Content-Type \$upstream_http_content_type always;
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
