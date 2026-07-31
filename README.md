# Tool Permission Enforcer

Production-oriented implementation of PS-2.2: a policy enforcement proxy between an AI
agent and its tools.

The project uses ten verification-gated phases. The local prototype is complete through
Phase 5; production-focused Phases 6-9 are intentionally deferred.
See [docs/implementation-phases.md](docs/implementation-phases.md) for the complete
sequence.

## Implemented through Phase 5

- Three independently runnable FastAPI services.
- Validated environment-based configuration.
- Production safety checks for development authentication, OIDC HTTPS, and CRM credentials.
- Structured JSON container logging.
- Liveness, readiness, service metadata, and OpenAPI endpoints.
- Local PostgreSQL, Redis, CRM, proxy, and optional agent Docker Compose topology.
- Non-root container images with locked Python dependencies.
- Formatting, linting, strict type checking, unit tests, and coverage enforcement.
- Pull-request CI for Python quality and container builds.
- Architecture, threat model, API, ADR, and local-startup documentation.
- Alembic-managed PostgreSQL schema with six application tables.
- SQLAlchemy database and repository layer.
- Transactional, one-active-version-only manifest activation.
- Idempotent synthetic seed data for an agent, CRM tool, read-only manifest, and three
  customers.
- Database-aware readiness checks that return HTTP 503 when persistence is unavailable.
- Migration upgrade/downgrade, restart persistence, rollback, repository, and seed tests.
- Production OIDC/JWKS access-token validation with an allowlisted signing algorithm.
- Isolated local-development token mode and token-minting utility.
- Scope enforcement and registered active-agent identity binding.
- Trusted session creation with signed customer context and server-side state.
- Matching-agent validation, expiry enforcement, and immediate revocation.
- Stable authentication and authorization error codes.
- Strict, typed permission-manifest parsing with checksum verification.
- Deterministic first-failure, default-deny policy evaluation.
- Read-only operation and trusted customer-scope enforcement.
- A functional protected CRM with read, write, and delete operations.
- An allowlisted proxy adapter with internal authentication and upstream timeouts.
- Mandatory idempotency keys and duplicate-request rejection.
- Durable authorization-before-forwarding audit records.
- Sanitized audit parameters, immutable execution events, filtering, and pagination.
- SHA-256 hash-linked audit integrity verification and tamper-detection tests.

## Quick verification

### Complete Phase 0-5 gate

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify_phase_5.ps1
```

The [Phase 5 local prototype runbook](docs/runbooks/phase-5-local-prototype.md) contains
complete Docker and no-Docker startup instructions plus the acceptance matrix.

### Docker Compose

```powershell
Copy-Item .env.example .env
docker compose up --build -d
docker compose ps
docker compose --profile agent up --build -d
```

The core stack starts the proxy, CRM, PostgreSQL, and Redis. The second command enables the
optional reference-agent profile.

After the stack is running, execute:

```powershell
uv run python -m scripts.run_local_demo
```

The demonstration proves an allowed current-customer read and blocked write, delete,
cross-customer, and duplicate requests, then queries and verifies the audit chain.

## Configuration

Copy `.env.example` to `.env` for Docker-based development. Local defaults are deliberately
usable without a file, but production-mode validation rejects:

- Development authentication.
- Non-HTTPS OIDC issuers.
- Default proxy-to-CRM credentials.
- The sample CRM's default internal API key.
- An enabled LLM provider without a configured API key.

Do not commit `.env` or real credentials.

## Current API surface

Every service exposes:

- `GET /`
- `GET /health/live`
- `GET /health/ready`
- `GET /docs`
- `GET /openapi.json`

The proxy exposes trusted-session, tool-call, and audit APIs. The CRM exposes protected
customer read, patch, and delete APIs. See [docs/api.md](docs/api.md) for the current surface.

## Personal AWS interview deployment

The repository includes a minimal Terraform deployment for a personal AWS account. It
provisions ECR, ECS Fargate, a load balancer, private RDS PostgreSQL, Secrets Manager, and
CloudWatch logs. No Cisco credentials or CI/CD system are required.

After installing AWS CLI, Docker Desktop, and Terraform, follow the
[AWS deployment runbook](docs/runbooks/aws-ecs-demo-deployment.md). The helper deploys,
waits for health, and runs the remote acceptance demo:

```powershell
.\scripts\deploy_aws_demo.ps1 -Region "ap-south-1" `
    -AllowedIngressCidr "YOUR.PUBLIC.IP.ADDRESS/32"
```

This is an IP-restricted interview deployment. Real production identity and HTTPS remain
explicit items in the [production readiness checklist](docs/production-readiness-checklist.md).
