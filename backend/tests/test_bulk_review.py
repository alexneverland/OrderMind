import copy
import pytest

from sqlalchemy import select, func

from backend.app.models.order import MatchCandidate, Order
from backend.app.models.product import Product
from backend.app.models.memory import CustomerProductAlias, CompanyProductUnitPreference
from backend.app.models.business_settings import CompanyBusinessSettings, CompanyRule
from backend.tests.test_order_revisions import approved_order


def pending_order(db):
    order, _, product = approved_order(db)
    order.status = "pending_review"
    order.approved_snapshot = None
    for line in order.lines:
        line.status = "needs_review"
        line.confidence_score = .98
        db.add(MatchCandidate(company_id=order.company_id, order_line_id=line.id, product_id=product.id,
            rank=1, match_type="exact_sku", score=.98, explanation="Synthetic exact match"))
    db.commit()
    return order, product


def confirm(client, order, version=None, company=None):
    return client.post(f"/api/v1/orders/{order.id}/confirm-safe", params={
        "company_id": company or order.company_id,
        "expected_version": version if version is not None else order.version,
    })


def test_bulk_confirms_safe_match_leaves_ambiguous_match_and_does_not_train(db_session, client):
    order, _ = pending_order(db_session)
    competitor = Product(company_id=order.company_id, sku="OTHER", description="Synthetic competitor", active=True)
    db_session.add(competitor); db_session.flush()
    db_session.add(MatchCandidate(company_id=order.company_id, order_line_id=order.lines[1].id,
        product_id=competitor.id, rank=2, match_type="exact_match", score=.97, explanation="Close alternative"))
    db_session.commit()
    result = confirm(client, order)
    assert result.status_code == 200, result.text
    assert result.json()["confirmed_count"] == 1
    assert result.json()["skipped"][0]["reason"] == "Competing product matches"
    db_session.expire_all()
    assert [line.status for line in order.lines] == ["confirmed", "needs_review"]
    assert db_session.scalar(select(func.count()).select_from(CustomerProductAlias)) == 0
    assert confirm(client, order).json()["confirmed_count"] == 0


def test_bulk_checks_version_tenant_and_closed_status(db_session, client):
    order, _ = pending_order(db_session)
    version = order.version
    assert confirm(client, order, company=999).status_code == 404
    assert confirm(client, order).json()["confirmed_count"] == 2
    assert confirm(client, order, version=version).status_code == 409
    db_session.expire_all()
    order.status = "cancelled"; db_session.commit()
    assert confirm(client, order).status_code == 409


def test_bulk_requires_grounded_unchanged_quantities_and_confidence(db_session, client):
    order, _ = pending_order(db_session)
    order.lines[0].confidence_score = .94
    # Even a confident match cannot confirm a new, unsupported final quantity.
    order.lines[1].final_quantity = 999
    db_session.commit()
    result = confirm(client, order).json()
    assert result["confirmed_count"] == 0
    assert [item["reason"] for item in result["skipped"]] == ["Confidence below 95%", "Quantity changed or invalid"]
    order.lines[0].confidence_score = .98
    order.lines[0].original_text = "TEST-1 99 pieces"
    db_session.commit()
    assert confirm(client, order).json()["skipped"][0]["reason"] == "Quantity or unit unsupported by customer input"


def test_bulk_uses_current_learned_unit_and_rejects_stale_promotion(db_session, client):
    order, product = pending_order(db_session)
    db_session.add(CompanyBusinessSettings(company_id=order.company_id,
        unitless_order_behavior="learned_product_preference", learn_unit_preferences=True))
    db_session.add(CompanyProductUnitPreference(company_id=order.company_id, product_id=product.id, unit="piece"))
    first = order.lines[0]
    first.unit_explicit = False; first.requested_unit = "unknown"; first.raw_unit = None
    first.original_text = "TEST-1 3"; order.raw_input = "TEST-1 3\nTEST-1 4 pieces"
    db_session.commit()
    assert confirm(client, order).json()["confirmed_count"] == 2
    db_session.expire_all()
    for line in order.lines: line.status = "needs_review"
    db_session.add(CompanyRule(company_id=order.company_id, rule_type="quantity_bonus", enabled=True,
        fingerprint="bulk-stale-promotion", configuration={"trigger": {"mode": "per_quantity", "quantity": 3, "unit": "piece"},
        "reward": {"quantity": 1, "unit": "piece"}}))
    db_session.commit()
    result = confirm(client, order).json()
    assert result["confirmed_count"] == 0
    assert all(item["reason"] == "Promotion changed or conflicting" for item in result["skipped"])


