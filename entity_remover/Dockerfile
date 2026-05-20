ARG BUILD_FROM
FROM ${BUILD_FROM}

RUN apk add --no-cache \
    bash \
    jq \
    python3

COPY run.sh /run.sh
COPY entity_remover.py /entity_remover.py
RUN chmod a+x /run.sh

CMD ["/run.sh"]
