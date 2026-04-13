# Merkle Patricia Trie (MPT)

## Web demo (Svelte + FastAPI)

### Dev (recommended)

```bash
python3 -m pip install -e ".[web]"
python3 -m uvicorn api_server:app --reload --host 127.0.0.1 --port 8000
```

```bash
cd web
npm install
npm run dev
```

Open `http://localhost:5173` (Vite proxies `/api/*` to `127.0.0.1:8000`).

### Single server (serve `web/dist` from FastAPI)

```bash
cd web && npm run build
python3 -m uvicorn api_server:app --host 127.0.0.1 --port 8000
```
