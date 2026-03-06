FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    APP_ENV=production \
    DJANGO_DEBUG=0 \
    SESSION_COOKIE_SECURE=1

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN python manage.py collectstatic --noinput

EXPOSE 8000

CMD set -e && \
    echo '=== Migration Status Before ===' >&2 && \
    python manage.py showmigrations >&2 && \
    echo '=== Running Migrations ===' >&2 && \
    python manage.py migrate --noinput --verbosity=2 >&2 && \
    echo '=== Migration Status After ===' >&2 && \
    python manage.py showmigrations >&2 && \
    echo '=== Starting gunicorn ===' >&2 && \
    exec gunicorn --bind 0.0.0.0:8000 --workers=2 --worker-class=gthread --threads=4 --timeout=120 --graceful-timeout=30 --keep-alive=2 --access-logfile=- --error-logfile=- finglass_project.wsgi:application
