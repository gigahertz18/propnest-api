import pytest
from unittest.mock import AsyncMock
from minio.error import S3Error

from app.core import storage_provisioning


class _FakeStorageClient:
    """Minimal stand-in for the MinIO client — only what ensure_bucket_exists touches."""

    def __init__(self, exists_result=False, exists_side_effect=None, make_bucket_side_effect=None):
        self._exists_result = exists_result
        self._exists_side_effect = exists_side_effect or []
        self.bucket_exists_calls = 0
        self.make_bucket_calls = 0
        self.make_bucket_side_effect = make_bucket_side_effect

    def bucket_exists(self, bucket):
        self.bucket_exists_calls += 1
        if self._exists_side_effect:
            effect = self._exists_side_effect.pop(0)
            if isinstance(effect, Exception):
                raise effect
            return effect
        return self._exists_result

    def make_bucket(self, bucket):
        self.make_bucket_calls += 1
        if self.make_bucket_side_effect:
            raise self.make_bucket_side_effect


def _s3_error(code):
    return S3Error(
        code=code,
        message="mocked",
        resource="/propnest-contracts",
        request_id="req",
        host_id="host",
        response=None,
    )


@pytest.mark.asyncio
class TestEnsureBucketExists:
    async def test_creates_bucket_when_missing(self):
        client = _FakeStorageClient(exists_result=False)

        await storage_provisioning.ensure_bucket_exists(client=client)

        assert client.make_bucket_calls == 1

    async def test_skips_creation_when_already_present(self):
        client = _FakeStorageClient(exists_result=True)

        await storage_provisioning.ensure_bucket_exists(client=client)

        assert client.make_bucket_calls == 0

    async def test_treats_bucket_already_owned_race_as_success(self):
        client = _FakeStorageClient(
            exists_result=False,
            make_bucket_side_effect=_s3_error("BucketAlreadyOwnedByYou"),
        )

        # Must not raise — another replica won the create race.
        await storage_provisioning.ensure_bucket_exists(client=client)

        assert client.make_bucket_calls == 1

    async def test_retries_then_succeeds(self, monkeypatch):
        monkeypatch.setattr(storage_provisioning.asyncio, "sleep", AsyncMock())
        client = _FakeStorageClient(exists_side_effect=[RuntimeError("not ready"), False])

        await storage_provisioning.ensure_bucket_exists(client=client, max_retries=3, retry_interval=0)

        assert client.bucket_exists_calls == 2
        assert client.make_bucket_calls == 1

    async def test_raises_after_max_retries(self, monkeypatch):
        monkeypatch.setattr(storage_provisioning.asyncio, "sleep", AsyncMock())
        client = _FakeStorageClient(exists_side_effect=[RuntimeError("down")] * 3)

        with pytest.raises(RuntimeError, match="propnest-documents"):
            await storage_provisioning.ensure_bucket_exists(client=client, max_retries=3, retry_interval=0)

        assert client.bucket_exists_calls == 3

    async def test_propagates_non_race_s3_error_from_make_bucket(self, monkeypatch):
        monkeypatch.setattr(storage_provisioning.asyncio, "sleep", AsyncMock())
        client = _FakeStorageClient(
            exists_result=False,
            make_bucket_side_effect=_s3_error("AccessDenied"),
        )

        with pytest.raises(RuntimeError):
            await storage_provisioning.ensure_bucket_exists(client=client, max_retries=2, retry_interval=0)
