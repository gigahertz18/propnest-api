from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ─── General ──────────────────────────────────────────
    ENV: str = "dev"
    APP_NAME: str = "PropNest API"
    API_V1_PREFIX: str = "/api/v1"

    # ─── PostgreSQL ───────────────────────────────────────
    DATABASE_URL: str

    # ─── MinIO ────────────────────────────────────────────
    MINIO_ENDPOINT: str
    MINIO_ROOT_USER: str
    MINIO_ROOT_PASSWORD: str
    MINIO_BUCKET_NAME: str = "propnest-contracts"

    # ─── Auth / JWT ───────────────────────────────────────
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    model_config = SettingsConfigDict(
        env_file=".env",          # Fallback — Docker injects these directly
        extra="ignore",
    )

    @property
    def is_dev(self) -> bool:
        return self.ENV == "dev"

    @property
    def is_prod(self) -> bool:
        return self.ENV == "prod"


settings = Settings()
