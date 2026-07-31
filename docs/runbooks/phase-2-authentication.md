# Phase 2 Authentication and Session Runbook

## Automated gate

```powershell
cd "C:\Users\arua\OneDrive - Cisco\Documents\Harish\tool-permission-enforcer"
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify_phase_2.ps1
```

This runs all Phase 0 and Phase 1 checks, then proves:

- Registered agent identity resolution.
- Trusted session creation with a scoped host token.
- Matching-agent session validation.
- Preservation of trusted customer context.
- Immediate rejection following revocation.

## Start a local manual environment

```powershell
$env:PROXY_DATABASE_URL="sqlite+pysqlite:///./phase2-manual.db"
$env:PROXY_DEV_AUTH_ENABLED="true"
$env:PROXY_DEV_JWT_SECRET="local-development-access-token-secret-change-me"
$env:PROXY_SESSION_SIGNING_SECRET="local-development-session-secret-change-me"

uv run alembic upgrade head
uv run python -m scripts.seed_phase_1
uv run uvicorn services.permission_proxy.main:app --port 8000
```

In a second PowerShell terminal from the project directory:

```powershell
$hostToken = uv run python -m scripts.mint_dev_token --type host
$agentToken = uv run python -m scripts.mint_dev_token --type agent

$hostHeaders = @{ Authorization = "Bearer $hostToken" }
$agentHeaders = @{ Authorization = "Bearer $agentToken" }
```

Verify the registered agent:

```powershell
Invoke-RestMethod `
  -Uri http://localhost:8000/v1/identity/me `
  -Headers $agentHeaders
```

Create a trusted session:

```powershell
$createBody = @{
  agent_id = "agent_support_001"
  user_id = "manual_user"
  customer_id = "customer_1001"
  ttl_seconds = 300
} | ConvertTo-Json

$created = Invoke-RestMethod `
  -Method Post `
  -Uri http://localhost:8000/v1/sessions `
  -Headers $hostHeaders `
  -ContentType "application/json" `
  -Body $createBody

$created
```

Validate the session as the agent:

```powershell
$validateBody = @{
  session_token = $created.session_token
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri http://localhost:8000/v1/sessions/validate `
  -Headers $agentHeaders `
  -ContentType "application/json" `
  -Body $validateBody
```

The response must show `customer_1001`.

Revoke and confirm rejection:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "http://localhost:8000/v1/sessions/$($created.session_id)/revoke" `
  -Headers $hostHeaders

try {
  Invoke-RestMethod `
    -Method Post `
    -Uri http://localhost:8000/v1/sessions/validate `
    -Headers $agentHeaders `
    -ContentType "application/json" `
    -Body $validateBody
}
catch {
  $_.ErrorDetails.Message
}
```

The final request must return HTTP 401 with `SESSION_NOT_ACTIVE`.

## Negative checks

- Remove `session:create` from a host token: session creation returns HTTP 403.
- Use a token signed with a different secret: authentication returns HTTP 401.
- Use another registered agent to validate the token: validation returns HTTP 403 with
  `SESSION_AGENT_MISMATCH`.
- Suspend the agent in the database: identity resolution and session validation return HTTP
  403 with `AGENT_NOT_ACTIVE`.
- Alter any session-token character: validation returns HTTP 401.

