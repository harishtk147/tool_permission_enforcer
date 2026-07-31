# ADR 0002: Trusted Signed Session Context

Status: accepted

## Decision

Customer scope will come from a short-lived session token issued by a trusted host
application and backed by server-side session state. Agent-provided session metadata will
not be authoritative.

## Rationale

If the agent can choose both the tool parameter and the comparison value, a compromised
agent can grant itself access to any customer. Binding the session to an agent and customer
outside the LLM trust boundary makes dynamic scope enforceable.

## Consequences

- A session API and token validation are required in Phase 2.
- Session tokens require signature, issuer, audience, expiry, status, and agent-binding checks.
- Revoked sessions fail closed even when the token has not expired.

