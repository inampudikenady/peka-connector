#!/bin/sh
set -eu
umask 077

secret_directory=/data/config/secrets
mkdir -p /data/state /data/config /data/logs /data/spool \
    /data/sources/documents /data/sources/cmdb "$secret_directory"
chmod 0700 /data/state /data/config /data/logs /data/spool \
    /data/sources/documents /data/sources/cmdb "$secret_directory"

persist_secret() {
    secret_path=$1
    legacy_value=$2
    if [ ! -s "$secret_path" ]; then
        temporary_path="${secret_path}.tmp.$$"
        if [ -n "$legacy_value" ]; then
            printf '%s' "$legacy_value" > "$temporary_path"
        else
            python -c 'import secrets; print(secrets.token_urlsafe(48), end="")' > "$temporary_path"
        fi
        chmod 0600 "$temporary_path"
        mv "$temporary_path" "$secret_path"
    fi
    chmod 0600 "$secret_path"
}

persist_secret "$secret_directory/jwt_secret" "${PEKA_JWT_SECRET:-}"
persist_secret "$secret_directory/encryption_key" "${PEKA_ENCRYPTION_KEY:-}"

PEKA_JWT_SECRET=$(tr -d '\r\n' < "$secret_directory/jwt_secret")
PEKA_ENCRYPTION_KEY=$(tr -d '\r\n' < "$secret_directory/encryption_key")
export PEKA_JWT_SECRET PEKA_ENCRYPTION_KEY

python -m app.core.preflight
alembic upgrade head
exec uvicorn app.main:app --host 0.0.0.0 --port 8080 --proxy-headers --forwarded-allow-ips="*"
