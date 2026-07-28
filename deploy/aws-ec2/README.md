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

Health: `http://127.0.0.1:8007/health`  
MCP: `http://127.0.0.1:8007/mcp`

Required env: see `env.example` (`OAUTH_*`, `JWT_SIGNING_KEY`, `STORAGE_ENCRYPTION_KEY`, `REDIS_URL`, `BASE_URL`).

---

## Part 1A — Single EC2 (no nginx)

### 1. AWS setup

**Option A — Lab / SSM only (simplest)**  
- Uvicorn on port **8007**, security group: **8007** from your IP (or none public; test via SSM `curl localhost:8007/health`).  
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

Allow the service user to read the app:

```bash
sudo chown -R www-data:www-data /opt/mcp-servers
# or: sudo chown -R nginx:nginx ... on AL2023 if www-data missing — create www-data or run as ec2-user in unit
```

On Amazon Linux, `www-data` may not exist — use `ec2-user` or `ssm-user` in the unit file instead.

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

Default unit binds **`0.0.0.0:8007`** (no nginx). Lock down **security groups** so only the ALB (or your IP) can reach 8007.

### 5. Google OAuth

Redirect URIs must match **`BASE_URL`** (scheme + host + port if non-default).

### 6. Verify

```bash
curl -s http://127.0.0.1:8007/health
# From outside (if SG allows):
curl -s http://<public-ip>:8007/health
# Via ALB:
curl -s https://your-domain.com/health
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

```bash
sudo cp deploy/aws-ec2/nginx/memory-mcp.conf /etc/nginx/conf.d/memory-mcp.conf
# Edit server_name to your domain
sudo nginx -t && sudo systemctl enable --now nginx
sudo certbot --nginx -d memory-mcp.example.com   # Ubuntu-style; adjust on AL2023
sudo systemctl reload nginx
```

Important (from [FastMCP HTTP deployment](https://gofastmcp.com/deployment/http#reverse-proxy-nginx)):

- `proxy_buffering off` — already in the sample config  
- Long `proxy_read_timeout` — already set to 300s  
- `proxy_set_header X-Forwarded-Proto $scheme` — so OAuth sees HTTPS  

### 6. Verify

```bash
curl -s http://127.0.0.1:8007/health          # on instance only
curl -s https://memory-mcp.example.com/health   # public
curl -s https://memory-mcp.example.com/mcp     # MCP endpoint (may require auth)
```

### 7. Multi-instance + nginx

Each EC2 runs the same stack (nginx + Uvicorn). Put an **ALB in front of :443** on each instance, or use one instance for practice. Shared **`JWT_SIGNING_KEY`**, **`STORAGE_ENCRYPTION_KEY`**, **`REDIS_URL`**, and **`BASE_URL`** on all nodes.

---

## Part 2 — Multi-instance (ALB, no nginx on EC2)

1. Same AMI/user-data: `uv sync`, `/etc/mcp-servers/env`, systemd on **8007**.
2. **Target group**: protocol HTTP, port **8007**, health check `GET /health`.
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
