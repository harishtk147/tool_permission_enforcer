# Phase 0 Local Startup Runbook

## Python-only verification

Prerequisites:

- Python 3.12.
- `uv`.

Run:

```powershell
cd "C:\Users\arua\OneDrive - Cisco\Documents\Harish\tool-permission-enforcer"
uv sync --frozen --python 3.12
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify_phase_0.ps1
```

## Container verification

Prerequisite: Docker Desktop with Docker Compose.

```powershell
Copy-Item .env.example .env
docker compose up --build -d
docker compose ps
Invoke-RestMethod http://localhost:8000/health/ready
Invoke-RestMethod http://localhost:8001/health/ready
docker compose --profile agent up --build -d
Invoke-RestMethod http://localhost:8002/health/ready
```

Expected results:

- `permission-proxy`, `sample-crm`, `postgres`, and `redis` report healthy.
- The optional `reference-agent` reports healthy after its profile is enabled.
- Each readiness response contains `status: ready` and `configuration: ok`.
- Interactive API pages open at ports 8000, 8001, and 8002 under `/docs`.

Stop the stack without deleting data:

```powershell
docker compose --profile agent down
```

To remove only this project's local Docker volumes after explicit confirmation:

```powershell
docker compose --profile agent down --volumes
```

## Common failures

- Port already in use: stop the conflicting process or change the host-side port in
  `docker-compose.yml`.
- Container remains unhealthy: run `docker compose logs <service-name>`.
- Configuration validation error: compare `.env` with `.env.example`.
- Production-mode startup rejection: development authentication and insecure issuer URLs are
  intentionally prohibited in production.
