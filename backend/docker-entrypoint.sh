#!/bin/sh
set -eu
umask 077

mkdir -p /data/state /data/config /data/logs /data/spool /data/sources/documents /data/sources/cmdb
chmod 0700 /data/state /data/config /data/logs /data/spool /data/sources/documents /data/sources/cmdb

alembic upgrade head
exec uvicorn app.main:app --host 0.0.0.0 --port 8080 --proxy-headers --forwarded-allow-ips="*"
