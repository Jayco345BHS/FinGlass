FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_DEBUG=0

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN python manage.py collectstatic --noinput

EXPOSE 8000

CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers=2", "--worker-class=gthread", "--threads=4", "--timeout=120", "--graceful-timeout=30", "--keep-alive=2", "--access-logfile=-", "--error-logfile=-", "finglass_project.wsgi:application"]
