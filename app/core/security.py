import logging

from datetime import datetime, timedelta, timezone

from jose import jwt, JWTError
from passlib.context import CryptContext
from passlib.exc import UnknownHashError

from app.core.config import settings

logger = logging.getLogger(__name__)

pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    bcrypt__truncate_error=False,  # Prevent error if password > 72 bytes
)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plaintext password against a stored hash.
    Uses `pwd_context.dummy_verify()` when `hashed_password` is missing
    or when an error occurs to mitigate timing-based user enumeration.
    """
    try:
        if not hashed_password:
            # consume comparable time to a real verify to mitigate timing attacks
            try:
                pwd_context.dummy_verify()
            except AttributeError:
                # older passlib may not expose dummy_verify; fall back silently
                pass
            return False

        return pwd_context.verify(plain_password, hashed_password)
    except (UnknownHashError, TypeError, ValueError):
        # ensure timing is similar on errors as well
        try:
            pwd_context.dummy_verify()
        except Exception:
            pass
        return False


def create_access_token(data: dict):
    payload = data.copy()

    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    # Use integer epoch timestamps for exp/iat (JWT numeric date)
    payload.update({"exp": int(expire.timestamp()), "iat": int(now.timestamp())})
    if settings.JWT_ISSUER:
        payload["iss"] = settings.JWT_ISSUER
    if settings.JWT_AUDIENCE:
        payload["aud"] = settings.JWT_AUDIENCE

    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            issuer=settings.JWT_ISSUER if settings.JWT_ISSUER else None,
            audience=settings.JWT_AUDIENCE if settings.JWT_AUDIENCE else None,
        )
        return payload
    except JWTError as e:
        logger.error("Error decoding access token: %s", e)
        return None
