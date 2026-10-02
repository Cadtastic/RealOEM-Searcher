# The hosted RealOEM Searcher server (hosted design 4.10). Build from the repository root:
#   docker build -f server/Dockerfile -t realoem-searcher .
FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.13 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1 \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1

WORKDIR /app/server
# Dependencies first, so a code change reuses this layer.
COPY server/pyproject.toml server/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY server/ ./
COPY brands/ /app/brands/
RUN uv sync --frozen --no-dev \
    && useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin app \
    && chmod 0755 /app/server/docker-entrypoint.sh

ENV PATH="/app/server/.venv/bin:$PATH" \
    REALOEM_BRANDS_DIR=/app/brands \
    REALOEM_CACHE_DIR=/data/cache \
    REALOEM_DATA_DIR=/data/data
EXPOSE 8080
# Starts as root only to hand the volume to the app user, then drops root for good.
ENTRYPOINT ["/app/server/docker-entrypoint.sh"]
CMD ["realoem-mcp-http"]
