import os
from dataclasses import dataclass, field

_KNOWN_INSECURE = {
    "dev-secret-key-to-the-universe-pwease-override",
    "propnest_secret",
}


# ─── Base ─────────────────────────────────────────────────────────────────────
@dataclass
class BaseConfig:
    # App
    APP_NAME: str = "PropNest API"
    API_V1_PREFIX: str = "/api/v1"
    DEBUG: bool = False
    ENV: str = "base"

    # Database
    DB_HOST: str = "db"
    DB_PORT: int = 5432
    DB_NAME: str = "propnest_db"
    DB_USER: str = "propnest"
    DB_PASSWORD: str = "propnest_secret"

    # Database retry — how long the app waits for PostgreSQL on startup
    DB_MAX_RETRIES: int = 10
    DB_RETRY_INTERVAL: int = 3  # seconds

    # MinIO
    MINIO_ENDPOINT: str = "http://minio:9000"
    MINIO_ROOT_USER: str = "propnest_minio"
    MINIO_ROOT_PASSWORD: str = "propnest_secret"
    MINIO_BUCKET_NAME: str = "propnest-contracts"

    # Auth / JWT
    SECRET_KEY: str = "dev-secret-key-to-the-universe-pwease-override"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    JWT_ISSUER: str = "propnest-api"
    JWT_AUDIENCE: str = "propnest-users"

    # CORS
    CORS_ORIGINS: list[str] = field(default_factory=lambda: ["http://localhost:3000"])

    @property
    def DATABASE_URL(self) -> str:
        return f"postgresql://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    @property
    def is_dev(self) -> bool:
        return self.ENV in ("dev", "unittest", "test")  # treat test envs as dev-like (enables Swagger, etc.)

    @property
    def is_staging(self) -> bool:
        return self.ENV == "staging"

    @property
    def is_prod(self) -> bool:
        return self.ENV == "prod"

    @property
    def is_test(self) -> bool:
        return self.ENV in ("unittest", "test")

    def validate(self) -> None:
        """
        Call once at startup. Raises RuntimeError if config is unsafe for the current environment.
        No-ops for dev/test configs, but prevents production configs from accidentally running with unsafe defaults.
        """
        pass  # override in production config to check for secrets from environment variables


# ─── Development ──────────────────────────────────────────────────────────────
@dataclass
class DevelopmentConfig(BaseConfig):
    DEBUG: bool = True
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 120
    ENV: str = "dev"

    # More retries in dev — local Docker can be slow to start
    DB_MAX_RETRIES: int = 15
    DB_RETRY_INTERVAL: int = 2


# ─── Unittest ─────────────────────────────────────────────────────────────────────
@dataclass
class UnittestConfig(BaseConfig):
    """
    Used exclusively when running pytest via `make test` and related commands.
    Points to a dedicated test database so real data is never touched.
    Tables are dropped after each test session for a clean slate.
    """

    DB_NAME: str = "propnest_unittest_db"
    DEBUG: bool = True

    ENV: str = "unittest"

    # DB should already be running when tests execute — retry fast
    DB_MAX_RETRIES: int = 5
    DB_RETRY_INTERVAL: int = 1


# ─── Test ─────────────────────────────────────────────────────────────────────
@dataclass
class TestConfig(BaseConfig):

    DEBUG: bool = True
    ENV: str = "test"

    # DB should already be running when tests execute — retry fast
    DB_MAX_RETRIES: int = 5
    DB_RETRY_INTERVAL: int = 1


# ─── Staging ──────────────────────────────────────────────────────────────────
@dataclass
class StagingConfig(BaseConfig):

    DB_MAX_RETRIES: int = 10
    DB_RETRY_INTERVAL: int = 3
    ENV: str = "staging"


# ─── Production ───────────────────────────────────────────────────────────────
@dataclass
class ProductionConfig(BaseConfig):
    DEBUG: bool = False
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    ENV: str = "prod"

    # Production DB may take longer to accept connections
    # after a deploy or failover — give it more room
    DB_MAX_RETRIES: int = 20
    DB_RETRY_INTERVAL: int = 5

    # Secrets from environment only in production
    DB_PASSWORD: str = field(default_factory=lambda: os.environ["DB_PASSWORD"])
    SECRET_KEY: str = field(default_factory=lambda: os.environ["SECRET_KEY"])
    MINIO_ROOT_PASSWORD: str = field(default_factory=lambda: os.environ["MINIO_ROOT_PASSWORD"])
    JWT_ISSUER: str = field(default_factory=lambda: os.environ.get("JWT_ISSUER", "propnest-api"))
    JWT_AUDIENCE: str = field(default_factory=lambda: os.environ.get("JWT_AUDIENCE", "propnest-users"))
    CORS_ORIGINS: list[str] = field(
        default_factory=lambda: [
            origin.strip() for origin in os.environ.get("CORS_ORIGINS", "").split(",") if origin.strip()
        ]
    )

    def validate(self) -> None:
        errors = []

        if not self.SECRET_KEY or self.SECRET_KEY in _KNOWN_INSECURE:
            errors.append(
                "SECRET_KEY is not set or is using a known insecure default. "
                "Set the SECRET_KEY environment variable."
            )
        if len(self.SECRET_KEY) < 32:
            errors.append("SECRET_KEY must be at least 32 characters.")

        if not self.DB_PASSWORD or self.DB_PASSWORD in _KNOWN_INSECURE:
            errors.append(
                "DB_PASSWORD is not set or is using a known insecure default. "
                "Set the DB_PASSWORD environment variable."
            )

        if not self.MINIO_ROOT_PASSWORD or self.MINIO_ROOT_PASSWORD in _KNOWN_INSECURE:
            errors.append(
                "MINIO_ROOT_PASSWORD is not set or is using a known insecure default. "
                "Set the MINIO_ROOT_PASSWORD environment variable."
            )

        if self.ACCESS_TOKEN_EXPIRE_MINUTES > 30:
            errors.append(
                f"ACCESS_TOKEN_EXPIRE_MINUTES is {self.ACCESS_TOKEN_EXPIRE_MINUTES}. " "Must be ≤ 30 in production."
            )

        if errors:
            raise RuntimeError("Production config validation failed:\n" + "\n".join(f"  - {e}" for e in errors))


# ─── Factory ──────────────────────────────────────────────────────────────────
_CONFIG_MAP: dict[str, type[BaseConfig]] = {
    "dev": DevelopmentConfig,
    "unittest": UnittestConfig,
    "test": TestConfig,
    "staging": StagingConfig,
    "prod": ProductionConfig,
}


def get_config() -> BaseConfig:
    """
    Factory — reads the ENV environment variable and returns
    the matching config instance.

    ENV is the only environment variable required for non-production environments.
    """
    env = os.getenv("ENV", "dev")
    config_class = _CONFIG_MAP.get(env)
    if not config_class:
        raise ValueError(f"Unknown environment '{env}'. " f"Valid options: {list(_CONFIG_MAP.keys())}")
    return config_class()


# Singleton — import this everywhere instead of instantiating directly
settings = get_config()
