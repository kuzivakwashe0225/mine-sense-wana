FROM node:22-slim AS web
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
# rasterio wheels need libexpat, which recent slim images no longer include
RUN apt-get update && apt-get install -y --no-install-recommends libexpat1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/ backend/
COPY wana.json ./
COPY --from=web /app/frontend/dist frontend/dist
ENV WANA_ROOT=/app WANA_DATA=/data
VOLUME /data
WORKDIR /app/backend
EXPOSE 8000
CMD ["python", "-m", "wana", "serve", "--host", "0.0.0.0", "--port", "8000"]
