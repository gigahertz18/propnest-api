import pytest

from app.core.config import ProductionConfig

VALID_ENV = {
    "SECRET_KEY": "a" * 32,
    "DB_PASSWORD": "a-real-db-password",
    "MINIO_ROOT_PASSWORD": "a-real-minio-password",
    "REDIS_PASSWORD": "a-real-redis-password",
}


def _set_env(monkeypatch, **overrides):
    env = {**VALID_ENV, **overrides}
    for key, value in env.items():
        monkeypatch.setenv(key, value)


def test_validate_passes_with_all_secure_env_vars(monkeypatch):
    _set_env(monkeypatch)
    ProductionConfig().validate()


def test_validate_raises_when_secret_key_is_known_insecure_default(monkeypatch):
    _set_env(monkeypatch, SECRET_KEY="dev-secret-key-to-the-universe-pwease-override")
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        ProductionConfig().validate()


def test_validate_raises_when_secret_key_too_short(monkeypatch):
    _set_env(monkeypatch, SECRET_KEY="too-short")
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        ProductionConfig().validate()


def test_validate_raises_when_db_password_is_known_insecure_default(monkeypatch):
    _set_env(monkeypatch, DB_PASSWORD="propnest_secret")
    with pytest.raises(RuntimeError, match="DB_PASSWORD"):
        ProductionConfig().validate()


def test_validate_raises_when_minio_root_password_is_known_insecure_default(monkeypatch):
    _set_env(monkeypatch, MINIO_ROOT_PASSWORD="propnest_secret")
    with pytest.raises(RuntimeError, match="MINIO_ROOT_PASSWORD"):
        ProductionConfig().validate()


def test_validate_raises_when_redis_password_is_empty(monkeypatch):
    _set_env(monkeypatch, REDIS_PASSWORD="")
    with pytest.raises(RuntimeError, match="REDIS_PASSWORD"):
        ProductionConfig().validate()


def test_validate_raises_when_access_token_expire_minutes_exceeds_30(monkeypatch):
    _set_env(monkeypatch)
    config = ProductionConfig()
    config.ACCESS_TOKEN_EXPIRE_MINUTES = 45
    with pytest.raises(RuntimeError, match="ACCESS_TOKEN_EXPIRE_MINUTES"):
        config.validate()


def test_constructing_production_config_raises_when_required_env_var_missing(monkeypatch):
    """
    SECRET_KEY/DB_PASSWORD/MINIO_ROOT_PASSWORD/REDIS_PASSWORD are read via
    `os.environ[...]` (not `.get`), so a genuinely *missing* var fails at
    construction time with a KeyError rather than surfacing through
    `validate()`'s RuntimeError — `validate()` only catches vars that are
    present but insecure/empty. Documented here since it's the other half
    of "required env var" enforcement referenced by the class docstring/PRD.
    """
    _set_env(monkeypatch)
    monkeypatch.delenv("SECRET_KEY")
    with pytest.raises(KeyError):
        ProductionConfig()
