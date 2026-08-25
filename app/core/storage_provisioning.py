"""
app/core/storage_provisioning.py

Ensures settings.MINIO_BUCKET_NAME exists on the configured MinIO instance.
Called once from app.main's lifespan(), analogous in spirit to
app.db.provisioning.ensure_database_exists() — but deliberately not that
same module/pattern: ensure_database_exists() is invoked by the dedicated
`migrate` one-off compose service (see docker/docker-compose.yml), and that
service has no counterpart in docker/docker-compose.prod.yml (prod applies
migrations manually post-boot, per README). Bucket provisioning needs to run
uniformly in dev *and* prod, so it lives in the ASGI app's own startup path
instead.
"""

import asyncio
import logging

from minio import Minio
from minio.error import S3Error

from app.core.config import settings

logger = logging.getLogger(__name__)

# A second replica racing to create the same bucket gets this from MinIO
# rather than a generic failure — treat it as success, not an error.
_BUCKET_ALREADY_OWNED = "BucketAlreadyOwnedByYou"


async def ensure_bucket_exists(
    client: Minio | None = None,
    max_retries: int | None = None,
    retry_interval: int | None = None,
) -> None:
    """
    Idempotent — safe to call on every app startup, and safe under multiple
    concurrent backend replicas starting at once.

    Retries mirror app.db.session.wait_for_db()'s pattern: `depends_on:
    condition: service_started` (docker-compose.yml) only guarantees the
    MinIO container process started, not that its S3 API is accepting
    connections yet. Raises RuntimeError (not the underlying MinIO
    exception) after exhausting retries, so a genuinely unreachable MinIO
    fails app startup loudly instead of deferring the failure to the first
    user-facing document/receipt upload.
    """
    from app.core.dependencies import get_storage_client  # local import: avoids importing

    client = client if client is not None else get_storage_client()
    max_retries = max_retries if max_retries is not None else settings.MINIO_MAX_RETRIES
    retry_interval = retry_interval if retry_interval is not None else settings.MINIO_RETRY_INTERVAL
    bucket = settings.MINIO_BUCKET_NAME

    for attempt in range(1, max_retries + 1):
        try:
            if not client.bucket_exists(bucket):
                try:
                    client.make_bucket(bucket)
                    logger.info("Created MinIO bucket %r", bucket)
                except S3Error as e:
                    if e.code != _BUCKET_ALREADY_OWNED:
                        raise
                    logger.info("MinIO bucket %r already exists (create race) — continuing", bucket)
            else:
                logger.info("MinIO bucket %r already exists — skipping creation", bucket)
            return
        except Exception as e:
            if attempt == max_retries:
                logger.error(
                    "MinIO bucket %r could not be verified/created after %d attempts. Last error: %s",
                    bucket,
                    max_retries,
                    e,
                )
                raise RuntimeError(
                    f"Could not ensure MinIO bucket {bucket!r} exists after {max_retries} attempts."
                ) from e

            logger.warning(
                "MinIO bucket check failed (attempt %d/%d) — retrying in %ds...",
                attempt,
                max_retries,
                retry_interval,
            )
            await asyncio.sleep(retry_interval)
