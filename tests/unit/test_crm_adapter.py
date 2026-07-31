import httpx
import pytest

from services.common.settings import PermissionProxySettings
from services.permission_proxy.tools.crm import HTTPCRMAdapter, ToolExecutionError


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def settings() -> PermissionProxySettings:
    return PermissionProxySettings(
        _env_file=None,
        app_env="test",
        crm_base_url="http://crm.test",
        crm_internal_api_key="test-proxy-to-crm-key-that-is-long-enough",
    )


@pytest.mark.anyio
async def test_crm_adapter_maps_timeout_to_fail_closed_error() -> None:
    async def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("simulated timeout", request=request)

    adapter = HTTPCRMAdapter(settings(), transport=httpx.MockTransport(timeout))
    with pytest.raises(ToolExecutionError) as captured:
        await adapter.execute(
            tool="crm",
            operation="read_customer",
            parameters={"customer_id": "customer_1001"},
        )

    assert captured.value.code == "UPSTREAM_TOOL_TIMEOUT"


@pytest.mark.anyio
async def test_crm_adapter_maps_upstream_failure_without_leaking_response() -> None:
    async def failure(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"internal": "do not expose"})

    adapter = HTTPCRMAdapter(settings(), transport=httpx.MockTransport(failure))
    with pytest.raises(ToolExecutionError) as captured:
        await adapter.execute(
            tool="crm",
            operation="read_customer",
            parameters={"customer_id": "customer_1001"},
        )

    assert captured.value.code == "UPSTREAM_TOOL_ERROR"
    assert captured.value.upstream_status_code == 503
    assert "do not expose" not in captured.value.message
