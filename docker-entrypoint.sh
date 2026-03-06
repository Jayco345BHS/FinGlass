#!/bin/bash
set -eux -o pipefail

echo "=== Migration Status Before ==="
python -u manage.py showmigrations

echo ""
echo "=== Running Migrations ==="
python -u manage.py migrate --noinput --verbosity=2

echo ""
echo "=== Migration Status After ==="
python -u manage.py showmigrations

echo ""
echo "=== Starting gunicorn ==="
exec gunicorn --bind 0.0.0.0:8000 \
    --workers=2 \
    --worker-class=gthread \
    --threads=4 \
    --timeout=120 \
    --graceful-timeout=30 \
    --keep-alive=2 \
    --access-logfile=- \
    --error-logfile=- \
    finglass_project.wsgi:application
