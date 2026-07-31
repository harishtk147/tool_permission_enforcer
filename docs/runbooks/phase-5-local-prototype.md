# Phase 5 Local Prototype Runbook

This runbook verifies the complete local prototype: trusted sessions, default-deny policy,
protected CRM execution, idempotency, sanitized audit events, and hash-chain integrity.

Before starting, stop any Phase 2 Uvicorn processes still using ports 8000 or 8001. They
must be restarted to load the Phase 5 routes.

## Option A: Docker Compose

Use this option when Docker Desktop is installed.

### 1. Start the services

From the repository root:

```powershell
docker compose up --build -d
docker compose ps
```

Wait until `postgres`, `redis`, `sample-crm`, and `permission-proxy` are healthy and
`database-migrate` has exited successfully.

Check the APIs:

```powershell
Invoke-RestMethod http://localhost:8000/health/ready
Invoke-RestMethod http://localhost:8001/health/ready
```

### 2. Run the acceptance demonstration

```powershell
uv sync --frozen
uv run python -m scripts.run_local_demo
```

The expected matrix is:

| Scenario | HTTP | Decision/reason |
|---|---:|---|
| Read `customer_1001` in its trusted session | 200 | `allow` / `ALLOWED` |
| Write `customer_1001` | 403 | `block` / `OPERATION_NOT_ALLOWED` |
| Read `customer_1002` in a `customer_1001` session | 403 | `block` / `DATA_SCOPE_VIOLATION` |
| Delete `customer_1001` | 403 | `block` / `OPERATION_NOT_ALLOWED` |
| Repeat the first idempotency key | 409 | `block` / `DUPLICATE_REQUEST` |
| Verify audit integrity | 200 | `valid: true` |

The audit response for the write attempt must contain only the changed field names and
`"changes": "[REDACTED]"`; it must not contain the attempted address.

### 3. Confirm the CRM cannot be called anonymously

```powershell
try {
    Invoke-WebRequest http://localhost:8001/customers/customer_1001 -ErrorAction Stop
} catch {
    $_.Exception.Response.StatusCode.value__
}
```

The expected status is `401`.

### 4. Stop the services

```powershell
docker compose down
```

Add `-v` only when you intentionally want to delete the local database and Redis volumes.

## Option B: Windows without Docker

This option uses a shared SQLite database and two local Uvicorn processes. Use three
PowerShell terminals, all opened in the repository root.

### 1. Prepare the database in terminal 1

```powershell
uv sync --frozen
$env:PROXY_DATABASE_URL = "sqlite+pysqlite:///./local-prototype.db"
uv run alembic upgrade head
uv run python -m scripts.seed_phase_1
```

### 2. Start the CRM in terminal 1

```powershell
$env:CRM_DATABASE_URL = "sqlite+pysqlite:///./local-prototype.db"
$env:CRM_INTERNAL_API_KEY = "local-development-only-change-me"
uv run uvicorn services.sample_crm.main:app --host 127.0.0.1 --port 8001
```

Leave it running.

### 3. Start the proxy in terminal 2

```powershell
$env:PROXY_DATABASE_URL = "sqlite+pysqlite:///./local-prototype.db"
$env:PROXY_CRM_BASE_URL = "http://127.0.0.1:8001"
$env:PROXY_CRM_INTERNAL_API_KEY = "local-development-only-change-me"
$env:PROXY_DEV_AUTH_ENABLED = "true"
uv run uvicorn services.permission_proxy.main:app --host 127.0.0.1 --port 8000
```

Leave it running.

### 4. Run the demonstration in terminal 3

```powershell
$env:PROXY_DATABASE_URL = "sqlite+pysqlite:///./local-prototype.db"
$env:PROXY_CRM_BASE_URL = "http://127.0.0.1:8001"
$env:PROXY_CRM_INTERNAL_API_KEY = "local-development-only-change-me"
uv run python -m scripts.run_local_demo
```

Compare the results with the acceptance matrix above. Interactive OpenAPI pages are
available at:

- Proxy: `http://localhost:8000/docs`
- CRM: `http://localhost:8001/docs`

Press `Ctrl+C` in terminals 1 and 2 to stop both services.

## Automated verification

The full Phase 0-5 gate is:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify_phase_5.ps1
```

This uses isolated temporary databases and does not alter `local-prototype.db`.

## Start clean

Stop both local processes first. If you intentionally want to discard local prototype data,
delete only the repository-local `local-prototype.db` file, then repeat the database
preparation step.
