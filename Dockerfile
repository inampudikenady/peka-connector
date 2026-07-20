FROM node:22-alpine AS frontend-builder

WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build


FROM python:3.13-slim AS backend-builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /build/backend
COPY backend/pyproject.toml ./
COPY backend/app ./app
RUN python -m pip install --prefix=/install .


FROM python:3.13-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PEKA_DATABASE_URL=sqlite+aiosqlite:////data/peka.db \
    PEKA_STATIC_ASSETS_DIR=/app/static

RUN groupadd --gid 10001 peka \
    && useradd --uid 10001 --gid peka --no-create-home peka

WORKDIR /app
COPY --from=backend-builder /install /usr/local
COPY --chown=peka:peka backend/app ./app
COPY --chown=peka:peka backend/alembic ./alembic
COPY --chown=peka:peka backend/alembic.ini ./alembic.ini
COPY --chown=peka:peka backend/docker-entrypoint.sh ./docker-entrypoint.sh
COPY --from=frontend-builder --chown=peka:peka /build/frontend/dist ./static

RUN mkdir -p /data /documents \
    && chown peka:peka /data \
    && chmod 0755 /documents \
    && chmod 0755 ./docker-entrypoint.sh

USER peka
EXPOSE 8080
VOLUME ["/data"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/v1/health', timeout=3)"

ENTRYPOINT ["./docker-entrypoint.sh"]

