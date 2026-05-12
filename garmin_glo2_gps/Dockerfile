ARG BUILD_FROM
FROM ${BUILD_FROM}

RUN apk add --no-cache \
    bash \
    bluez \
    bluez-deprecated \
    coreutils \
    jq \
    kmod \
    python3 \
    py3-pip \
    util-linux

RUN pip3 install --break-system-packages --no-cache-dir \
    pynmea2==1.19.0

COPY run.sh /run.sh
COPY garmin_glo2.py /garmin_glo2.py
RUN chmod a+x /run.sh

CMD ["/run.sh"]
