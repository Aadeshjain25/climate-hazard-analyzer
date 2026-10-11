FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app

# Run as an unprivileged user
RUN useradd --create-home appuser
USER appuser

EXPOSE 8000
# Render/Cloud Run inject $PORT; default 8000 locally. --proxy-headers lets uvicorn see the real scheme.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
