# syntax=docker/dockerfile:1.7

ARG UV_VERSION=0.12.20

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

FROM debian:bookworm-slim AS system

ARG DEBIAN_FRONTEND=noninteractive
ARG RASPBERRY_PI_ARCHIVE_KEY_SHA256=76603890d82a492175caf17aba68dc73acb1189c9fd58ec0c19145dfa3866d56

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_NO_MANAGED_PYTHON=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv

COPY --from=uv /uv /uvx /usr/local/bin/

# Raspberry Pi owns the native GPIO and camera stack. Keep ABI-coupled Python
# packages in apt and expose them to the application virtual environment.
RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        ca-certificates \
        curl \
        gnupg \
    && curl --fail --silent --show-error --location \
        https://archive.raspberrypi.com/debian/raspberrypi.gpg.key \
        --output /tmp/raspberrypi.gpg.key \
    && echo "${RASPBERRY_PI_ARCHIVE_KEY_SHA256}  /tmp/raspberrypi.gpg.key" \
        | sha256sum --check --strict - \
    && gpg --dearmor \
        --output /usr/share/keyrings/raspberrypi-archive-keyring.gpg \
        /tmp/raspberrypi.gpg.key \
    && echo "deb [signed-by=/usr/share/keyrings/raspberrypi-archive-keyring.gpg] https://archive.raspberrypi.com/debian/ bookworm main" \
        > /etc/apt/sources.list.d/raspberrypi.list \
    && apt-get update \
    && apt-get install --yes --no-install-recommends \
        python3 \
        python3-gpiozero \
        python3-lgpio \
        python3-libcamera \
        python3-numpy \
        python3-picamera2 \
    && apt-get purge --yes --auto-remove curl gnupg \
    && rm -f /tmp/raspberrypi.gpg.key \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN uv venv \
        --python /usr/bin/python3 \
        --system-site-packages \
    && .venv/bin/python -c \
        "import gpiozero, libcamera, numpy, picamera2"

ENV PATH="/app/.venv/bin:$PATH" \
    EDGE_HARDWARE_SERVICE_BACKEND=simulation


FROM system AS container-smoke-test

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY tests ./tests

RUN uv sync --frozen

CMD ["uv", "run", "pytest"]


FROM system AS runtime

COPY pyproject.toml uv.lock README.md ./
COPY src ./src

RUN uv sync --frozen --no-dev

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=2).read()"]

CMD ["uvicorn", "edge_hardware_service.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
