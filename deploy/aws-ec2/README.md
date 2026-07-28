# Memory MCP — ASGI on AWS EC2 (practice)

This guide uses the **ASGI app** in `memory_mcp.server:app` (`mcp.http_app(stateless_http=True)`), which matches [FastMCP HTTP deployment](https://gofastmcp.com/deployment/http#asgi-application) and supports **multiple Uvicorn workers** and **multiple EC2 instances** behind an ALB.

## Local ASGI (fix common uvicorn mistake)

Uvicorn imports a **Python module**, not a file path. Package name uses underscores:

```bash
# Wrong (will fail):
# uvicorn src/memory-mcp/__init__.py:app

# Correct:
uv run --env-file .env uvicorn memory_mcp.server:app --host 0.0.0.0 --port 8007
```

Health: `curl http://127.0.0.1:8007/health`  
MCP: `http://127.0.0.1:8007/mcp`

Required env (see `env.example`):

- `OAUTH_CLIENT_ID`, `OAUTH_CLIENT_SECRET`
- `MCP_BASE_URL` — public URL clients use (HTTPS in prod)

---

## Part 1 — Single EC2 instance

### 1. AWS setup

1. Launch **Ubuntu 24.04** EC2 (e.g. `t3.small`), same VPC as any DB you need.
2. **Security group**
   - Inbound: `22` from your IP, `443` from `0.0.0.0/0` (or restrict).
   - Do **not** expose `8007` publicly; nginx terminates TLS on 443.
3. Elastic IP (optional but useful for stable DNS).
4. Route53 (or external DNS): `memory-mcp.example.com` → instance IP or ALB (Part 2).

### 2. Install on the VM

**SSM Session Manager:** new shells often start in `/usr/bin`. Always `cd` to the repo with an **absolute path** before `uv sync`, or you get errors like  
`Permission denied` on `/usr/bin/opt/Mcp-servers/.venv`.

#### Ubuntu / Debian

```bash
sudo apt-get update && sudo apt-get install -y git nginx certbot python3-venv build-essential libpq-dev python3-dev
```

#### Amazon Linux 2023 / RHEL / Fedora (`dnf` / `yum`)

Debian package names **do not work**. Use:

```bash
sudo dnf install -y git nginx python3-devel postgresql-devel gcc gcc-c++ make
# certbot on AL2023 (optional, for TLS):
# sudo dnf install -y certbot python3-certbot-nginx
```

| Ubuntu (apt)        | Amazon Linux (dnf)   |
|---------------------|----------------------|
| `build-essential`   | `gcc gcc-c++ make`   |
| `libpq-dev`         | `postgresql-devel`   |
| `python3-dev`       | `python3-devel`      |

#### Common steps (all distros)

```bash
# Clone your repo (or rsync artifact)
sudo mkdir -p /opt && sudo chown "$USER:$USER" /opt
git clone <your-repo> /opt/Mcp-servers
cd /opt/Mcp-servers
pwd   # must be /opt/Mcp-servers, not /usr/bin

# Install uv (see https://docs.astral.sh/uv/)
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

uv sync --frozen --no-dev
```

If `uv sync` fails building `psycopg2` with **`pg_config executable not found`**, install the Postgres **devel** packages above **or** `git pull` the latest repo (uses **`psycopg2-binary`**, no compile).

If the repo was cloned as root, fix ownership then sync as the app user:

```bash
sudo chown -R "$USER:$USER" /opt/Mcp-servers   # or /opt/mcp-servers — match your path
cd /opt/Mcp-servers
uv sync --frozen --no-dev
```

**Do not** run `sudo uv sync`: `uv` is usually installed in `~/.local/bin` and is not on root’s `PATH`. Prefer fixing directory ownership and running `uv` as your user.

If you truly must run as root once (not recommended):

```bash
sudo env "PATH=$HOME/.local/bin:$PATH" uv sync --frozen --no-dev
```

Better: install the app under the deploy user’s home directory to avoid `/opt` permission issues:

```bash
git clone <your-repo> ~/Mcp-servers
cd ~/Mcp-servers
uv sync --frozen --no-dev
```

### 3. Secrets (no `.env` file in prod)

Create `/etc/mcp-starter/env` (root-only, `chmod 600`):

```bash
OAUTH_CLIENT_ID=...
OAUTH_CLIENT_SECRET=...
MCP_BASE_URL=https://memory-mcp.example.com
# Optional for multi-worker / multi-instance (Part 2):
# JWT_SIGNING_KEY=...
# REDIS_URL=redis://...
```

Wire `GoogleProvider` to `JWT_SIGNING_KEY` + Redis storage before running **multiple workers or instances** (see Part 2).

### 4. systemd + Uvicorn

Copy `systemd/memory-mcp.service` to `/etc/systemd/system/`, adjust paths, then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable memory-mcp
sudo systemctl start memory-mcp
sudo systemctl status memory-mcp
```

Single instance can use **one worker** (default). For practice with workers on one box:

```ini
# In service file ExecStart — only after OAuth prod keys + Redis if needed:
# ... uvicorn memory_mcp.server:app --host 127.0.0.1 --port 8007 --workers 2
```

`stateless_http=True` is already set on `app` in code.

### 5. nginx + TLS

Copy `nginx/memory-mcp.conf` to `/etc/nginx/sites-available/`, enable, obtain cert:

```bash
sudo ln -s /etc/nginx/sites-available/memory-mcp /etc/nginx/sites-enabled/
sudo certbot --nginx -d memory-mcp.example.com
sudo nginx -t && sudo systemctl reload nginx
```

Critical for MCP streaming (from FastMCP docs): `proxy_buffering off`, long `proxy_read_timeout`.

### 6. Google OAuth

In Google Cloud Console, add redirect URIs for **`MCP_BASE_URL`** (HTTPS), e.g. paths under your FastMCP OAuth proxy (`/auth/callback`, etc.).

### 7. Verify

```bash
curl -s https://memory-mcp.example.com/health
```

Connect with `uv run memory-client` (update client URL) or Claude **custom connector** → remote MCP URL + OAuth.

---

## Part 2 — Multi-instance (ALB + 2+ EC2)

Goal: Application Load Balancer → N identical EC2 targets; **no sticky sessions** (MCP clients often ignore cookies).

### 1. Code / config requirements

Already done in repo:

- `app = mcp.http_app(stateless_http=True)` in `memory_mcp/server.py`.

Still required for **OAuth across instances** ([FastMCP OAuth production](https://gofastmcp.com/deployment/http#oauth-token-security)):

1. **`jwt_signing_key`** — same on all instances (env `JWT_SIGNING_KEY`).
2. **`client_storage`** — shared Redis with encryption (e.g. ElastiCache), not in-memory.

Until those are configured, practice multi-instance with **auth disabled** or a single instance only.

### 2. AWS layout

1. **Target group** — HTTP, port **80** (nginx on each instance) or **8007** if no nginx on targets (prefer nginx on each node).
2. **Health check** — `GET /health`, expect `200`.
3. **ALB listener** — HTTPS 443, ACM certificate, forward to target group.
4. **Launch template / ASG** — same AMI/user-data as Part 1; min 2 instances across AZs for practice.
5. **Security groups** — ALB → instances on 443/80; instances outbound for Google OAuth + Redis.

### 3. Shared state (practice)

- **ElastiCache Redis** in same VPC; security group allows EC2 SG on 6379.
- Set `REDIS_URL` on all instances; extend `GoogleProvider` with `jwt_signing_key` and `client_storage` (see FastMCP docs).

### 4. Deploy flow

1. Bake AMI or use user-data: `uv sync`, systemd, nginx.
2. Rolling refresh: new instance registers healthy → drain old.
3. Confirm: two targets healthy; run OAuth login twice; hit different instances (check logs) — both should work with shared Redis + JWT key.

### 5. Long-running tools

If tools exceed ALB/nginx idle timeout, increase timeouts or use FastMCP **EventStore** + SSE polling ([doc](https://gofastmcp.com/deployment/http#sse-polling-for-long-running-operations)).

---

## Docker on EC2 (optional)

Build and run on the VM (or push to ECR):

```bash
docker build -t memory-mcp .
docker run -d --name memory-mcp \
  -p 127.0.0.1:8007:8007 \
  --env-file /etc/mcp-starter/env \
  -v /var/lib/memory-mcp/memories:/app/src/memory_mcp/memories \
  memory-mcp
```

Override image CMD to ASGI:

```bash
docker run ... memory-mcp \
  uvicorn memory_mcp.server:app --host 0.0.0.0 --port 8007
```

Point nginx at `127.0.0.1:8007` as in Part 1.

---

## Checklist

| Step | Single EC2 | Multi-instance |
|------|------------|----------------|
| ASGI `memory_mcp.server:app` | ✓ | ✓ |
| `stateless_http=True` | ✓ (in code) | ✓ |
| `MCP_BASE_URL` HTTPS | ✓ | ✓ |
| nginx SSE settings | ✓ | ✓ |
| `/health` for LB | optional | ✓ |
| `JWT_SIGNING_KEY` + Redis | optional | **required** for OAuth |
| Google redirect URIs | ✓ | ✓ |
