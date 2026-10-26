# Packaging wrapper around Proton's unmodified official Linux release.
# The installer is amd64; the connector itself remains architecture-independent.
FROM debian:bookworm-slim
ARG BRIDGE_VERSION=3.27.1
ARG BRIDGE_SHA256=d69eab5674335a41428bf77bde6a9f85667867e2083205625a710f6948e54d86
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl gnupg pass \
    && curl --fail --location --proto '=https' --tlsv1.2 \
       "https://github.com/ProtonMail/proton-bridge/releases/download/v${BRIDGE_VERSION}/protonmail-bridge_${BRIDGE_VERSION}-1_amd64.deb" \
       --output /tmp/bridge.deb \
    && printf '%s  /tmp/bridge.deb\n' "$BRIDGE_SHA256" | sha256sum --check --strict \
    && apt-get install -y --no-install-recommends /tmp/bridge.deb \
    && rm -f /tmp/bridge.deb && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 bridge && useradd --uid 10001 --gid bridge --home-dir /data --no-create-home bridge \
    && mkdir /data && chown bridge:bridge /data
ENV HOME=/data GNUPGHOME=/data/gnupg PASSWORD_STORE_DIR=/data/password-store \
    XDG_CONFIG_HOME=/data/config XDG_CACHE_HOME=/data/cache XDG_DATA_HOME=/data/share
COPY bridge-entrypoint.sh /usr/local/bin/bridge-entrypoint
RUN chmod 0755 /usr/local/bin/bridge-entrypoint
USER 10001:10001
WORKDIR /data
ENTRYPOINT ["/usr/local/bin/bridge-entrypoint"]
CMD ["--noninteractive"]
