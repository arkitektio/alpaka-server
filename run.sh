#!/bin/bash
# Abort on the first failing step: a half-initialised server (no admin, no
# partners, unapplied migrations) must not come up looking healthy.
set -euo pipefail

echo "=> Waiting for DB to be online"
python manage.py wait_for_database -s 6

echo "=> Performing database migrations..."
python manage.py migrate

echo "=> Ensuring Superusers..."
python manage.py ensureadmin

echo "=> Ensuring Provider Partners..."
python manage.py ensurepartners

echo "=> Starting Server"
daphne -b 0.0.0.0 -p 80 --websocket_timeout -1 alpaka_server.asgi:application
