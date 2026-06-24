from concurrent.futures import ThreadPoolExecutor, as_completed

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.repositories.contract import contract_repo
from app.models.property import Property
from app.models.tenant import Tenant
from tests.factories import make_property_model, make_tenant_model, make_contract


def test_concurrent_create_active_contracts_fails_once(db):
    # Create an engine/session local for concurrent workers. Also create the
    # property and tenant using that same session so other connections can see
    # the rows (the test `db` fixture uses a nested transaction that is NOT
    # visible to separate connections).
    engine = create_engine(settings.DATABASE_URL)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    with SessionLocal() as setup_session:
        prop = make_property_model(setup_session)
        tenant = make_tenant_model(setup_session)
        # capture scalar IDs immediately to avoid DetachedInstance issues
        prop_id = prop.id
        tenant_id = tenant.id

    def create_contract():
        with SessionLocal() as session:
            return contract_repo.create(session, make_contract(property_id=prop_id, tenant_id=tenant_id))

    successes = 0
    failures = 0
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(create_contract) for _ in range(2)]
            for future in as_completed(futures):
                try:
                    future.result()
                    successes += 1
                except IntegrityError:
                    failures += 1
    finally:
        # cleanup created contracts, property, and tenant so subsequent tests
        # are not affected by rows inserted outside the test transaction.
        with SessionLocal() as cleanup_session:
            contracts = contract_repo.get_by_property(cleanup_session, prop_id)
            for c in contracts:
                cleanup_session.delete(c)
            # Remove property and tenant created for the concurrency test
            p = cleanup_session.get(Property, prop_id)
            if p:
                cleanup_session.delete(p)
            t = cleanup_session.get(Tenant, tenant_id)
            if t:
                cleanup_session.delete(t)
            cleanup_session.commit()

    assert successes == 1
    assert failures == 1
