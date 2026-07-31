import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response, status

from services.common.database import Database
from services.common.logging import configure_logging
from services.common.models import HealthResponse, ServiceInfo
from services.common.settings import SampleCRMSettings, get_crm_settings
from services.sample_crm.api import build_customer_router

logger = logging.getLogger(__name__)


def create_app(
    settings: SampleCRMSettings | None = None,
    database: Database | None = None,
) -> FastAPI:
    config = settings or get_crm_settings()
    database_instance = database or Database(config.database_url)
    owns_database = database is None

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        configure_logging(config.log_level)
        logger.info(
            "service_started",
            extra={
                "service": config.service_name,
                "version": config.service_version,
                "environment": config.app_env,
            },
        )
        yield
        logger.info("service_stopped", extra={"service": config.service_name})
        if owns_database:
            database_instance.dispose()

    application = FastAPI(
        title="Private Sample CRM API",
        summary="Synthetic protected tool used by the permission enforcer",
        version=config.service_version,
        lifespan=lifespan,
    )
    application.state.settings = config
    application.state.database = database_instance
    application.include_router(build_customer_router(database=database_instance, settings=config))

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

    @application.get(
        "/health/ready",
        response_model=HealthResponse,
        tags=["health"],
        responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": HealthResponse}},
    )
    def readiness(response: Response) -> HealthResponse:
        database_ready = database_instance.ping()
        if not database_ready:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(
            service=config.service_name,
            status="ready" if database_ready else "not_ready",
            version=config.service_version,
            environment=config.app_env,
            checks={
                "configuration": "ok",
                "database": "ok" if database_ready else "unavailable",
            },
        )

    return application


app = create_app()
