ARG BUILD_FROM=ghcr.io/home-assistant/base:latest
FROM $BUILD_FROM

# Install Python 3, FFmpeg, and Pillow for full feature support
RUN apk add --no-cache \
    python3 \
    py3-pip \
    ffmpeg \
    py3-pillow \
    bash

# Install copyparty from PyPI
RUN pip3 install --no-cache-dir --break-system-packages copyparty

# Copy and configure the startup script
COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD ["/run.sh"]
