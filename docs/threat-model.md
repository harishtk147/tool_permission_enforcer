# Initial Threat Model

## Protected assets

- Customer records exposed by registered tools.
- Agent and session credentials.
- Permission manifests.
- Audit records.
- Internal service credentials and LLM provider credentials.

## Trust boundaries

1. User to trusted host application.
2. Host application to session issuer.
3. LLM agent to permission proxy.
4. Permission proxy to registered tool.
5. Services to PostgreSQL and Redis.
6. Administrators and auditors to control-plane APIs.

## Initial threats and planned controls

| Threat | Planned control |
|---|---|
| Agent changes a customer ID to expand its scope | Server-validated signed session context and equality policy rule. |
| Agent calls the CRM directly | Private networking and a CRM credential available only to the proxy. |
| Agent supplies an arbitrary destination | Server-side allowlisted tool registry; requests contain no URL. |
| Forged agent or session token | OIDC/JWT signature, issuer, audience, expiry, status, and binding validation. |
| Missing or unavailable policy | Default deny and fail-closed request handling. |
| Duplicate mutation after timeout | Mandatory idempotency key; reuse is rejected before forwarding. |
| Sensitive data leaked through logs | Structured allowlisted fields and parameter sanitization. |
| Policy changed without traceability | Immutable versioning, activation transaction, checksum, and audit event. |
| Audit record modified | Append-oriented permissions and hash-linked records. |
| Development authentication enabled in production | Startup configuration validation. |
| Agent forges trusted customer context | Customer context comes from a signed token and matching server-side session row. |
| Session token is stolen and later revoked | Every validation checks current server-side status and JWT ID. |
| Access token is signed by an unexpected key or algorithm | Production uses an allowlisted algorithm and configured OIDC JWKS provider. |
| Suspended agent continues using an unexpired token | Every identity and session validation checks the current agent status. |
| Manifest contains executable or unknown rule content | Strict typed schemas reject unknown fields and rule types; no dynamic evaluation is used. |
| Blocked call still reaches a tool | Authorization audit commits before forwarding, and blocked paths never invoke an adapter. |
| Audit parameters expose attempted customer changes | Only allowlisted identifiers and change-field names are stored; change values are redacted. |

This document is updated at each phase as new interfaces and data flows are introduced.
