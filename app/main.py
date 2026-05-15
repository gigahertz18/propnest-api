import time
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.core.config import settings
from app.db.session import engine
from app.api.v1.routes import properties, auth, users

logger = logging.getLogger(__name__)


# ─── Lifespan ─────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    _wait_for_db(
        max_retries=settings.DB_MAX_RETRIES,
        retry_interval=settings.DB_RETRY_INTERVAL,
    )
    logger.info(f"{settings.APP_NAME} started in [{settings.ENV}] mode")
    yield
    engine.dispose()
    logger.info("Database connections closed")


def _wait_for_db(max_retries: int, retry_interval: int) -> None:
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
                    f"Database not available after {max_retries} attempts. "
                    f"Last error: {e}"
                )
                raise RuntimeError(
                    f"Could not connect to the database after {max_retries} attempts."
                ) from e

            logger.warning(
                f"Database not ready "
                f"(attempt {attempt}/{max_retries}) — "
                f"retrying in {retry_interval}s..."
            )
            time.sleep(retry_interval)


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
app.include_router(auth.router,       prefix=settings.API_V1_PREFIX)
app.include_router(users.router,      prefix=settings.API_V1_PREFIX)
app.include_router(properties.router, prefix=settings.API_V1_PREFIX)

# ─── Health Check ─────────────────────────────────────────
@app.get("/health", tags=["Health"])
def health_check():
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "env": settings.ENV,
    }
