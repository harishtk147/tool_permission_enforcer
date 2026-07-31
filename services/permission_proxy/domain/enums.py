from enum import StrEnum


class AgentStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DECOMMISSIONED = "decommissioned"


class ToolStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class ManifestStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    REVOKED = "revoked"


class SessionStatus(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"


class AuditDecision(StrEnum):
    ALLOW = "allow"
    BLOCK = "block"
    ERROR = "error"


class AuditExecutionStatus(StrEnum):
    NOT_FORWARDED = "not_forwarded"
    AUTHORIZED = "authorized"
    EXECUTED = "executed"
    TOOL_FAILED = "tool_failed"
    TIMED_OUT = "timed_out"
