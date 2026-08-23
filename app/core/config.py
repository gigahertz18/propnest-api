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

    # Redis — rate limiting (per-IP) and login-lockout state (per-identifier)
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: str | None = None

    # Redis - background job queue (ARQ). Same REdis instance/credentials as
    # above; only the logicla DB index differs. Indeces 0-9 are reserved for
    # core app concenrs (rate limiting/lockout, and per environment variants
    # of that - see UnittestConfig/TestConfig below); 10+ is reserved for
    # background jobs, so the same integer was never asked to mean two different
    # things at once for a given environment.
    REDIS_JOBS_DB: int = 10

    # Redis connection tuning - mirrors the pool_size/pool_pre_pign tuning
    # already done for the SQLAlchemy engine below.
    REDIS_MAX_CONNECTIONS: int = 20
    REDIS_SOCKET_TIMEOUT: float = 2.0  # seconds a command can block before giving up
    REDIS_SOCKET_CONNECT_TIMEOUT: float = 2.0
    REDIS_HEALTH_CHECK_INTERVAL: int = 30  # seconds between pings on idle connections

    # Dedicated system identity the billing scheduling job authenticates as
    # (see app/jobs/billing_jobs.py, scripts/seed_system_user.py). Not a secret -
    # just stable, well-known primary key so the job can fetch it directly rather
    # than the username. AuthService.login refuses to authenticate this identity outright
    # (see auth_service.py) - it's never meant to hold a session.
    SYSTEM_SCHEDULER_USER_ID: str = "00000000-0000-0000-0000-000000000001"
    SYSTEM_SCHEDULER_USERNAME: str = "system.scheduler"
    SYSTEM_SCHEDULER_EMAIL: str = "system-scheduler@propnest.internal"

    # Cadence for the automated billing jobs (app/jobs/billing_jobs.py). Both jobs run
    # once daily at this hour:minute - deliberately explicit, separate settings (not a cron string)
    # so the cadence can be retuned via env var alone, no code change needed.
    # Default 01:00 - after midnight, ahead of typical morning dashboard checks.
    BILLING_JOB_CRON_HOUR: int = 1
    BILLING_JOB_CRON_MINUTE: int = 0

    # Auth / JWT
    SECRET_KEY: str = "dev-secret-key-to-the-universe-pwease-override"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    JWT_ISSUER: str = "propnest-api"
    JWT_AUDIENCE: str = "propnest-users"

    # Login throttling - see AuthService.login / LoginAttemptRepository/ IpRateLimitRepository
    LOGIN_RATE_LIMIT_MAX_REQUESTS: int = 10
    LOGIN_RATE_LIMIT_WINDOW_SECONDS: int = 60
    LOGIN_MAX_FAILED_ATTEMPTS: int = 5
    LOGIN_FAILURE_WINDOW_SECONDS: int = 900  # 15 min rolling window for counting failures
    LOGIN_LOCKOUT_BASE_SECONDS: int = 30
    LOGIN_LOCKOUT_MAX_SECONDS: int = 900  # 15 min cap, progressive backoff doubles up to this

    # CORS
    CORS_ORIGINS: list[str] = field(default_factory=lambda: ["http://localhost:3000"])

    @property
    def DATABASE_URL(self) -> str:
        return f"postgresql+asyncpg://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    @property
    def REDIS_URL(self) -> str:
        auth = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
        return f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    @property
    def REDIS_JOBS_URL(self) -> str:
        auth = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
        return f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_JOBS_DB}"

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

    # Separate Redis DB index so test runs never share keyspace with dev.
    REDIS_DB: int = 1
    # Same reasoning, reserved range: dev jobs=10, unittest jobs=11
    REDIS_JOBS_DB: int = 11

    # Small, fast values so lockout/rate-limit tests don't need long sleeps.
    LOGIN_RATE_LIMIT_MAX_REQUESTS: int = 5
    LOGIN_RATE_LIMIT_WINDOW_SECONDS: int = 60
    LOGIN_MAX_FAILED_ATTEMPTS: int = 3
    LOGIN_FAILURE_WINDOW_SECONDS: int = 30
    LOGIN_LOCKOUT_BASE_SECONDS: int = 2
    LOGIN_LOCKOUT_MAX_SECONDS: int = 6


