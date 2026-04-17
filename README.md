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

### Deploy as one app (frontend + API) (Option 4)

This repo can be deployed as a single service: FastAPI serves both:
- the API under `/api/*`
- the built frontend from `web/dist` at `/`

The app auto-serves the frontend when `web/dist` exists:
`api_server.py` mounts `StaticFiles(..., html=True)` at `/`.

#### Render (recommended easiest)

This repo includes `render.yaml` (a Render Blueprint).

- **Deploy**
  - Create a new Render service from this repo (Blueprint).
  - Render will run the build that installs Python deps, builds the frontend, then starts `uvicorn`.

- **Local prod-like run**

```bash
python3 -m pip install -e ".[web]"
cd web && npm ci && npm run build
cd .. && python3 -m uvicorn api_server:app --host 127.0.0.1 --port 8000
```

Then open `http://127.0.0.1:8000`.

### Static hosting (GitHub Pages) + hosted API (Option 3)

GitHub Pages can host the **static frontend** from `web/`, but the demo still needs a running API for `/api/*`.

- **Frontend (GitHub Pages)**
  - The repo includes a GitHub Actions workflow at `.github/workflows/deploy-gh-pages.yml` that builds `web/` and deploys `web/dist` to Pages.
  - Set the API origin in GitHub:
    - **Settings → Secrets and variables → Actions → Variables**
    - Add `VITE_API_BASE` = `https://your-api.example.com`
  - The deployed site will call `https://your-api.example.com/api/...` instead of `/api/...`.

- **API (hosted elsewhere)**
  - Ensure CORS allows requests from your Pages origin.
  - Configure either:
    - `MPT_CORS_ORIGINS="https://<user>.github.io"` (comma-separated list), or
    - `MPT_CORS_ORIGIN_REGEX="^https://[^/]+\\.github\\.io$"` (regex)
  - Then run the API with your host/port, for example:

```bash
python3 -m uvicorn api_server:app --host 0.0.0.0 --port 8000
```
