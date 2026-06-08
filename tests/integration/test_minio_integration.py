import io
import time
import uuid

import pytest

from app.core.dependencies import get_storage_client
from app.core.config import settings


def test_minio_put_stat_get_and_remove_object():
    """Integration test: robustly use the real MinIO instance to put, stat, get, and remove an object.

    The test will:
      - construct the MinIO client via DI
      - wait/retry for the service to become reachable
      - create the bucket if it's missing (and remember to delete it afterward)
      - put an object, stat it, read it back, and remove it

    This test will skip when MinIO is not reachable from the test runtime.
    """
    try:
        client = get_storage_client()
    except Exception as e:
        pytest.skip(f"MinIO client unavailable: {e}")

    bucket = settings.MINIO_BUCKET_NAME
    created_bucket = False
    key = f"test-integration/{uuid.uuid4()}.txt"
    data = b"hello-minio-integration"

    # Wait for MinIO to be reachable and bucket to be checkable
    for attempt in range(8):
        try:
            exists = client.bucket_exists(bucket)
            break
        except Exception:
            if attempt == 7:
                pytest.skip("MinIO not reachable after retries")
            time.sleep(1)

    # Ensure bucket exists; create if missing
    try:
        if not exists:
            client.make_bucket(bucket)
            created_bucket = True
    except Exception as e:
        pytest.skip(f"Cannot ensure bucket exists: {e}")

    # Track whether object was created so we can always attempt cleanup
    object_created = False
    try:
        # Put object
        client.put_object(bucket, key, io.BytesIO(data), len(data), content_type="text/plain")
        object_created = True

        # Stat and validate size
        info = client.stat_object(bucket, key)
        assert info.size == len(data)

        # Read object and validate bytes
        resp = client.get_object(bucket, key)
        try:
            body = resp.read()
            assert body == data
        finally:
            try:
                resp.close()
            except Exception:
                pass
            try:
                resp.release_conn()
            except Exception:
                pass

    finally:
        # Best-effort cleanup: remove object and, if created bucket, delete it too
        try:
            if object_created:
                client.remove_object(bucket, key)
        except Exception:
            pass

        if created_bucket:
            try:
                client.remove_bucket(bucket)
            except Exception:
                # If bucket is not empty or remove fails, ignore — test should not fail on teardown
                pass
