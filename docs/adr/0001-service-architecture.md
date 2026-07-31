# ADR 0001: Small Independently Deployable Services

Status: accepted

## Decision

Use a Python monorepo with separate permission-proxy, sample-CRM, and reference-agent
processes. Share only configuration, logging, and API model utilities.

## Rationale

The proxy and protected tool must have a real network boundary so tests can prove that
blocked calls never reach the CRM. A monorepo reduces interview-project overhead while
separate processes retain realistic deployment and security boundaries.

## Consequences

- Each service receives its own container image and health endpoint.
- The CRM can be placed on a private network independently of the agent.
- Shared domain logic must not create a backdoor around the proxy.

