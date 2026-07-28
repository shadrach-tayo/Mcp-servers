# Memory MCP — ASGI on AWS EC2 (practice)

Two deployment shapes:

| Mode | Public entry | Uvicorn bind | systemd unit |
|------|----------------|--------------|----------------|
| **Direct / ALB** | `:8007` or ALB→8007 | `0.0.0.0:8007` | `systemd/memory-mcp.service` |
| **nginx on instance** | `:443` (TLS) | `127.0.0.1:8007` | `systemd/memory-mcp-nginx.service` |

ASGI entrypoint: `memory_mcp.server:app` (`stateless_http=True`).

## Local ASGI

```bash
uv run --env-file .env uvicorn memory_mcp.server:app --host 0.0.0.0 --port 8007
```

Health: `http://127.0.0.1:8007/api/health`
MCP: `http://127.0.0.1:8007/api/mcp`

Required env: see `env.example` (`OAUTH_*`, `JWT_SIGNING_KEY`, `STORAGE_ENCRYPTION_KEY`, `REDIS_URL`, `BASE_URL`).

---

## Part 1A — Single EC2 (no nginx)

### 1. AWS setup

**Option A — Lab / SSM only (simplest)**  
- Uvicorn on port **8007**, security group: **8007** from your IP (or none public; test via SSM `curl localhost:8007/api/health`).  
- `BASE_URL=http://<public-ip>:8007` — Google OAuth may require HTTPS for real clients.

**Option B — Production-shaped without nginx on the box (recommended)**  
- **ALB** listener **HTTPS 443** (ACM cert) → target group → instance **HTTP:8007**.  
- Instance security group: allow **8007 only from the ALB security group**, not from `0.0.0.0/0`.  
- `BASE_URL=https://your-domain.com` (ALB hostname or Route53 name).

Also: **22** or SSM (no SSH required), outbound for Google OAuth + Upstash Redis.

### 2. Install on the VM

**SSM:** always `cd` to the repo with an absolute path (not `/usr/bin`).

#### Amazon Linux 2023

```bash
sudo dnf install -y git python3-devel gcc gcc-c++ make
```

#### Ubuntu (if you use it)

```bash
sudo apt-get update && sudo apt-get install -y git python3-venv
```

(`psycopg2-binary` in the repo avoids Postgres dev packages for `uv sync`.)

#### App install

```bash
sudo mkdir -p /opt && sudo chown "$USER:$USER" /opt
git clone <your-repo> /opt/mcp-servers
cd /opt/mcp-servers
export PATH="$HOME/.local/bin:$PATH"
curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync --frozen --no-dev
```

Allow the **same user as the systemd unit** to read the app:

```bash
sudo chown -R ec2-user:ec2-user /opt/mcp-servers   # Amazon Linux (default in deploy units)
# Ubuntu: sudo chown -R www-data:www-data /opt/mcp-servers and set User=www-data in the unit
```

If `journalctl` shows **`status=217/USER`**, the `User=` in the unit does not exist on the OS — fix the unit and `daemon-reload` (units in this repo default to `ec2-user` for AL2023).

### 3. Environment (`/etc/mcp-servers/env`)

```bash
sudo mkdir -p /etc/mcp-servers
sudo cp deploy/aws-ec2/env.example /etc/mcp-servers/env
sudo nano /etc/mcp-servers/env
sudo chmod 600 /etc/mcp-servers/env
```

systemd loads this via `EnvironmentFile=/etc/mcp-servers/env` (see below). **Do not** rely on `.env` in the repo on EC2.

Generate keys once:

```bash
openssl rand -hex 32   # JWT_SIGNING_KEY
/opt/mcp-servers/.venv/bin/python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Set **`BASE_URL`** to the URL clients use to reach MCP (HTTPS via ALB, or `http://ip:8007` for lab).

### 4. systemd + Uvicorn (direct)

```bash
sudo cp deploy/aws-ec2/systemd/memory-mcp.service /etc/systemd/system/
# Edit User/Group/paths if needed (Amazon Linux: User=ec2-user)
sudo systemctl daemon-reload
sudo systemctl enable --now memory-mcp
sudo systemctl status memory-mcp
journalctl -u memory-mcp -f
```

