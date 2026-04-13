# Merkle-Patricia-Trie

## Web demo (Svelte + FastAPI)

Terminal 1 — API (from repo root):

```bash
python3 -m pip install -e ".[web]"
python3 -m uvicorn api_server:app --reload --host 127.0.0.1 --port 8000
```

Terminal 2 — frontend dev server (proxies `/api` to port 8000):

```bash
cd web && npm install && npm run dev
```

Open `http://localhost:5173`. After `npm run build` in `web/`, you can serve the SPA from the same process as the API at `http://127.0.0.1:8000/` (static files from `web/dist/`).
