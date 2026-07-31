from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from services.common.settings import PermissionProxySettings


class ToolExecutionError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        upstream_status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.upstream_status_code = upstream_status_code


@dataclass(frozen=True)
class ToolExecutionResult:
    result: dict[str, Any] | None
    upstream_status_code: int


class ToolAdapter(Protocol):
    async def execute(
        self,
        *,
        tool: str,
        operation: str,
        parameters: dict[str, Any],
    ) -> ToolExecutionResult: ...


class HTTPCRMAdapter:
    def __init__(
        self,
        settings: PermissionProxySettings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = str(settings.crm_base_url).rstrip("/")
        self.internal_key = settings.crm_internal_api_key.get_secret_value()
        self.timeout = settings.upstream_timeout_seconds
        self.transport = transport

    async def execute(
        self,
        *,
        tool: str,
        operation: str,
        parameters: dict[str, Any],
    ) -> ToolExecutionResult:
        if tool != "crm":
            raise ToolExecutionError("TOOL_NOT_REGISTERED", "No adapter exists for the tool")

        customer_id = parameters["customer_id"]
        path = f"/customers/{customer_id}"
        method: str
        body: dict[str, Any] | None
        if operation == "read_customer":
            method, body = "GET", None
        elif operation == "write_customer":
            changes = parameters.get("changes")
            if not isinstance(changes, dict):
                raise ToolExecutionError(
                    "INVALID_PARAMETERS",
                    "write_customer requires a changes object",
                )
            method, body = "PATCH", changes
        elif operation == "delete_customer":
            method, body = "DELETE", None
        else:
            raise ToolExecutionError(
                "OPERATION_NOT_SUPPORTED",
                "The registered adapter does not support this operation",
            )

        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                transport=self.transport,
            ) as client:
                response = await client.request(
                    method,
                    path,
                    headers={"X-Internal-API-Key": self.internal_key},
                    json=body,
                )
        except httpx.TimeoutException as error:
            raise ToolExecutionError(
                "UPSTREAM_TOOL_TIMEOUT",
                "The protected tool timed out",
            ) from error
        except httpx.HTTPError as error:
            raise ToolExecutionError(
                "UPSTREAM_TOOL_ERROR",
                "The protected tool could not be reached",
            ) from error

        if response.status_code >= 400:
            raise ToolExecutionError(
                "UPSTREAM_TOOL_ERROR",
                "The protected tool rejected the request",
                upstream_status_code=response.status_code,
            )
        result = None if response.status_code == 204 else response.json()
        return ToolExecutionResult(
            result=result,
            upstream_status_code=response.status_code,
        )
