# Phase 1 Persistence Runbook

## Automated gate

```powershell
cd "C:\Users\arua\OneDrive - Cisco\Documents\Harish\tool-permission-enforcer"
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify_phase_1.ps1
```

This runs the complete Phase 0 gate followed by:

- Upgrade of a fresh database to the latest Alembic revision.
- Two seed executions to prove idempotency.
- Disposal and recreation of the database engine.
- Verification that records survive the restart.
- Verification of all expected table and record counts.

## Manual verification with SQLite

SQLite is supported only for local verification and automated tests. Production uses
PostgreSQL.

```powershell
$env:PROXY_DATABASE_URL="sqlite+pysqlite:///./phase1-manual.db"
$env:CRM_DATABASE_URL=$env:PROXY_DATABASE_URL

uv run alembic upgrade head
uv run python -m scripts.seed_phase_1
uv run python -m scripts.inspect_phase_1
uv run alembic current
```

Expected inspection result:

```json
{
  "active_manifest_id": "support-agent-readonly-v1",
  "agents": 1,
  "audit_events": 0,
  "customers": 3,
  "database_ready": true,
  "manifests": 1,
  "sessions": 0,
  "tools": 1
}
```

Run the seed and inspection commands again. Counts must remain unchanged.

To verify readiness against the migrated database:

```powershell
uv run uvicorn services.permission_proxy.main:app --port 8000
```

In another terminal with the same `PROXY_DATABASE_URL`:

```powershell
Invoke-RestMethod http://localhost:8000/health/ready
```

The response must contain `status: ready` and `database: ok`. Stop and restart the service,
then inspect the database again to demonstrate persistence across process restarts.

## Manual verification with Docker

Prerequisite: Docker Desktop with Docker Compose.

```powershell
Copy-Item .env.example .env -ErrorAction SilentlyContinue
docker compose up --build -d
docker compose ps -a
docker compose logs database-migrate
Invoke-RestMethod http://localhost:8000/health/ready
Invoke-RestMethod http://localhost:8001/health/ready
```

Expected results:

- `database-migrate` exits with code 0 after applying the migration and seed.
- PostgreSQL, Redis, the sample CRM, and permission proxy report healthy.
- Proxy and CRM readiness responses contain `database: ok`.

Inspect persisted seed data inside the proxy image:

```powershell
docker compose run --rm permission-proxy python -m scripts.inspect_phase_1
```

Restart the application services and inspect again:

```powershell
docker compose restart permission-proxy sample-crm
docker compose run --rm permission-proxy python -m scripts.inspect_phase_1
```

Record counts and the active manifest must remain unchanged.
