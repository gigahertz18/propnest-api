from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.v1.routes import properties, auth, users



app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
    docs_url="/docs" if settings.is_dev else None,      # Disable Swagger in prod
    redoc_url="/redoc" if settings.is_dev else None,    # Disable ReDoc in prod
)

# ─── CORS ─────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"] if settings.is_dev else [],  # Tighten in prod
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Routers ──────────────────────────────────────────────────────────────────
# Uncomment as you build each module:
# from app.api.v1.routes import properties, leases, payments, users
app.include_router(properties.router, prefix=settings.API_V1_PREFIX, tags=["Properties"])
app.include_router(auth.router,       prefix=settings.API_V1_PREFIX, tags=["Auth"])
app.include_router(users.router,      prefix=settings.API_V1_PREFIX, tags=["Users"])
# app.include_router(leases.router,     prefix=settings.API_V1_PREFIX, tags=["Leases"])
# app.include_router(payments.router,   prefix=settings.API_V1_PREFIX, tags=["Payments"])
# app.include_router(users.router,      prefix=settings.API_V1_PREFIX, tags=["Users"])


# ─── Health Check ─────────────────────────────────────────────────────────────
@app.get("/health", tags=["Health"])
def health_check():
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "env": settings.ENV,
    }
