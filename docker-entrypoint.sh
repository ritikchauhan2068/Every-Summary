#!/bin/sh
set -eu

if [ "${1:-}" = "serve" ]; then
    set -- python -m uvicorn sourcewise.app:app --host 0.0.0.0 --port "${PORT:-8000}"
fi

if [ "$(id -u)" = "0" ]; then
    install -d -m 700 -o sourcewise -g sourcewise "$SOURCEWISE_DATA"
    exec gosu sourcewise "$@"
fi

exec "$@"