**`status=203/EXEC`** — systemd could not run `ExecStart` (missing venv, wrong path, or bad `uvicorn` shebang). On the instance:

```bash
sudo systemctl stop memory-mcp
ls -la /opt/mcp-servers/.venv/bin/python
sudo -u ec2-user /opt/mcp-servers/.venv/bin/python -m uvicorn --version
```

If `.venv` is missing, run `cd /opt/mcp-servers && uv sync --frozen --no-dev` as `ec2-user`, then set `ExecStart` to  
`/opt/mcp-servers/.venv/bin/python -m uvicorn memory_mcp.server:app ...` (see deploy units), `daemon-reload`, and start again.

**`Permission denied` on `/opt/mcp-servers/.venv/bin/uvicorn`** — the installed unit still calls the `uvicorn` script; use **`python -m uvicorn`** instead (deploy units already do). On the instance:

```bash
sudo systemctl stop memory-mcp
sudo sed -i 's|ExecStart=.*|ExecStart=/opt/mcp-servers/.venv/bin/python -m uvicorn memory_mcp.server:app --host 127.0.0.1 --port 8007|' /etc/systemd/system/memory-mcp.service
grep -E '^(ExecStart|Environment=PYTHONPATH)' /etc/systemd/system/memory-mcp.service
# Add PYTHONPATH line if missing (see deploy/aws-ec2/systemd/*.service)
sudo systemctl daemon-reload && sudo systemctl start memory-mcp
```

Build the venv as the same user as `User=` in the unit (`uv sync` as `ec2-user`, not `ssm-user`). If it still fails with permission errors on AL2023, check SELinux: `getenforce` and `sudo ausearch -m avc -ts recent`.

Default unit binds **`0.0.0.0:8007`** (no nginx). Lock down **security groups** so only the ALB (or your IP) can reach 8007.

### 5. Google OAuth

Redirect URIs must match **`BASE_URL`** (scheme + host + port if non-default).

### 6. Verify

```bash
curl -s http://127.0.0.1:8007/api/health
# From outside (if SG allows):
curl -s http://<public-ip>:8007/api/health
# Via ALB:
curl -s https://your-domain.com/api/health
```

---

## Part 1B — Single EC2 **with nginx** (TLS on the instance)

Traffic flow:

```text
Internet :443 → nginx (TLS) → http://127.0.0.1:8007 → Uvicorn → FastMCP
```

### 1. AWS setup

- Security group: **443** from clients (and **80** for Let’s Encrypt HTTP-01), **not** 8007 from the internet.
- DNS `memory-mcp.example.com` → instance public IP (or Elastic IP).

### 2. Install nginx + certbot

**Ubuntu:**

```bash
sudo apt-get install -y nginx certbot python3-certbot-nginx
```

**Amazon Linux 2023:**

```bash
sudo dnf install -y nginx
# certbot: use snap, pip, or ACM instead — AL2023 varies; many teams use ALB+ACM and skip certbot on AL
```

### 3. App + env (same as Part 1A)

`uv sync`, `/etc/mcp-servers/env`, with:

```bash
BASE_URL=https://memory-mcp.example.com
```

(no port in URL when using 443)

### 4. systemd — bind Uvicorn to localhost only

```bash
sudo cp deploy/aws-ec2/systemd/memory-mcp-nginx.service /etc/systemd/system/memory-mcp.service
sudo systemctl daemon-reload
sudo systemctl enable --now memory-mcp
```

Uses **`127.0.0.1:8007`** so MCP is not exposed except through nginx.

### 5. nginx config

Sample config proxies **`/` → Uvicorn** so OAuth **`/.well-known/*`** (app root) and **`/api/*`** (MCP mount) both work. Default hostname in the file is **`mcp.livemigrate.ai`** — change `server_name` and cert paths if needed.

**Cloudflare:** DNS **A** record `mcp` → EC2; SSL/TLS **Full (strict)** once origin has a valid cert (Let’s Encrypt recommended below).

Always run **`sudo nginx -t`** (not as `ssm-user` — otherwise permission errors on logs).

**Recommended — Let’s Encrypt (HTTP-01 via webroot)**

