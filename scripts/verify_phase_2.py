import asyncio
import tempfile
from pathlib import Path

import httpx

from scripts.verify_phase_1 import upgrade
from services.common.database import Database
from services.common.settings import PermissionProxySettings
from services.permission_proxy.main import create_app
from services.permission_proxy.persistence.seed import SEED_AGENT_ID, seed_phase_1
from services.permission_proxy.security.auth import AccessTokenService


async def verify_api_flow(settings: PermissionProxySettings, database: Database) -> None:
    token_service = AccessTokenService(settings)
    host_token = token_service.issue_development_token(
        subject="dev:trusted-host",
        token_use="host",
        scopes={"session:create", "session:revoke"},
    )
    agent_token = token_service.issue_development_token(
        subject="dev:agent_support_001",
        token_use="agent",
        scopes={"tool:invoke"},
    )
    app = create_app(settings=settings, database=database)
    transport = httpx.ASGITransport(app=app)
    host_headers = {"Authorization": f"Bearer {host_token}"}
    agent_headers = {"Authorization": f"Bearer {agent_token}"}

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://phase-2") as client,
    ):
        identity = await client.get("/v1/identity/me", headers=agent_headers)
        if identity.status_code != 200 or identity.json().get("agent_id") != SEED_AGENT_ID:
            raise RuntimeError(f"Agent identity verification failed: {identity.text}")

        created_response = await client.post(
            "/v1/sessions",
            headers=host_headers,
            json={
                "agent_id": SEED_AGENT_ID,
                "user_id": "verification_user",
                "customer_id": "customer_1001",
                "ttl_seconds": 300,
            },
        )
        if created_response.status_code != 201:
            raise RuntimeError(f"Session creation failed: {created_response.text}")
        created = created_response.json()

        validated = await client.post(
            "/v1/sessions/validate",
            headers=agent_headers,
            json={"session_token": created["session_token"]},
        )
        if validated.status_code != 200:
            raise RuntimeError(f"Session validation failed: {validated.text}")
        if validated.json().get("customer_id") != "customer_1001":
            raise RuntimeError("Trusted customer context was not preserved")

        revoked = await client.post(
            f"/v1/sessions/{created['session_id']}/revoke",
            headers=host_headers,
        )
        if revoked.status_code != 200 or revoked.json().get("status") != "revoked":
            raise RuntimeError(f"Session revocation failed: {revoked.text}")

        rejected = await client.post(
            "/v1/sessions/validate",
            headers=agent_headers,
            json={"session_token": created["session_token"]},
        )
        if rejected.status_code != 401:
            raise RuntimeError("Revoked session token was accepted")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="permission-phase-2-") as temp_directory:
        database_path = Path(temp_directory) / "phase-2-verification.db"
        database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
        upgrade(database_url)
        database = Database(database_url)
        try:
            seed_phase_1(database)
            settings = PermissionProxySettings(
                _env_file=None,
                app_env="test",
                database_url=database_url,
                dev_auth_enabled=True,
            )
            asyncio.run(verify_api_flow(settings, database))
        finally:
            database.dispose()

    print("Phase 2 identity, trusted session, validation, and revocation checks passed.")


if __name__ == "__main__":
    main()
