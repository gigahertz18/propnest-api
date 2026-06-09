import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.core.config import settings
from app.core.logging import setup_logging
from app.db.session import engine
from app.api.v1.routes import properties, auth, users, contracts, tenants, documents

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
    engine.dispose()
    logger.info("Database connections closed")


async def _wait_for_db(max_retries: int, retry_interval: int) -> None:
    """
    Retries the DB connection until PostgreSQL is ready or max retries exceeded.
    Values come from the active config class — tunable per environment.
    """
    for attempt in range(1, max_retries + 1):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
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

# ─── Routers ──────────────────────────────────────────────
app.include_router(auth.router, prefix=settings.API_V1_PREFIX)
app.include_router(users.router, prefix=settings.API_V1_PREFIX)
app.include_router(properties.router, prefix=settings.API_V1_PREFIX)
app.include_router(contracts.router, prefix=settings.API_V1_PREFIX)
app.include_router(tenants.router, prefix=settings.API_V1_PREFIX)
app.include_router(documents.router, prefix=settings.API_V1_PREFIX)


# ─── Health Check ─────────────────────────────────────────
@app.get("/health", tags=["Health"])
def health_check():
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "env": settings.ENV,
    }
