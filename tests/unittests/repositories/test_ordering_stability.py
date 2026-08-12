import uuid
import pytest
from datetime import datetime, timezone

from app.repositories.document import document_repo
from app.models.document import Document


async def _make_tied_documents(db, n=4):
    """Insert n Documents sharing one identical created_at timestamp,
    bypassing the factory's dict-builder (which doesn't expose created_at)
    so we can force the exact tie condition the bug depends on."""
    same_ts = datetime.now(timezone.utc)
    docs = []
    for i in range(n):
        doc = Document(
            id=uuid.uuid4(),
            file_name=f"doc_{i}.pdf",
            file_url=f"http://example.com/doc_{i}.pdf",
            file_type="application/pdf",
            created_at=same_ts,
        )
        db.add(doc)
        docs.append(doc)
    await db.flush()
    for doc in docs:
        await db.refresh(doc)
    return docs


@pytest.mark.asyncio
class TestBaseRepositoryOrderingStability:
    async def test_get_all_orders_deterministically_on_created_at_tie(self, db):
        """With all rows sharing one created_at, repeated calls must return
        the same order every time — proving a secondary sort key is in play.
        Without it, Postgres is free to reorder tied rows between calls."""
        await _make_tied_documents(db, n=6)

        first_call = await document_repo.get_all(db, limit=100)
        second_call = await document_repo.get_all(db, limit=100)

        assert [d.id for d in first_call] == [d.id for d in second_call]

    async def test_get_all_pagination_has_no_gaps_or_duplicates_on_tie(self, db):
        """The actual bug: paginating across tied rows with skip/limit must
        not duplicate a row on one page and skip it on another."""
        docs = await _make_tied_documents(db, n=6)

        page_1 = await document_repo.get_all(db, skip=0, limit=3)
        page_2 = await document_repo.get_all(db, skip=3, limit=3)

        seen_ids = [d.id for d in page_1] + [d.id for d in page_2]
        assert sorted(seen_ids) == sorted(d.id for d in docs)
        assert len(seen_ids) == len(set(seen_ids))

    async def test_get_all_secondary_order_matches_id_ascending(self, db):
        """Confirms the tiebreaker is specifically `.id` ascending, not just
        'some' stable order — pins the implementation choice from the fix."""
        docs = await _make_tied_documents(db, n=4)

        result = await document_repo.get_all(db, limit=100)

        assert [d.id for d in result] == sorted((d.id for d in docs))
