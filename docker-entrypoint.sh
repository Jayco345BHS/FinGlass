#!/bin/bash
set -e

echo "=== Migration Status Before ==="
python -u manage.py showmigrations

echo "=== Running Migrations ==="
python -u manage.py migrate --noinput --verbosity=2

echo "=== Migration Status After ==="
python -u manage.py showmigrations

echo "=== Starting gunicorn ==="
exec gunicorn --bind 0.0.0.0:8000 --workers=2 --worker-class=gthread --threads=4 --timeout=120 --graceful-timeout=30 --keep-alive=2 --access-logfile=- --error-logfile=- finglass_project.wsgi:application
