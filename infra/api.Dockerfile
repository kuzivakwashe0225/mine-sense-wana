# MineSense Wana API (FastAPI + model pipeline). Runs as a non-root user; only /data is writable.
FROM python:3.12-slim
# rasterio wheels need libexpat, which recent slim images no longer include
RUN apt-get update && apt-get install -y --no-install-recommends libexpat1 && rm -rf /var/lib/apt/lists/* \
 && useradd --system --uid 10001 --home /app wana
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt
COPY backend/wana backend/wana
COPY wana.json ./
ENV WANA_ROOT=/app WANA_DATA=/data WANA_WEB_DIST=/nonexistent
RUN mkdir -p /data && chown wana:wana /data
USER wana
VOLUME /data
WORKDIR /app/backend
EXPOSE 8000
HEALTHCHECK --interval=20s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"
# first start: no model yet, so build the SAMPLE dataset (load real data later with `python -m wana ingest/stack/train`)
CMD ["sh", "-c", "ls /data/runs/v*/model.json >/dev/null 2>&1 || python -m wana all-sample; exec uvicorn wana.api:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips '*' --no-server-header"]