def test_legacy_snapshot_without_product_id_retains_prior_review(db_session, client):
    import uuid
    old, _, _ = approved_order(db_session)
    snapshot = copy.deepcopy(old.approved_snapshot)
    for line in snapshot["lines"]: line.pop("product_id", None)
    old.approved_snapshot = snapshot; db_session.commit()
    response = client.post(f"/api/v1/orders/{old.id}/revisions", json={"company_id": old.company_id, "request_id": str(uuid.uuid4())})
    assert response.status_code == 201, response.text
    assert all(line["status"] == "confirmed" for line in response.json()["lines"])
    revision = db_session.get(Order, response.json()["id"])
    for line in revision.lines: line.status = "needs_review"
    db_session.commit()
    response = client.post(f"/api/v1/orders/{revision.id}/revision-review", params={"company_id": old.company_id})
    assert all(line["status"] == "confirmed" for line in response.json()["lines"])
    db_session.expire_all()
    assert old.approved_snapshot == snapshot


def test_concurrent_bulk_requests_reject_stale_version(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from backend.app.core.database import Base, enable_sqlite_wal
    from backend.app.services.bulk_review_service import confirm_safe_lines, BulkReviewConflict
    engine = create_engine(f"sqlite:///{(tmp_path / 'bulk.sqlite').as_posix()}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    enable_sqlite_wal(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as db:
        order, _ = pending_order(db)
        order_id, company_id, version = order.id, order.company_id, order.version
    barrier = Barrier(2)
    def worker():
        with sessions() as db:
            barrier.wait(timeout=10)
            try:
                return confirm_safe_lines(db, order_id, company_id, version)["confirmed_count"]
            except BulkReviewConflict:
                return "stale"
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(worker) for _ in range(2)]
            results = [future.result(timeout=15) for future in futures]
        assert results.count(2) == 1 and results.count("stale") == 1
        with sessions() as db:
            assert db.get(Order, order_id).version == version + 1
            assert db.scalar(select(func.count()).select_from(CustomerProductAlias)) == 0
    finally:
        engine.dispose()


@pytest.mark.parametrize("learned_unit", [False, True])
def test_bulk_reaches_safe_lines_from_normal_order_creation(db_session, client, learned_unit):
    source, _, product = approved_order(db_session)
    if learned_unit:
        db_session.add(CompanyBusinessSettings(company_id=source.company_id,
            unitless_order_behavior="learned_product_preference", learn_unit_preferences=True))
        db_session.add(CompanyProductUnitPreference(company_id=source.company_id, product_id=product.id, unit="piece"))
        db_session.commit()
    text = "TEST-1 3" if learned_unit else "TEST-1 3 pieces"
    response = client.post("/api/v1/orders/create-from-match", json={
        "company_id": source.company_id, "customer_id": source.customer_id, "raw_input": text,
        "items": [{"line_number": 1, "original_text": text, "product_phrase": "TEST-1", "quantity": 3,
            "unit": "unknown" if learned_unit else "piece", "raw_unit": None if learned_unit else "pieces",
            "unit_explicit": not learned_unit}],
    })
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["lines"][0]["confidence_score"] >= .95
    assert data["lines"][0]["status"] == ("needs_review" if learned_unit else "auto_accepted")
    response = client.post(f"/api/v1/orders/{data['id']}/confirm-safe", params={
        "company_id": source.company_id, "expected_version": data["version"],
    })
    assert response.status_code == 200, response.text
    assert response.json()["confirmed_count"] == 1 and response.json()["skipped"] == []
    persisted = client.get(f"/api/v1/orders/{data['id']}").json()
    assert persisted["lines"][0]["status"] == "confirmed"


def test_bulk_downgrades_unsafe_auto_accepted_line(db_session, client):
    order, _ = pending_order(db_session)
    for line in order.lines: line.status = "auto_accepted"
    order.lines[1].final_quantity = 999
    version = order.version
    db_session.commit()
    result = confirm(client, order).json()
    assert result["confirmed_count"] == 1 and result["version"] == version + 1
    db_session.expire_all()
    assert [line.status for line in order.lines] == ["confirmed", "needs_review"]
