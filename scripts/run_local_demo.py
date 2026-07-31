import json
import os
from typing import Any
from uuid import uuid4

import httpx

from services.common.settings import PermissionProxySettings
from services.permission_proxy.persistence.seed import SEED_AGENT_ID
from services.permission_proxy.security.auth import AccessTokenService


def show(label: str, response: httpx.Response) -> dict[str, Any]:
    try:
        body: dict[str, Any] = response.json()
    except json.JSONDecodeError:
        body = {"body": response.text}
    print(f"\n{label}: HTTP {response.status_code}")
    print(json.dumps(body, indent=2, sort_keys=True))
    return body


def main() -> None:
    settings = PermissionProxySettings()
    base_url = os.getenv("PROXY_DEMO_BASE_URL", "http://localhost:8000")
    tokens = AccessTokenService(settings)
    run_id = uuid4().hex[:12]
    host_token = tokens.issue_development_token(
        subject="dev:trusted-host",
        token_use="host",
        scopes={"session:create"},
    )
    agent_token = tokens.issue_development_token(
        subject="dev:agent_support_001",
        token_use="agent",
        scopes={"tool:invoke"},
    )
    auditor_token = tokens.issue_development_token(
        subject="dev:auditor",
        token_use="auditor",
        scopes={"audit:read"},
    )

    with httpx.Client(base_url=base_url, timeout=10) as client:
        session_response = client.post(
            "/v1/sessions",
            headers={"Authorization": f"Bearer {host_token}"},
            json={
                "agent_id": SEED_AGENT_ID,
                "user_id": "user_local_demo",
                "customer_id": "customer_1001",
                "ttl_seconds": 600,
            },
        )
        session = show("Create trusted customer_1001 session", session_response)
        session_response.raise_for_status()
        call_headers = {
            "Authorization": f"Bearer {agent_token}",
            "X-Session-Token": session["session_token"],
        }

        scenarios = (
            (
                "Allowed read for session customer",
                "read",
                200,
                "ALLOWED",
                {
                    "tool": "crm",
                    "operation": "read_customer",
                    "parameters": {"customer_id": "customer_1001"},
                },
            ),
            (
                "Blocked write",
                "write",
                403,
                "OPERATION_NOT_ALLOWED",
                {
                    "tool": "crm",
                    "operation": "write_customer",
                    "parameters": {
                        "customer_id": "customer_1001",
                        "changes": {"address": "This must never reach CRM"},
                    },
                },
            ),
            (
                "Blocked cross-customer read",
                "cross",
                403,
                "DATA_SCOPE_VIOLATION",
                {
                    "tool": "crm",
                    "operation": "read_customer",
                    "parameters": {"customer_id": "customer_1002"},
                },
            ),
            (
                "Blocked delete",
                "delete",
                403,
                "OPERATION_NOT_ALLOWED",
                {
                    "tool": "crm",
                    "operation": "delete_customer",
                    "parameters": {"customer_id": "customer_1001"},
                },
            ),
        )
        first_read_headers: dict[str, str] | None = None
        first_read_body: dict[str, Any] | None = None
        for label, key_suffix, expected_status, expected_reason, body in scenarios:
            headers = {
                **call_headers,
                "Idempotency-Key": f"{run_id}-{key_suffix}",
            }
            result = client.post("/v1/tool-calls", headers=headers, json=body)
            result_body = show(label, result)
            if (
                result.status_code != expected_status
                or result_body.get("reason_code") != expected_reason
            ):
                raise RuntimeError(f"Acceptance scenario failed: {label}")
            if key_suffix == "read":
                first_read_headers = headers
                first_read_body = body

        if first_read_headers is None or first_read_body is None:
            raise RuntimeError("Read scenario was not configured")
        duplicate = client.post(
            "/v1/tool-calls",
            headers=first_read_headers,
            json=first_read_body,
        )
        duplicate_body = show("Blocked duplicate idempotency key", duplicate)
        if duplicate.status_code != 409 or duplicate_body.get("reason_code") != "DUPLICATE_REQUEST":
            raise RuntimeError("Duplicate-request acceptance scenario failed")

        audit_headers = {"Authorization": f"Bearer {auditor_token}"}
        events = client.get(
            "/v1/audit/events",
            headers=audit_headers,
            params={"session_id": session["session_id"], "limit": 20},
        )
        show("Audit events for this session", events)
        integrity = client.get("/v1/audit/integrity", headers=audit_headers)
        integrity_body = show("Audit-chain integrity", integrity)
        if integrity.status_code != 200 or integrity_body.get("valid") is not True:
            raise RuntimeError("Audit-chain integrity verification failed")

    print("\nLocal Phase 5 demonstration completed.")


if __name__ == "__main__":
    main()
