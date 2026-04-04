ARG BUILD_FROM
FROM $BUILD_FROM

# Install Node.js and native build tools (better-sqlite3 requires compilation)
RUN apk add --no-cache nodejs npm python3 make g++ linux-headers && \
    npm install -g node-gyp

ENV PYTHON=/usr/bin/python3

WORKDIR /app

# Install dependencies first (layer cache friendly)
COPY package.json package-lock.json ./
RUN npm ci --omit=dev

# Copy application files
COPY server.js ./
COPY public/ ./public/

# Add and permission the entrypoint
COPY run.sh /run.sh
RUN chmod a+x /run.sh

# Required labels for HA Supervisor
LABEL \
    io.hass.version="1.0.2" \
    io.hass.type="addon" \
    io.hass.arch="aarch64|amd64|armhf|armv7|i386"

CMD [ "/run.sh" ]
