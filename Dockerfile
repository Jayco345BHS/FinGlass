FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_ENV=production \
    DJANGO_DEBUG=0 \
    SESSION_COOKIE_SECURE=1

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN python manage.py collectstatic --noinput

EXPOSE 8000

CMD sh -c "set -e && \
    echo 'Running database migrations...' && \
    python manage.py migrate --noinput && \
    echo 'Migrations complete. Starting gunicorn...' && \
    gunicorn --bind 0.0.0.0:8000 --workers=2 --worker-class=gthread --threads=4 --timeout=120 --graceful-timeout=30 --keep-alive=2 --access-logfile=- --error-logfile=- finglass_project.wsgi:application"
