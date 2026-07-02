ARG BUILD_FROM
FROM $BUILD_FROM

RUN apk add --no-cache nginx

COPY run.sh /run.sh
RUN chmod a+x /run.sh

LABEL \
    io.hass.version="0.1.10" \
    io.hass.type="addon" \
    io.hass.arch="aarch64|amd64|armhf|armv7|i386"

CMD [ "/run.sh" ]