Security group: allow **80** and **443**. `memory-mcp.conf` points at `/etc/letsencrypt/live/mcp.livemigrate.ai/` — **`nginx -t` fails until certbot creates those files.**

```bash
sudo mkdir -p /var/www/certbot
sudo cp deploy/aws-ec2/nginx/memory-mcp.bootstrap.conf /etc/nginx/conf.d/memory-mcp.conf
sudo nginx -t && sudo systemctl enable --now nginx && sudo systemctl reload nginx

# Install certbot (Amazon Linux 2023 example: snap — see certbot docs for Ubuntu/dnf)
sudo dnf install -y snapd && sudo systemctl enable --now snapd
sudo ln -sf /var/lib/snapd/snap /snap && sudo snap install --classic certbot
sudo ln -sf /snap/bin/certbot /usr/bin/certbot

sudo certbot certonly --webroot -w /var/www/certbot -d mcp.livemigrate.ai

sudo cp deploy/aws-ec2/nginx/memory-mcp.conf /etc/nginx/conf.d/memory-mcp.conf
sudo nginx -t && sudo systemctl reload nginx
sudo certbot renew --dry-run
```

Cloudflare → SSL/TLS → **Full (strict)**.

**Alternative — Cloudflare Origin cert:** paste PEMs under `/etc/nginx/ssl/`, swap `ssl_certificate*` in `memory-mcp.conf` (see comments in file), then reload nginx.

Set env to match the public URL (no `/api` in `BASE_URL`; use `MCP_MOUNT_PREFIX=/api`):

```bash
BASE_URL=https://mcp.livemigrate.ai
```

Important (from [FastMCP HTTP deployment](https://gofastmcp.com/deployment/http#reverse-proxy-nginx)):

- `proxy_buffering off` — already in the sample config  
- Long `proxy_read_timeout` — already set to 300s  
- `proxy_set_header X-Forwarded-Proto $scheme` — so OAuth sees HTTPS  

### 6. Verify

```bash
curl -s http://127.0.0.1:8007/api/health
curl -s https://mcp.livemigrate.ai/api/health
curl -sI https://mcp.livemigrate.ai/.well-known/oauth-authorization-server
# MCP URL for clients (with default MCP_PATH=/mcp):
# https://mcp.livemigrate.ai/api/mcp
```

### 7. Multi-instance + nginx

Each EC2 runs the same stack (nginx + Uvicorn). Put an **ALB in front of :443** on each instance, or use one instance for practice. Shared **`JWT_SIGNING_KEY`**, **`STORAGE_ENCRYPTION_KEY`**, **`REDIS_URL`**, and **`BASE_URL`** on all nodes.

---

## Part 2 — Multi-instance (ALB, no nginx on EC2)

1. Same AMI/user-data: `uv sync`, `/etc/mcp-servers/env`, systemd on **8007**.
2. **Target group**: protocol HTTP, port **8007**, health check `GET /api/health`.
3. **ALB**: HTTPS 443 → target group (ACM on ALB).
4. **Identical env** on every instance: `JWT_SIGNING_KEY`, `STORAGE_ENCRYPTION_KEY`, `REDIS_URL`, `BASE_URL`.
5. `stateless_http=True` is already set in code — no sticky sessions.

Increase ALB idle timeout if tools run long (or use FastMCP EventStore / SSE polling).

You can also terminate TLS at **nginx on each instance** (Part 1B) and use an ALB with **HTTPS → HTTPS** to instances, or TCP pass-through — pick one TLS layer, not both with conflicting certs unless you know the setup.

---

## Docker on EC2 (optional)

```bash
docker run -d --name memory-mcp \
  -p 8007:8007 \
  --env-file /etc/mcp-servers/env \
  memory-mcp
```

No nginx container; same security group rules as above.

---

## Checklist (no nginx)

| Item | Single EC2 | Multi-instance |
|------|------------|----------------|
| Uvicorn `0.0.0.0:8007` | ✓ | ✓ |
| `/etc/mcp-servers/env` + systemd | ✓ | ✓ |
| TLS at ALB (or HTTP lab only) | ✓ | ✓ |
| SG: 8007 from ALB only | optional | ✓ |
| Shared Redis + JWT keys | ✓ | ✓ |
| `BASE_URL` matches public URL | ✓ | ✓ |
