# Production image for the Farmedia API and web UI.
# Build:  docker build -t farmedia .
# Run:    docker run --env-file .env -p 8000:8000 farmedia
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    APP_ENV=production \
    PORT=8000 \
    FORWARDED_ALLOW_IPS=127.0.0.1

WORKDIR /app

# Unprivileged user: the app never needs root.
RUN useradd --create-home --uid 10001 appuser

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY app.py ./
COPY services ./services
COPY static ./static

USER appuser
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT', '8000') + '/api/health', timeout=4)"

# Shell form so ${PORT} is expanded; exec keeps uvicorn as PID 1 so it stops cleanly on SIGTERM.
CMD ["sh", "-c", "exec uvicorn app:app --host 0.0.0.0 --port ${PORT} --proxy-headers"]