# ─── Test ─────────────────────────────────────────────────────────────────────
@dataclass
class TestConfig(BaseConfig):

    DEBUG: bool = True
    ENV: str = "test"

    # DB should already be running when tests execute — retry fast
    DB_MAX_RETRIES: int = 5
    DB_RETRY_INTERVAL: int = 1

    REDIS_DB: int = 2
    REDIS_JOBS_DB: int = 12


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
    DB_HOST: str = field(default_factory=lambda: os.environ.get("DB_HOST", "db"))
    DB_PORT: int = field(default_factory=lambda: int(os.environ.get("DB_PORT", "5432")))
    DB_NAME: str = field(default_factory=lambda: os.environ.get("DB_NAME", "propnest_db"))
    DB_USER: str = field(default_factory=lambda: os.environ.get("DB_USER", "propnest"))
    DB_PASSWORD: str = field(default_factory=lambda: os.environ["DB_PASSWORD"])
    SECRET_KEY: str = field(default_factory=lambda: os.environ["SECRET_KEY"])
    MINIO_ROOT_PASSWORD: str = field(default_factory=lambda: os.environ["MINIO_ROOT_PASSWORD"])
    REDIS_HOST: str = field(default_factory=lambda: os.environ.get("REDIS_HOST", "redis"))
    REDIS_PORT: int = field(default_factory=lambda: int(os.environ.get("REDIS_PORT", "6379")))
    REDIS_PASSWORD: str = field(default_factory=lambda: os.environ["REDIS_PASSWORD"])
    JWT_ISSUER: str = field(default_factory=lambda: os.environ.get("JWT_ISSUER", "propnest-api"))
    JWT_AUDIENCE: str = field(default_factory=lambda: os.environ.get("JWT_AUDIENCE", "propnest-users"))
    CORS_ORIGINS: list[str] = field(
        default_factory=lambda: [
            origin.strip() for origin in os.environ.get("CORS_ORIGINS", "").split(",") if origin.strip()
        ]
    )

    # Redis Scheduler
    REDIS_JOBS_DB: int = field(default_factory=lambda: int(os.environ.get("REDIS_JOBS_DB", "10")))
    SYSTEM_SCHEDULER_USER_ID: str = field(
        default_factory=lambda: os.environ.get("SYSTEM_SCHEDULER_USER_ID", "00000000-0000-0000-0000-000000000001")
    )
    SYSTEM_SCHEDULER_USERNAME: str = field(
        default_factory=lambda: os.environ.get("SYSTEM_SCHEDULER_USERNAME", "system.scheduler")
    )
    BILLING_JOB_CRON_HOUR: int = field(default_factory=lambda: int(os.environ.get("BILLING_JOB_CRON_HOUR", "1")))
    BILLING_JOB_CRON_MINUTE: int = field(default_factory=lambda: int(os.environ.get("BILLING_JOB_CRON_MINUTE", "0")))

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

        if not self.REDIS_PASSWORD:
            errors.append(
                "REDIS_PASSWORD is not set. Set the REDIS_PASSWORD environment variable "
                "so login-lockout/rate-limit state isn't exposed on an authenticated Redis instance."
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
    config = config_class()

    # Fail loudly rather than silently sharing keyspace: REDIS_DB and REDIS_JOBS_DB
    # are two different concerns on the same Redis instance - if they're ever
    # equal (a copy-paste mistake in a future env subclass), a FLUSHDB in tests/conftest.py's
    # _flush_redis would wipe both, and rate-limit state would leak into job-queue keyspace
    # or vice-versa.
    if config.REDIS_DB == config.REDIS_JOBS_DB:
        raise RuntimeError(
            f"REDIS_DB and REDIS_JOBS_DB are both {config.REDIS_DB} for ENV={env} - "
            "they must use different logical Redis DB indices."
        )

    return config


# Singleton — import this everywhere instead of instantiating directly
settings = get_config()
