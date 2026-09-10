#!/bin/bash
# Abort on the first failing step: a half-initialised server (no admin, no
# partners, unapplied migrations) must not come up looking healthy.
set -euo pipefail

echo "=> Waiting for DB to be online"
python manage.py wait_for_database -s 2

echo "=> Performing database migrations..."
python manage.py migrate

echo "=> Ensuring Superusers..."
python manage.py ensureadmin

echo "=> Ensuring Provider Partners..."
python manage.py ensurepartners

echo "=> Starting Server"
python manage.py runserver 0.0.0.0:80
