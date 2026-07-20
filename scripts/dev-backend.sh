#!/bin/sh
set -eu

cd "$(dirname "$0")/../backend"
alembic upgrade head
exec uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

