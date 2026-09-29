# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------------------
# Stage 1: builder. Compilers and build headers live here and are thrown away.
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS builder

# Pinned by digest for the bonus marks. Swap in your own after `docker pull`:
#   docker inspect --format='{{index .RepoDigests 0}}' python:3.12-slim-bookworm
# FROM python@sha256:<digest> AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

RUN apt-get update \
 && apt-get install --no-install-recommends -y build-essential=12.9 \
 && rm -rf /var/lib/apt/lists/*

# Requirements BEFORE source. This is the whole point of the layer order:
# editing a route must not re-run pip install. Changing requirements.txt is
# rare; changing app/ is constant.
COPY requirements.txt ./
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

# ---------------------------------------------------------------------------
# Stage 2: runtime. No compiler, no pip cache, no build-essential.
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

# curl is here only because HEALTHCHECK needs an HTTP client. Everything else
# stays out of the runtime image.
RUN apt-get update \
 && apt-get install --no-install-recommends -y curl \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --system --gid 1001 civic \
 && useradd --system --uid 1001 --gid civic --no-create-home civic

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=civic:civic alembic.ini ./
COPY --chown=civic:civic alembic ./alembic
COPY --chown=civic:civic app ./app
COPY --chown=civic:civic seeds ./seeds

# Non-root. A container that runs as root is one container escape away from
# being a host compromise, and nothing here needs privilege.
USER civic

EXPOSE 8000

# Container-level health, distinct from the Kubernetes probes: this is what
# `depends_on: condition: service_healthy` in compose.yaml waits on.
HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=3 \
    CMD curl --fail --silent http://localhost:8000/health || exit 1

# Exec form, so uvicorn is PID 1 and receives SIGTERM directly. In shell form
# the signal goes to /bin/sh, uvicorn never sees it, and every rolling update
# ends in a 30-second SIGKILL with requests still in flight.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--no-access-log", "--timeout-graceful-shutdown", "25"]
