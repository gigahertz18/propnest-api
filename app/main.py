import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.logging import setup_logging
from app.db.session import engine
from app.api.v1.routes import properties, auth, users, contracts, tenants, documents, payments

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
    logger.info("%s started in [%s] mode", settings.APP_NAME, settings.ENV)
    yield
    await engine.dispose()
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


# ─── Routers ──────────────────────────────────────────────
app.include_router(auth.router, prefix=settings.API_V1_PREFIX)
app.include_router(users.router, prefix=settings.API_V1_PREFIX)
app.include_router(properties.router, prefix=settings.API_V1_PREFIX)
app.include_router(contracts.router, prefix=settings.API_V1_PREFIX)
app.include_router(tenants.router, prefix=settings.API_V1_PREFIX)
app.include_router(documents.router, prefix=settings.API_V1_PREFIX)
app.include_router(payments.router, prefix=settings.API_V1_PREFIX)


# ─── Health Check ─────────────────────────────────────────
@app.get("/health", tags=["Health"])
def health_check():
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "env": settings.ENV,
    }
