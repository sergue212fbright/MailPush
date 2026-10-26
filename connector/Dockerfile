FROM python:3.12-slim-bookworm AS build
WORKDIR /build
COPY pyproject.toml README.md LICENSE requirements-lock.txt ./
COPY src ./src
RUN python -m pip wheel --no-cache-dir --wheel-dir /wheels -r requirements-lock.txt .

FROM python:3.12-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 MAILPUSH_CONFIG=/config/config.toml MAILPUSH_STATE_DIR=/data
RUN groupadd --gid 10001 mailpush && useradd --uid 10001 --gid mailpush --no-create-home mailpush \
    && mkdir /config /data && chown mailpush:mailpush /data
COPY --from=build /wheels /wheels
RUN python -m pip install --no-cache-dir --no-index --find-links=/wheels mailpush-connector \
    && rm -r /wheels
USER 10001:10001
WORKDIR /data
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 CMD ["mailpush", "healthcheck", "--state-dir", "/data"]
ENTRYPOINT ["mailpush"]
CMD ["run", "--config", "/config/config.toml"]
