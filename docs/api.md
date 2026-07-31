# Service API

Each of the three services exposes:

- `GET /`: service name, version, environment, and documentation path.
- `GET /health/live`: process liveness.
- `GET /health/ready`: phase-specific readiness checks. Proxy and CRM readiness now include
  a live database connectivity check and return HTTP 503 when it fails.
- `GET /docs`: interactive OpenAPI documentation.
- `GET /openapi.json`: machine-readable OpenAPI schema.

Default local ports:

| Service | Port |
|---|---:|
| Permission proxy | 8000 |
| Sample CRM | 8001 |
| Reference agent | 8002 |

## Permission-proxy APIs

| Method | Path | Credential requirement |
|---|---|---|
| GET | `/v1/identity/me` | Any valid access token; agent tokens are checked against the registry |
| POST | `/v1/sessions` | Host/admin token with `session:create` |
| POST | `/v1/sessions/validate` | Active registered agent token with `tool:invoke` |
| POST | `/v1/sessions/{session_id}/revoke` | Host/admin token with `session:revoke` |
| POST | `/v1/tool-calls` | Active agent token, trusted session token, `tool:invoke`, and idempotency key |
| GET | `/v1/audit/events` | Auditor/admin token with `audit:read` |
| GET | `/v1/audit/events/{request_id}` | Auditor/admin token with `audit:read` |
| GET | `/v1/audit/integrity` | Auditor/admin token with `audit:read` |

Authentication failures return HTTP 401, authorization failures return HTTP 403, unknown
agents or sessions return HTTP 404, and malformed request bodies return HTTP 422. Security
errors contain stable `detail.code` and `detail.message` fields.

Tool calls require `Authorization`, `X-Session-Token`, and `Idempotency-Key` headers.
Policy blocks return HTTP 403, duplicate idempotency keys return HTTP 409, and upstream
failures return HTTP 502 or 504. Requests never contain a destination URL.

## Protected sample-CRM APIs

| Method | Path | Proxy operation |
|---|---|---|
| GET | `/customers/{customer_id}` | `read_customer` |
| PATCH | `/customers/{customer_id}` | `write_customer` |
| DELETE | `/customers/{customer_id}` | `delete_customer` |

Every CRM operation requires `X-Internal-API-Key`. The read-only seeded agent can reach only
`read_customer` through the proxy.
