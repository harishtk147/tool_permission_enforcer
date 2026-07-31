# Data Model Through Phase 5

Phase 1 introduces six application tables plus Alembic's revision table.

## Control-plane tables

### `agents`

Stores stable machine identities independently of short-lived credentials.

Key invariants:

- `agent_id` is the stable application identifier.
- `oidc_subject` is unique.
- Status is constrained to `active`, `suspended`, or `decommissioned`.

### `tool_definitions`

Stores allowlisted tool destinations and schemas.

Key invariants:

- Tool name is unique.
- The destination URL is server-side configuration and cannot be supplied by an agent call.
- Status is constrained to `active` or `disabled`.

### `permission_manifests`

Stores immutable policy versions for an agent.

Key invariants:

- `(agent_id, version)` is unique.
- Only one row with `status = active` may exist for an agent.
- Expiry, when present, must be later than the effective timestamp.
- The JSON document has a canonical SHA-256 checksum.
- Activation locks the owning agent, supersedes the existing active version, and activates the
  target in one transaction.

### `agent_sessions`

Reserves the persistent session model used by Phase 2.

Key invariants:

- JWT ID is unique.
- A session belongs to one agent, user, and customer.
- `created_by_subject` records the trusted host or administrator that created it.
- Expiry must be later than creation.
- Status is constrained to `active`, `expired`, or `revoked`.

### `tool_call_audit_events`

Stores the append-oriented audit model completed in Phase 5.

Key invariants:

- `(request_id, sequence)` is unique.
- Every event records the caller-supplied idempotency key.
- Decision and execution status use constrained values.
- Events can reference an agent, session, and matched manifest.
- Parameters are sanitized before persistence.
- Each record hashes its canonical fields and the previous record hash for tamper detection.

## Synthetic CRM table

### `crm_customers`

Contains only synthetic customer records. Three deterministic records are seeded for
`customer_1001`, `customer_1002`, and `customer_1003`.

## Seeded control data

- Agent: `agent_support_001`.
- Tool: `crm`.
- Active manifest: `support-agent-readonly-v1`.
- Allowed operation: `read_customer`.
- Dynamic scope: session customer ID must equal the tool parameter customer ID.

The seed operation is idempotent. Existing seed identifiers with conflicting immutable data
cause an error instead of being silently overwritten.
