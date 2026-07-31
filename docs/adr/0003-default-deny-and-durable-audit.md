# ADR 0003: Default Deny and Audit Before Forwarding

Status: accepted

## Decision

Policy evaluation is deterministic and default deny. An allowed authorization decision must
be durably audited before the proxy forwards a request to a tool.

## Rationale

An unavailable policy or audit store must not silently bypass enforcement. Writing the
authorization record first also prevents successful side effects that have no governance
record.

## Consequences

- Missing, invalid, expired, or unavailable policy state blocks the call.
- Database unavailability blocks tool forwarding unless a specifically approved durable
  design is introduced later.
- Tool execution completion is recorded as a separate append-only event.

