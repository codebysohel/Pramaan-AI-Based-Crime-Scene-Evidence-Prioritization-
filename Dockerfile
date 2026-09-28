FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PRAMAAN_HOME=/data APP_HOST=0.0.0.0 APP_PORT=8000 \
    PRAMAAN_ALLOWED_HOSTS="127.0.0.1:*,localhost:*,[::1]:*"
WORKDIR /app/src
COPY src/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ .
RUN useradd -r -u 10001 pramaan && mkdir -p /data && chown pramaan /data
USER pramaan
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health')" || exit 1
CMD ["sh", "-c", "python -m pramaan seed >/dev/null 2>&1 || true; python -m pramaan serve --host 0.0.0.0 --port 8000"]
