from dataclasses import dataclass
from time import perf_counter
from typing import Any, Literal
from uuid import uuid4

from services.permission_proxy.audit.service import AuditEventInput, AuditService
from services.permission_proxy.domain.enums import AuditDecision, AuditExecutionStatus
from services.permission_proxy.policy.evaluator import PolicyEvaluator
from services.permission_proxy.security.sessions import TrustedSessionClaims
from services.permission_proxy.tools.crm import ToolAdapter, ToolExecutionError


@dataclass(frozen=True)
class ToolCallOutcome:
    request_id: str
    decision: Literal["allow", "block", "error"]
    reason_code: str
    message: str
    result: dict[str, Any] | None = None
    upstream_status_code: int | None = None


class ToolCallService:
    def __init__(
        self,
        *,
        evaluator: PolicyEvaluator,
        audit: AuditService,
        adapter: ToolAdapter,
    ) -> None:
        self.evaluator = evaluator
        self.audit = audit
        self.adapter = adapter

    async def execute(
        self,
        *,
        agent_id: str,
        trusted_session: TrustedSessionClaims,
        idempotency_key: str,
        tool: str,
        operation: str,
        parameters: dict[str, Any],
        trace_id: str | None,
    ) -> ToolCallOutcome:
        request_id = f"req_{uuid4().hex}"
        started = perf_counter()

        if self.audit.has_idempotency_key(agent_id, idempotency_key):
            outcome = ToolCallOutcome(
                request_id=request_id,
                decision="block",
                reason_code="DUPLICATE_REQUEST",
                message="This idempotency key has already been used",
            )
            self._record(
                outcome=outcome,
                idempotency_key=idempotency_key,
                sequence=0,
                agent_id=agent_id,
                trusted_session=trusted_session,
                tool=tool,
                operation=operation,
                parameters=parameters,
                execution_status=AuditExecutionStatus.NOT_FORWARDED,
                trace_id=trace_id,
                total_latency_ms=self._elapsed_ms(started),
            )
            return outcome

        policy_started = perf_counter()
        policy = self.evaluator.evaluate(
            agent_id=agent_id,
            session=trusted_session,
            tool_name=tool,
            operation=operation,
            parameters=parameters,
        )
        decision_latency_ms = self._elapsed_ms(policy_started)
        if not policy.allowed:
            outcome = ToolCallOutcome(
                request_id=request_id,
                decision="block",
                reason_code=policy.reason_code,
                message=policy.message,
            )
            self._record(
                outcome=outcome,
                idempotency_key=idempotency_key,
                sequence=0,
                agent_id=agent_id,
                trusted_session=trusted_session,
                tool=tool,
                operation=operation,
                parameters=parameters,
                execution_status=AuditExecutionStatus.NOT_FORWARDED,
                manifest_id=policy.manifest_id,
                policy_checksum=policy.policy_checksum,
                decision_latency_ms=decision_latency_ms,
                total_latency_ms=self._elapsed_ms(started),
                trace_id=trace_id,
            )
            return outcome

        authorized = ToolCallOutcome(
            request_id=request_id,
            decision="allow",
            reason_code="ALLOWED",
            message="Tool call is permitted",
        )
        self._record(
            outcome=authorized,
            idempotency_key=idempotency_key,
            sequence=0,
            agent_id=agent_id,
            trusted_session=trusted_session,
            tool=tool,
            operation=operation,
            parameters=parameters,
            execution_status=AuditExecutionStatus.AUTHORIZED,
            manifest_id=policy.manifest_id,
            policy_checksum=policy.policy_checksum,
            decision_latency_ms=decision_latency_ms,
            total_latency_ms=self._elapsed_ms(started),
            trace_id=trace_id,
        )

        try:
            execution = await self.adapter.execute(
                tool=tool,
                operation=operation,
                parameters=parameters,
            )
        except ToolExecutionError as error:
            outcome = ToolCallOutcome(
                request_id=request_id,
                decision="error",
                reason_code=error.code,
                message=error.message,
                upstream_status_code=error.upstream_status_code,
            )
            execution_status = (
                AuditExecutionStatus.TIMED_OUT
                if error.code == "UPSTREAM_TOOL_TIMEOUT"
                else AuditExecutionStatus.TOOL_FAILED
            )
            self._record(
                outcome=outcome,
                idempotency_key=idempotency_key,
                sequence=1,
                agent_id=agent_id,
                trusted_session=trusted_session,
                tool=tool,
                operation=operation,
                parameters=parameters,
                execution_status=execution_status,
                manifest_id=policy.manifest_id,
                policy_checksum=policy.policy_checksum,
                upstream_status_code=error.upstream_status_code,
                decision_latency_ms=decision_latency_ms,
                total_latency_ms=self._elapsed_ms(started),
                trace_id=trace_id,
            )
            return outcome

        outcome = ToolCallOutcome(
            request_id=request_id,
            decision="allow",
            reason_code="ALLOWED",
            message="Tool call executed",
            result=execution.result,
            upstream_status_code=execution.upstream_status_code,
        )
        self._record(
            outcome=outcome,
            idempotency_key=idempotency_key,
            sequence=1,
            agent_id=agent_id,
            trusted_session=trusted_session,
            tool=tool,
            operation=operation,
            parameters=parameters,
            execution_status=AuditExecutionStatus.EXECUTED,
            manifest_id=policy.manifest_id,
            policy_checksum=policy.policy_checksum,
            upstream_status_code=execution.upstream_status_code,
            decision_latency_ms=decision_latency_ms,
            total_latency_ms=self._elapsed_ms(started),
            trace_id=trace_id,
        )
        return outcome

    def _record(
        self,
        *,
        outcome: ToolCallOutcome,
        idempotency_key: str,
        sequence: int,
        agent_id: str,
        trusted_session: TrustedSessionClaims,
        tool: str,
        operation: str,
        parameters: dict[str, Any],
        execution_status: AuditExecutionStatus,
        trace_id: str | None,
        manifest_id: str | None = None,
        policy_checksum: str | None = None,
        upstream_status_code: int | None = None,
        decision_latency_ms: int | None = None,
        total_latency_ms: int | None = None,
    ) -> None:
        decision = {
            "allow": AuditDecision.ALLOW,
            "block": AuditDecision.BLOCK,
            "error": AuditDecision.ERROR,
        }[outcome.decision]
        self.audit.record(
            AuditEventInput(
                request_id=outcome.request_id,
                idempotency_key=idempotency_key,
                sequence=sequence,
                agent_id=agent_id,
                session_id=trusted_session.session_id,
                user_id=trusted_session.user_id,
                tool=tool,
                operation=operation,
                parameters=parameters,
                decision=decision,
                reason_code=outcome.reason_code,
                execution_status=execution_status,
                manifest_id=manifest_id,
                policy_checksum=policy_checksum,
                upstream_status_code=upstream_status_code,
                decision_latency_ms=decision_latency_ms,
                total_latency_ms=total_latency_ms,
                trace_id=trace_id,
            )
        )

    @staticmethod
    def _elapsed_ms(started: float) -> int:
        return max(0, round((perf_counter() - started) * 1000))
