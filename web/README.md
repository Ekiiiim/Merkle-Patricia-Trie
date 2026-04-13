# Web frontend (Svelte + Vite)

The app talks to the FastAPI backend via `/api/*`.

## Dev

```bash
npm install
npm run dev
```

Vite proxies `/api` → `http://127.0.0.1:8000` (see `vite.config.ts`). Open the URL it prints (usually `http://localhost:5173`).

## Build

```bash
npm run build
```

If `web/dist` exists, the backend (`api_server.py`) will serve it when you run uvicorn from the repo root.
