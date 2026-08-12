ARG PEKA_CONNECTOR_VERSION=1.0.2
ARG PEKA_BUILD_REVISION=local
ARG PEKA_BUILD_CREATED=unknown
ARG PEKA_BUILD_SOURCE=local

FROM node:22-alpine AS frontend-builder

WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build


FROM python:3.13-slim AS backend-builder

ARG PEKA_CONNECTOR_VERSION
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /build/backend
COPY backend/pyproject.toml ./
COPY VERSION /build/VERSION
COPY backend/app ./app
COPY backend/scripts ./scripts
RUN test "$(tr -d '\r\n' < /build/VERSION)" = "${PEKA_CONNECTOR_VERSION}" \
    && PYTHONPATH=. python scripts/prepare_build_version.py \
       "${PEKA_CONNECTOR_VERSION}" pyproject.toml app/core/_build_version.py
RUN python -m pip install --prefix=/install .


FROM python:3.13-slim AS runtime

ARG PEKA_CONNECTOR_VERSION
ARG PEKA_BUILD_REVISION
ARG PEKA_BUILD_CREATED
ARG PEKA_BUILD_SOURCE
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PEKA_DATABASE_URL=sqlite+aiosqlite:////data/state/peka.db \
    PEKA_DATA_ROOT=/data \
    PEKA_SOURCES_ROOT=/data/sources \
    PEKA_STATIC_ASSETS_DIR=/app/static \
    PEKA_BUILD_ID=${PEKA_BUILD_REVISION}

LABEL org.opencontainers.image.title="PEKA Connector" \
      org.opencontainers.image.version="${PEKA_CONNECTOR_VERSION}" \
      org.opencontainers.image.revision="${PEKA_BUILD_REVISION}" \
      org.opencontainers.image.created="${PEKA_BUILD_CREATED}" \
      org.opencontainers.image.source="${PEKA_BUILD_SOURCE}"

RUN groupadd --gid 10001 peka \
    && useradd --uid 10001 --gid peka --no-create-home peka

WORKDIR /app
COPY --from=backend-builder /install /usr/local
COPY --chown=peka:peka backend/app ./app
COPY --chown=peka:peka VERSION release.json ./
COPY --from=backend-builder --chown=peka:peka /build/backend/app/core/_build_version.py ./app/core/_build_version.py
COPY --chown=peka:peka backend/alembic ./alembic
COPY --chown=peka:peka backend/alembic.ini ./alembic.ini
COPY --chown=peka:peka backend/docker-entrypoint.sh ./docker-entrypoint.sh
COPY --from=frontend-builder --chown=peka:peka /build/frontend/dist ./static

RUN mkdir -p /data/state /data/config /data/logs /data/spool /data/external-sources /data/sources/documents /data/sources/cmdb \
    && chown peka:peka /data \
    && chown peka:peka /data/state /data/config /data/logs /data/spool \
    && chmod 0700 /data/state /data/config /data/logs /data/spool \
    && chown peka:peka /data/sources/documents /data/sources/cmdb \
    && chmod 0755 /data/external-sources /data/sources \
    && chmod 0700 /data/sources/documents /data/sources/cmdb \
    && chmod 0755 ./docker-entrypoint.sh

USER peka
EXPOSE 8080
VOLUME ["/data"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/v1/health', timeout=3)"

ENTRYPOINT ["./docker-entrypoint.sh"]
