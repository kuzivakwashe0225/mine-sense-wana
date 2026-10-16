# MineSense Wana web app: built React bundle served by nginx, which also routes /api and /auth.
FROM node:22-slim AS build
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM nginx:1.28.0-alpine
COPY infra/nginx/default.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/frontend/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=20s --timeout=4s --retries=3 CMD wget -qO- http://127.0.0.1:8080/healthz || exit 1
