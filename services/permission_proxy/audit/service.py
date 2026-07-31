import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from services.common.database import Database
from services.permission_proxy.domain.enums import AuditDecision, AuditExecutionStatus
from services.permission_proxy.domain.models import ToolCallAuditEvent
from services.permission_proxy.persistence.repositories import AuditEventRepository


@dataclass(frozen=True)
class AuditEventInput:
    request_id: str
    idempotency_key: str
    sequence: int
    agent_id: str
    session_id: str | None
    user_id: str | None
    tool: str
    operation: str
    parameters: dict[str, Any]
    decision: AuditDecision
    reason_code: str
    execution_status: AuditExecutionStatus
    manifest_id: str | None = None
    policy_checksum: str | None = None
    upstream_status_code: int | None = None
    decision_latency_ms: int | None = None
    total_latency_ms: int | None = None
    trace_id: str | None = None


@dataclass(frozen=True)
class IntegrityResult:
    valid: bool
    events_checked: int
    first_invalid_event_id: str | None = None


def sanitize_parameters(parameters: dict[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    if isinstance(parameters.get("customer_id"), str):
        sanitized["customer_id"] = parameters["customer_id"]
    if "changes" in parameters:
        changes = parameters["changes"]
        sanitized["change_fields"] = (
            sorted(str(key) for key in changes) if isinstance(changes, dict) else "[INVALID]"
        )
        sanitized["changes"] = "[REDACTED]"
    unknown = sorted(set(parameters) - {"customer_id", "changes"})
    if unknown:
        sanitized["ignored_parameter_names"] = unknown
    return sanitized


def event_hash(event: ToolCallAuditEvent) -> str:
    timestamp = event.timestamp
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    payload = {
        "event_id": event.event_id,
        "request_id": event.request_id,
        "idempotency_key": event.idempotency_key,
        "sequence": event.sequence,
        "timestamp": timestamp.astimezone(UTC).isoformat(),
        "agent_id": event.agent_id,
        "session_id": event.session_id,
        "user_id": event.user_id,
        "tool": event.tool,
        "operation": event.operation,
        "sanitized_parameters": event.sanitized_parameters,
        "decision": event.decision.value,
        "reason_code": event.reason_code,
        "matched_manifest_id": event.matched_manifest_id,
        "policy_checksum": event.policy_checksum,
        "execution_status": event.execution_status.value,
        "upstream_status_code": event.upstream_status_code,
        "decision_latency_ms": event.decision_latency_ms,
        "total_latency_ms": event.total_latency_ms,
        "trace_id": event.trace_id,
        "previous_record_hash": event.previous_record_hash,
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


class AuditService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def has_idempotency_key(self, agent_id: str, idempotency_key: str) -> bool:
        with self.database.session() as session:
            return (
                AuditEventRepository(session).find_by_idempotency_key(
                    agent_id,
                    idempotency_key,
                )
                is not None
            )

    def record(self, data: AuditEventInput) -> ToolCallAuditEvent:
        with self.database.session() as session:
            repository = AuditEventRepository(session)
            previous = repository.last_chain_event()
            event = ToolCallAuditEvent(
                event_id=f"evt_{uuid4().hex}",
                request_id=data.request_id,
                idempotency_key=data.idempotency_key,
                sequence=data.sequence,
                timestamp=datetime.now(UTC),
                agent_id=data.agent_id,
                session_id=data.session_id,
                user_id=data.user_id,
                tool=data.tool,
                operation=data.operation,
                sanitized_parameters=sanitize_parameters(data.parameters),
                decision=data.decision,
                reason_code=data.reason_code,
                matched_manifest_id=data.manifest_id,
                policy_checksum=data.policy_checksum,
                execution_status=data.execution_status,
                upstream_status_code=data.upstream_status_code,
                decision_latency_ms=data.decision_latency_ms,
                total_latency_ms=data.total_latency_ms,
                trace_id=data.trace_id,
                previous_record_hash=previous.record_hash if previous is not None else None,
                record_hash="pending",
            )
            event.record_hash = event_hash(event)
            return repository.add(event)

    def verify_integrity(self) -> IntegrityResult:
        with self.database.session() as session:
            events = AuditEventRepository(session).all_chain_events()
            previous_hash: str | None = None
            for event in events:
                if event.previous_record_hash != previous_hash or event.record_hash != event_hash(
                    event
                ):
                    return IntegrityResult(
                        valid=False,
                        events_checked=len(events),
                        first_invalid_event_id=event.event_id,
                    )
                previous_hash = event.record_hash
            return IntegrityResult(valid=True, events_checked=len(events))
