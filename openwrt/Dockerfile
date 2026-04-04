FROM albrechtloh/openwrt-docker:latest

# Install jq to parse Home Assistant options.json
RUN apk add --no-cache jq

# HA adapter script: bridges /data/options.json → environment variables
COPY run.sh /ha-run.sh
RUN chmod +x /ha-run.sh

CMD ["/ha-run.sh"]
