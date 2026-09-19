# MPT Demo Deploy

Public hostname: `mpt.minyu.me`

```bash
cd Merkle-Patricia-Trie
docker compose up -d --build
```

- `mpt-api`: FastAPI (`uvicorn api_server:app`) on internal port `8000`. It runs with
  `MPT_PUBLIC_DEMO=true`, so the on-disk RocksDB stores under `./db` are never loaded,
  and is capped at 512 MB of memory.
- `mpt-web`: Caddy serving the built Svelte client and proxying `/api/*` to `mpt-api`.
  Only this container joins the shared `web` network.

The shared proxy should include (`~/deploy/proxy/sites/mpt.caddy`):

```caddy
mpt.minyu.me {
	reverse_proxy mpt-web:80
}
```

After adding or changing a site file, reload the shared proxy:

```bash
cd ~/deploy/proxy
docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
```

## Update

```bash
git pull
docker compose up -d --build
```
