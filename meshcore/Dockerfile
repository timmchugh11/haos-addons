ARG BUILD_ARCH=amd64
FROM homeassistant/${BUILD_ARCH}-base:latest

ARG BUILD_VERSION

RUN apk add --no-cache \
      bash \
      bluez \
      build-base \
      dbus \
      eudev-libs \
      git \
      linux-headers \
      openssl \
      py3-pip \
      py3-wheel \
      python3 \
      python3-dev \
    && python3 -m venv /opt/meshcore-venv

ENV PATH="/opt/meshcore-venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

COPY requirements.txt /tmp/requirements.txt
COPY patch_meshcore_serial.py /tmp/patch_meshcore_serial.py
RUN pip install --upgrade pip setuptools wheel \
    && pip install -r /tmp/requirements.txt \
    && python /tmp/patch_meshcore_serial.py

WORKDIR /app
COPY app.py /app/app.py
COPY custom-ui/ /app/custom-ui/

COPY run.sh /run.sh
RUN chmod a+x /run.sh

LABEL \
  io.hass.version="${BUILD_VERSION}" \
  io.hass.type="addon" \
  io.hass.arch="aarch64|amd64|armhf|armv7|i386"

CMD [ "/run.sh" ]
