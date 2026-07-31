# Phase 2 Authentication and Trusted Sessions

## Access-token modes

### Production OIDC mode

Set:

- `PROXY_DEV_AUTH_ENABLED=false`
- `PROXY_OIDC_ISSUER=https://...`
- `PROXY_OIDC_AUDIENCE=tool-permission-enforcer`
- `PROXY_OIDC_JWKS_URL=https://...`
- `PROXY_OIDC_ALGORITHM=RS256`

The proxy obtains the signing key from the configured JWKS provider and validates signature,
algorithm, issuer, audience, expiry, issued-at time, subject, and token use. Production startup
fails when development authentication is enabled, the issuer is not HTTPS, or no JWKS URL is
configured.

### Local development mode

Development access tokens use HS256 and `PROXY_DEV_JWT_SECRET`. They are available only
when `PROXY_DEV_AUTH_ENABLED=true`. The token utility can create short-lived agent, host,
administrator, and auditor credentials for local verification.

Development credentials and secrets must never be used in staging or production.

## Token uses and scopes

| Token use | Purpose | Current scopes |
|---|---|---|
| `agent` | Authenticates a deployed agent | `tool:invoke` |
| `host` | Trusted application that creates customer sessions | `session:create`, `session:revoke` |
| `admin` | Administrative control plane | Session scopes now; policy scopes in later phases |
| `auditor` | Read-only audit consumer | `audit:read` in Phase 5 |

An agent token subject must exactly match an active registered agent's `oidc_subject`.
Suspended and decommissioned agents are rejected even when their JWT is otherwise valid.

## Trusted session creation

1. A trusted host authenticates with a host or administrator access token.
2. `POST /v1/sessions` requires `session:create`.
3. The service confirms that the target agent exists and is active.
4. The session is persisted with agent, user, customer, creator, JWT ID, status, and expiry.
5. The proxy signs a short-lived agent-session token.

The session token contains:

- Session ID and unique JWT ID.
- Agent ID.
- User ID.
- Trusted customer ID.
- Issuer and audience.
- Issued-at, not-before, and expiry timestamps.
- `token_use=agent_session`.

## Trusted session validation

`POST /v1/sessions/validate` requires:

- A valid agent access token.
- `tool:invoke`.
- A registered active agent matching the access-token subject.
- A valid session token bound to the same agent.
- Matching server-side JWT ID, agent, user, customer, status, and expiry.

The customer ID in the session token is signed and checked against server-side state. The
agent cannot replace it with request metadata. Phase 3 will use this trusted value when
evaluating dynamic data scope.

## Revocation

`POST /v1/sessions/{session_id}/revoke` requires a host or administrator access token with
`session:revoke`. Revocation is idempotent and stored immediately. A revoked token is rejected
even if its cryptographic expiry time has not passed.

## Signing-secret handling

The session-token signing secret is separate from the development access-token secret. Both
must contain at least 32 characters. Production rejects the repository's local session secret.
The production value belongs in AWS Secrets Manager and is injected into the proxy task at
runtime.

