# Verification-Gated Implementation Phases

There are ten phases, numbered 0 through 9. The locally testable prototype is complete
through Phase 5. Phases 6-9 are deferred until production work resumes.

| Phase | Outcome | Manual gate |
|---:|---|---|
| 0 | Repository, validated configuration, services, containers, checks, CI, and architecture decisions | Services start and health checks, formatting, typing, and tests pass. |
| 1 | PostgreSQL domain model, migrations, repositories, and seed data | Data survives restart and manifest activation is transactional. |
| 2 | Real authentication and trusted session context | Forged, expired, revoked, and cross-agent credentials are rejected. |
| 3 | Versioned manifests and deterministic default-deny policy engine | Read-only and dynamic customer-scope decision matrix passes. |
| 4 | Tool-call proxy, separate functional CRM, adapters, timeouts, and idempotency | Allowed calls reach CRM; blocked calls never do. |
| 5 | Durable sanitized and tamper-evident audit trail with query APIs | Every decision is queryable and deliberate modification is detected. |
| 6 | Real LLM reference agent and automated PS-2.2 scenarios | Real tool calling proves allowed read and blocked write/cross-customer access. |
| 7 | Metrics, logs, traces, dashboards, alerts, resilience, and bonus probing alert | Failure simulations are observable and fail closed. |
| 8 | Terraform AWS deployment and CI/CD for staging and production | Multi-instance HTTPS staging deployment passes acceptance tests. |
| 9 | Threat review, security/load tests, backup restore, runbooks, and final handoff | Complete production definition of done and interview demo pass. |
