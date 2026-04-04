ARG BUILD_FROM
FROM $BUILD_FROM

# Install Node.js (base images are Alpine-based)
RUN apk add --no-cache nodejs npm

WORKDIR /app

# Install dependencies first (layer cache friendly)
COPY package.json ./
RUN npm install --omit=dev

# Copy application files
COPY server.js ./
COPY public/ ./public/

# Add and permission the entrypoint
COPY run.sh /run.sh
RUN chmod a+x /run.sh

# Required labels for HA Supervisor
LABEL \
    io.hass.version="1.0.0" \
    io.hass.type="addon" \
    io.hass.arch="aarch64|amd64|armhf|armv7|i386"

CMD [ "/run.sh" ]
