ARG BUILD_FROM
FROM $BUILD_FROM

RUN apk add --no-cache hostapd dnsmasq iw iptables jq usbutils

COPY run.sh /run.sh
RUN chmod +x /run.sh

CMD ["/run.sh"]
