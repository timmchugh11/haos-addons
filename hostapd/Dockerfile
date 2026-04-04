ARG BUILD_FROM
FROM $BUILD_FROM

RUN apk add --no-cache hostapd dnsmasq iw iptables jq usbutils python3 py3-flask py3-gunicorn

COPY run.sh /run.sh
COPY web/ /web/
RUN chmod +x /run.sh

CMD ["/run.sh"]
