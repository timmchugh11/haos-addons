ARG BUILD_FROM
FROM $BUILD_FROM

RUN apk add --no-cache nodejs npm

WORKDIR /app

COPY package.json ./
RUN npm install --omit=dev

COPY server.js ./
COPY public/ ./public/

COPY run.sh /run.sh
RUN chmod a+x /run.sh

LABEL \
    io.hass.version="0.1.0" \
    io.hass.type="addon" \
    io.hass.arch="aarch64|amd64|armhf|armv7|i386"

CMD [ "/run.sh" ]
