# syntax=docker/dockerfile:1

FROM node:22-alpine AS client-build
WORKDIR /app
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web ./
RUN npm run build

FROM caddy:2-alpine AS web
COPY --from=client-build /app/dist /srv
COPY deploy/Caddyfile /etc/caddy/Caddyfile

FROM python:3.12-slim AS api
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
COPY pyproject.toml README.md ./
COPY mpt ./mpt
RUN pip install --no-cache-dir ".[web]"
COPY api_server.py ./
# api_server.py expects ./db to exist; it stays empty because the public demo disables on-disk DBs.
RUN mkdir db
USER nobody
EXPOSE 8000
CMD ["uvicorn", "api_server:app", "--host", "0.0.0.0", "--port", "8000"]
