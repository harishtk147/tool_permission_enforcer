import logging
from .api import router as ai_router
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from services.common.logging import configure_logging
from services.common.models import HealthResponse, ServiceInfo
from services.common.settings import ReferenceAgentSettings, get_agent_settings

logger = logging.getLogger(__name__)


def create_app(settings: ReferenceAgentSettings | None = None) -> FastAPI:
    config = settings or get_agent_settings()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        configure_logging(config.log_level)
        logger.info(
            "service_started",
            extra={
                "service": config.service_name,
                "version": config.service_version,
                "environment": config.app_env,
                "llm_provider": config.llm_provider,
            },
        )
        yield
        logger.info("service_stopped", extra={"service": config.service_name})

    application = FastAPI(
        title="Reference Agent API",
        summary="Reference LLM agent for end-to-end policy demonstrations",
        version=config.service_version,
        lifespan=lifespan,
    )
    application.state.settings = config
    application.include_router(ai_router)

    @application.get("/", response_model=ServiceInfo, tags=["service"])
    async def service_info() -> ServiceInfo:
        return ServiceInfo(
            name=config.service_name,
            version=config.service_version,
            environment=config.app_env,
            docs_url="/docs",
        )

    @application.get("/health/live", response_model=HealthResponse, tags=["health"])
    async def liveness() -> HealthResponse:
        return HealthResponse(
            service=config.service_name,
            status="alive",
            version=config.service_version,
            environment=config.app_env,
        )

    @application.get("/health/ready", response_model=HealthResponse, tags=["health"])
    async def readiness() -> HealthResponse:
        provider_status = "disabled" if config.llm_provider == "disabled" else "configured"
        return HealthResponse(
            service=config.service_name,
            status="ready",
            version=config.service_version,
            environment=config.app_env,
            checks={"configuration": "ok", "llm_provider": provider_status},
        )

    return application


app = create_app()
