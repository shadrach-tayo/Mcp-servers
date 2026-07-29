# Memory MCP on AWS EC2 — Setup Q&A

Review guide covering common issues while deploying **Memory MCP** (`memory_mcp.server:app`) on **Amazon Linux EC2**, with **nginx**, **Cloudflare** (`mcp.livemigrate.ai`), **Let’s Encrypt**, **Google OAuth**, and **Upstash Redis**.

---

## Architecture & URLs

### Q: What is the public MCP endpoint URL?

**A:** With default env:

- `MCP_MOUNT_PREFIX=/api`
- `MCP_PATH=/mcp`

Clients use:

```text
https://mcp.livemigrate.ai/api/mcp
```

Health check:

```text
https://mcp.livemigrate.ai/api/health
```

(`GET` should return `OK`.)

### Q: Why does `curl http://127.0.0.1:8007/health` return nothing or 404?

**A:** Health is registered on the FastMCP app **under the mount prefix**, not at the Starlette root. With `MCP_MOUNT_PREFIX=/api`, use:

```bash
curl -s http://127.0.0.1:8007/api/health
```

Plain `/health` returns **404 Not Found** (not an empty body). Exit code `000` from curl usually means **nothing is listening** on 8007 (service down).

### Q: What should `BASE_URL` be in `/etc/mcp-servers/env`?

**A:** The URL users and OAuth see in the browser — **scheme + host**, no path:

```bash
BASE_URL=https://mcp.livemigrate.ai
```

Do **not** put `/api` in `BASE_URL`; the server combines `BASE_URL` + `MCP_MOUNT_PREFIX` for auth base URL internally.

### Q: Why must nginx proxy `/` and not only `/api/`?

**A:** The Starlette app mounts OAuth **`.well-known`** routes at the **root**. MCP tools live under `/api/*`. A config that only proxies `/api/` breaks OAuth discovery and login. The repo nginx config proxies **`location /`** to Uvicorn.

---

## Environment file on EC2

### Q: Why does `source /etc/mcp-servers/env` fail with “Permission denied”?

**A:** The file is **`chmod 600`** and owned by **root**. SSM users (`ssm-user`) cannot read it.

**You do not need** to source it for production: **systemd** reads `EnvironmentFile=` as root before dropping to `User=ec2-user`.

For a one-off manual test as root:

```bash
sudo bash -c 'set -a && . /etc/mcp-servers/env && set +a && cd /opt/mcp-servers && runuser -u ec2-user -- env PATH="/opt/mcp-servers/.venv/bin:$PATH" PYTHONPATH=/opt/mcp-servers/src ...'
```

### Q: Should I use `.env` in the repo on EC2?

**A:** **No.** Use **`/etc/mcp-servers/env`** only (see `deploy/aws-ec2/env.example`). Never commit secrets.

### Q: What env vars are required for the server to start?

**A:** At minimum:

- `OAUTH_CLIENT_ID`, `OAUTH_CLIENT_SECRET`
- `JWT_SIGNING_KEY`, `STORAGE_ENCRYPTION_KEY`
- `REDIS_URL` (Upstash **`rediss://`** TCP URL, not REST)
- `BASE_URL`
- `MCP_MOUNT_PREFIX=/api` and usually `MCP_PATH=/mcp`

Missing vars cause **import-time crash** with `RuntimeError: Missing required environment variable ...`.

---

## systemd & Uvicorn

### Q: What does `status=217/USER` mean?

**A:** The **`User=`** in the unit file does not exist on the OS. Deploy units default to **`ec2-user`** on Amazon Linux. **`www-data`** exists on Ubuntu, not AL2023.

Fix: set `User=ec2-user` / `Group=ec2-user` and `chown -R ec2-user:ec2-user /opt/mcp-servers`.

### Q: What does `status=203/EXEC` or “Failed to execute ... uvicorn: Permission denied” mean?

**A:** systemd could not run `ExecStart`. Common causes:

1. **Wrong unit** still calling `/opt/mcp-servers/.venv/bin/uvicorn` instead of **`python -m uvicorn`**
2. **Venv built as `ssm-user`** but service runs as **`ec2-user`** — `.venv/bin/python` symlinks to `/home/ssm-user/.local/share/uv/...` and ec2-user cannot execute it

Fix venv ownership:

```bash
sudo -u ec2-user bash -lc 'cd /opt/mcp-servers && rm -rf .venv && uv sync --frozen --no-dev'
```

Use in unit:

```ini
ExecStart=/opt/mcp-servers/.venv/bin/python -m uvicorn memory_mcp.server:app --host 127.0.0.1 --port 8007
Environment=PYTHONPATH=/opt/mcp-servers/src
```

**Rule:** Run **`uv sync`** as the **same user** as `User=` in systemd (`ec2-user`), not from SSM as `ssm-user`.

### Q: Direct vs nginx systemd unit?

**A:**

