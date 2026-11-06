# Use a Python image with uv pre-installed
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

# Install the project into `/app`
WORKDIR /app

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1

# Copy from the cache instead of linking since it's a mounted volume
ENV UV_LINK_MODE=copy

# Omit development dependencies
ENV UV_NO_DEV=1

# Ensure installed tools can be executed out of the box
ENV UV_TOOL_BIN_DIR=/usr/local/bin

# Install the project's dependencies using the lockfile and settings
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project

# Then, add the rest of the project source code and install it
# Installing separately from its dependencies allows optimal layer caching
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked

# Place executables in the environment at the front of the path
ENV PATH="/app/.venv/bin:$PATH"

# Compile translations
RUN uv run pybabel compile -d src/locales -D messages

# Run as an unprivileged user. Configuration and logs live in /app/data, which is MOUNTED at runtime:
#   docker run -v /path/to/dir-with-config.yml:/app/data ...
# No secret (Telegram token, qBittorrent password) is ever part of the image.
RUN groupadd --gid 1000 bot && useradd --uid 1000 --gid 1000 --no-create-home --shell /usr/sbin/nologin bot \
    && mkdir -p /app/data && chown bot:bot /app/data
VOLUME ["/app/data"]
USER bot

LABEL org.opencontainers.image.title="qbittorrent-bot-rss" \
      org.opencontainers.image.description="Telegram bot for qBittorrent with RSS management. Configuration is mounted at /app/data." \
      org.opencontainers.image.source="https://github.com/DimaBroi/QBittorrentBot" \
      org.opencontainers.image.licenses="GPL-3.0"

# Reset the entrypoint and start python directly (no `uv run` at runtime)
ENTRYPOINT []

CMD ["python", "-m", "src.main"]