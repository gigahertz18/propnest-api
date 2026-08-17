import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from redis.exceptions import RedisError

from app.core.config import settings
from app.core.logging import setup_logging
from app.core.redis_client import RedisClientManager
from app.db.session import engine
from app.api.v1.routes import (
    properties,
    auth,
    users,
    contracts,
    tenants,
    documents,
    payments,
    collections,
    audit_logs,
    activity_feed,
    leases,
    billing_records,
    receipts,
    receipt_templates,
)
from app.services.exceptions import (
    RelatedResourceNotFoundError,
    ResourceForbiddenError,
    UserForbiddenError,
    ServiceException,
)

# ─── Logging must be configured before any module-level logger is used ────────
setup_logging(env=settings.ENV)

logger = logging.getLogger(__name__)


# ─── Lifespan ─────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.validate()  # fail fast if config is unsafe for the current environment
    await _wait_for_db(
        max_retries=settings.DB_MAX_RETRIES,
        retry_interval=settings.DB_RETRY_INTERVAL,
    )
    app.state.redis = RedisClientManager(
        url=settings.REDIS_URL,
        max_connections=settings.REDIS_MAX_CONNECTIONS,
        socket_timeout=settings.REDIS_SOCKET_TIMEOUT,
        socket_connect_timeout=settings.REDIS_SOCKET_CONNECT_TIMEOUT,
        health_check_interval=settings.REDIS_HEALTH_CHECK_INTERVAL,
    )
    logger.info("%s started in [%s] mode", settings.APP_NAME, settings.ENV)
    yield
    await engine.dispose()
    await app.state.redis.close()
    logger.info("Database connections closed")


async def _wait_for_db(max_retries: int, retry_interval: int) -> None:
    """
    Retries the DB connection until PostgreSQL is ready or max retries exceeded.
    Values come from the active config class — tunable per environment.
    """
    for attempt in range(1, max_retries + 1):
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            logger.info("Database is ready")
            return
        except Exception as e:
            if attempt == max_retries:
                logger.error(
                    "Database not available after %d attempts. Last error: %s",
                    max_retries,
                    e,
                )
                raise RuntimeError(f"Could not connect to the database after {max_retries} attempts.") from e

            logger.warning(
                "Database not ready (attempt %d/%d) — retrying in %ds...",
                attempt,
                max_retries,
                retry_interval,
            )
            await asyncio.sleep(retry_interval)


# ─── App ──────────────────────────────────────────────────────────────────────
app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.is_dev else None,
    redoc_url="/redoc" if settings.is_dev else None,
)

# ─── CORS ─────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Exception Handlers ───────────────────────────────────
@app.exception_handler(RelatedResourceNotFoundError)
async def related_resource_not_found_handler(request: Request, exc: RelatedResourceNotFoundError) -> JSONResponse:
    """
    Default 404 mapping for a missing/failed property/contract/tenant
    lookup. Routes only need their own except block when a different
    status code or detail message is actually required (e.g.
    UserNotFoundError, a separate class with its own route-supplied text).
    """
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(exc)})


@app.exception_handler(ResourceForbiddenError)
@app.exception_handler(UserForbiddenError)
async def resource_forbidden_handler(request: Request, exc: ServiceException) -> JSONResponse:
    """
    Default 403 mapping for "not authorized to manage this resource"
    errors. Covers every ResourceForbiddenError subclass (Contract/
    Document/Property/Tenant/PaymentForbiddenError) plus UserForbiddenError,
    which predates ResourceForbiddenError and doesn't share its base class.
    """
    return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content={"detail": str(exc)})


@app.exception_handler(ServiceException)
async def service_exception_handler(request: Request, exc: ServiceException) -> JSONResponse:
    """
    Last-resort safety net for any ServiceException subclass that reaches
    the route layer without a more specific handler or per-route except
    block - e.g. a future exception type a route author forgets to catch,
    or DocumentStorageInconsistentError today (a genuine server-side
    data-consistency failure that replace_document_file deliberately
    leaves uncaught - see its docstring). Returns a generic message
    rather than str(exc): unlike the 404/403 handlers above, this exists
    to safety-net exception types nobody has reviewed the client-facing
    message of, so passing through internal detail isn't safe here. The
    real exception is always logged for diagnosis.
    """
    logger.error("Unhandled ServiceException reached the global handler: %s", exc, exc_info=exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An unexpected error occurred while processing this request."},
    )


@app.exception_handler(IntegrityError)
async def integrity_error_handler(request: Request, exc: IntegrityError) -> JSONResponse:
    """
    Last-resort safety net for FK/unique-constraint violations that reach
    the route layer without being translated into a domain exception first.
    Services should still catch IntegrityError explicitly and raise a
    specific exception where the failure mode is known (see
    app/services/exceptions.py) — this handler exists so a future
    relationship that's missed in a service degrades into a 409 instead of
    a bare, unhandled 500.
    """
    logger.warning("Unhandled IntegrityError reached the global handler: %s", exc)
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"detail": "This action conflicts with existing related records and cannot be completed."},
    )


@app.exception_handler(RedisError)
async def redis_error_handler(request: Request, exc: RedisError) -> JSONResponse:
    """
    Last-resort safety net for Redis connection/timeout errors that reach the route
    layer without being translated into a domain exception first. AuthService.login should still
    catch RedisError explicitly and fail closed with LoginThrottleUnavailableError (see
    app/services/exceptions.py) - this handler exists so a future Redis call that's missed in a service
    degrades into a 503 instead of a bare, unhandled 500.
    """
    logger.error("Unhandled RedisError reached the global handler: %s", exc)
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": "A required service is temporarily unavailable. Please try again shortly."},
    )


# ─── Routers ──────────────────────────────────────────────
app.include_router(auth.router, prefix=settings.API_V1_PREFIX)
app.include_router(users.router, prefix=settings.API_V1_PREFIX)
app.include_router(properties.router, prefix=settings.API_V1_PREFIX)
app.include_router(contracts.router, prefix=settings.API_V1_PREFIX)
app.include_router(tenants.router, prefix=settings.API_V1_PREFIX)
app.include_router(documents.router, prefix=settings.API_V1_PREFIX)
app.include_router(payments.router, prefix=settings.API_V1_PREFIX)
app.include_router(collections.router, prefix=settings.API_V1_PREFIX)
app.include_router(audit_logs.router, prefix=settings.API_V1_PREFIX)
app.include_router(activity_feed.router, prefix=settings.API_V1_PREFIX)
app.include_router(leases.router, prefix=settings.API_V1_PREFIX)
app.include_router(billing_records.router, prefix=settings.API_V1_PREFIX)
app.include_router(receipts.router, prefix=settings.API_V1_PREFIX)
app.include_router(receipt_templates.router, prefix=settings.API_V1_PREFIX)


# ─── Health Check ─────────────────────────────────────────
@app.get("/health", tags=["Health"])
def health_check():
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "env": settings.ENV,
    }