| Mode | Unit | Uvicorn bind |
|------|------|----------------|
| ALB / lab on :8007 | `memory-mcp.service` | `0.0.0.0:8007` |
| nginx on instance | `memory-mcp-nginx.service` | `127.0.0.1:8007` |

With nginx, do **not** expose 8007 on the security group.

---

## Git on EC2

### Q: `git pull` — “dubious ownership” and “cannot open .git/FETCH_HEAD: Permission denied”?

**A:** Repo owned by **`ec2-user`**, you are **`ssm-user`**.

```bash
git config --global --add safe.directory /opt/mcp-servers   # fixes dubious ownership warning only
sudo -u ec2-user git -C /opt/mcp-servers pull             # actual pull
```

---

## nginx & TLS

### Q: `nginx -t` fails — cannot load certificate ... fullchain.pem?

**A:** **`memory-mcp.conf`** references Let’s Encrypt paths **before** certbot has created them. Order matters:

1. **`memory-mcp.bootstrap.conf`** (HTTP only on :80)
2. **`certbot certonly --webroot`**
3. **`memory-mcp.conf`** (HTTPS on :443)
4. `sudo nginx -t && sudo systemctl reload nginx`

Always run **`sudo nginx -t`** (not as unprivileged user).

### Q: Cloudflare Origin cert vs Let’s Encrypt on nginx — which is recommended?

**A:** **Let’s Encrypt on nginx** + Cloudflare **Full (strict)**:

- Publicly trusted cert on the origin
- Works if you later change DNS/proxy
- Standard certbot renewal

**Cloudflare Origin** cert is optional when you cannot open port 80 or want fastest paste-and-go PEM setup.

### Q: Cloudflare DNS for `mcp.livemigrate.ai`?

**A:** **A** record `mcp` → EC2 public IP. Proxied (orange cloud) is OK with **Full (strict)** once origin has a valid cert.

Security group: **443** (and **80** for HTTP-01 + redirect). Block **8007** from the internet when using nginx.

### Q: What is `memory-mcp.bootstrap.conf` for?

**A:** Serves HTTP on port **80**, proxies to Uvicorn, exposes **`/.well-known/acme-challenge/`** for certbot. Use until LE files exist under `/etc/letsencrypt/live/mcp.livemigrate.ai/`.

---

## Redis (Upstash)

### Q: What Redis URL format?

**A:** **`rediss://`** (TLS) TCP endpoint from Upstash, not the REST URL. Server stores OAuth client state in Redis via `RedisStore` + Fernet encryption wrapper.

### Q: Local `memory-client` failed connecting to `localhost:6379`?

**A:** Client used `RedisStore` without `REDIS_URL`, defaulting to local Redis. Fix: use Redis only when `REDIS_URL` is set; otherwise FastMCP uses **in-memory** token storage.

```bash
uv run memory-client
uv run --env-file .env memory-client   # persistent tokens via Upstash
```

Optional: `MCP_CLIENT_URL=https://mcp.livemigrate.ai/api/mcp`

---

## OAuth & clients

### Q: Google OAuth — what to configure?

**A:** In Google Cloud Console for the same client ID as EC2 env:

- **Authorized JavaScript origins:** `https://mcp.livemigrate.ai`
- **Redirect URIs:** match FastMCP/Google provider (often under `https://mcp.livemigrate.ai/api/...`). Add exact URI from the first browser error if mismatch.

Restart `memory-mcp` after changing `BASE_URL`.

### Q: Claude / remote MCP URL?

**A:** `https://mcp.livemigrate.ai/api/mcp` with OAuth — not stdio. Stdio bypasses HTTP OAuth.

### Q: Verify OAuth metadata?

**A:**

```bash
curl -sI https://mcp.livemigrate.ai/.well-known/oauth-authorization-server
curl -sI https://mcp.livemigrate.ai/.well-known/oauth-protected-resource
```

Should not be nginx **404**.

---

## End-to-end checklist

1. `uv sync` as **ec2-user**; `/etc/mcp-servers/env` complete; `memory-mcp` active  
2. `curl -s http://127.0.0.1:8007/api/health` → `OK`  
3. nginx bootstrap → certbot → full `memory-mcp.conf` → reload  
4. `curl -s https://mcp.livemigrate.ai/api/health` → `OK`  
5. Cloudflare **Full (strict)**  
6. Google OAuth URIs; connect Claude to `/api/mcp`  
7. `sudo certbot renew --dry-run`; `systemctl enable memory-mcp nginx`

---

## Quick reference commands

```bash
# Service
sudo systemctl restart memory-mcp
sudo journalctl -u memory-mcp -n 50 --no-pager

# App update
sudo -u ec2-user git -C /opt/mcp-servers pull

# nginx
sudo nginx -t && sudo systemctl reload nginx

# Health
curl -s https://mcp.livemigrate.ai/api/health
```

---

*Generated from deployment practice for the mcp-starter Memory MCP project. Repo paths: `deploy/aws-ec2/`, `src/memory_mcp/`.*
