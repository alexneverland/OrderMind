import copy
import io
import uuid

import openpyxl
import pytest
from sqlalchemy import select

from backend.app.models.company import Company
from backend.app.models.customer import Customer
from backend.app.models.order import Order, OrderLine, OrderRevision
from backend.app.models.product import Product
from backend.app.models.export import ExportProfile
from backend.app.services.order_workflow_service import OrderWorkflowService, OrderApprovalError
from backend.app.services.order_revision_service import create_revision
from backend.app.services.export_engine import ExportEngine


def approved_order(db, corrected=False, cases=False):
    company = Company(name="Synthetic Revision Company")
    db.add(company); db.flush()
    customer = Customer(company_id=company.id, customer_code="TEST", customer_name="Example Buyer")
    product = Product(company_id=company.id, sku="TEST-1", description="Synthetic Product", unit="piece", active=True)
    db.add_all([customer, product]); db.flush()
    packaging = None
    if cases:
        from backend.app.models.product import Packaging
        packaging = Packaging(company_id=company.id, product_id=product.id, package_type="case", pieces_per_case=12, unit="piece")
        db.add(packaging); db.flush()
    profile = ExportProfile(company_id=company.id, name="Example pallets", format="order_sheet",
        include_header=False, quantity_output_unit="source", bonus_separate_row=True, bonus_marker="A",
        palletization={"enabled": True, "automatic_pallets": {"max_rows": 1}, "output": {"layout": "multi_sheet_workbook"}})
    order = Order(company_id=company.id, customer_id=customer.id, order_number="TEST-ORDER",
        raw_input="TEST-1 3 pieces\nTEST-1 4 pieces", status="pending_review", overall_confidence=1)
    db.add_all([profile, order]); db.flush()
    for number, qty in [(1, 3), (2, 4)]:
        db.add(OrderLine(company_id=company.id, order_id=order.id, line_number=number,
            original_text=f"TEST-1 {qty} pieces", product_phrase="TEST-1", requested_quantity=qty,
            requested_unit="case" if cases else "piece", raw_unit="cases" if cases else "pieces", unit_explicit=True,
            matched_product_id=product.id, final_sku=product.sku, final_quantity=qty + 2 if corrected else qty,
            matched_packaging_id=packaging.id if packaging else None,
            final_bonus_quantity=3 if corrected and number == 1 else None,
            final_unit="case" if cases else "piece", status="confirmed", confidence_score=1, confidence_reasons=[]))
    db.commit()
    OrderWorkflowService.approve_order(db, order.id)
    return order, profile, product


def sheets(content):
    return openpyxl.load_workbook(io.BytesIO(content)).sheetnames


def test_revision_uses_new_pallet_policy_without_rewriting_export_history(db_session, client):
    old, profile, product = approved_order(db_session)
    original_bytes, _, _ = ExportEngine.export_order(db_session, old.id, profile.id)
    snapshot = copy.deepcopy(old.approved_snapshot)
    old_exports = [record.id for record in old.export_records]
    product.kg_per_piece = 1
    profile.palletization = {"enabled": True, "automatic_pallets": {"max_rows": 10, "max_weight_kg": 10}, "output": {"layout": "multi_sheet_workbook"}}
    db_session.commit()
    key = str(uuid.uuid4())
    payload = {"company_id": old.company_id, "request_id": key}
    response = client.post(f"/api/v1/orders/{old.id}/revisions", json=payload)
    assert response.status_code == 201, response.text
    revision = db_session.get(Order, response.json()["id"])
    assert revision.status == "pending_review" and revision.approved_snapshot is None
    assert revision.export_records == []
    assert [line.final_quantity for line in revision.lines] == [3, 4]
    assert all(line.status == "confirmed" for line in revision.lines)
    replay = client.post(f"/api/v1/orders/{old.id}/revisions", json=payload)
    assert replay.json()["id"] == revision.id
    assert len(list(db_session.scalars(select(OrderRevision)))) == 1
    OrderWorkflowService.approve_order(db_session, revision.id)
    assert revision.approved_snapshot["lines"][0]["kg_per_piece"] is not None
    new_bytes, _, _ = ExportEngine.export_order(db_session, revision.id, profile.id)
    reexport, _, _ = ExportEngine.export_order(db_session, old.id, profile.id)
    assert len(sheets(original_bytes)) == len(sheets(reexport)) == 2
    assert len(sheets(new_bytes)) == 1
    db_session.refresh(old)
    assert old.approved_snapshot == snapshot
    assert old.status == "exported"
    assert all(record_id in [record.id for record in old.export_records] for record_id in old_exports)
    assert client.get(f"/api/v1/orders/{old.id}").json()["revisions"][0]["id"] == revision.id
    assert client.get(f"/api/v1/orders/{revision.id}").json()["revision_source"]["id"] == old.id


def test_revision_preserves_paid_corrections_and_recalculates_promotions(db_session):
    from backend.app.models.business_settings import CompanyRule
    old, _, _ = approved_order(db_session, corrected=True)
    original = copy.deepcopy(old.approved_snapshot)
    # Add a rule after the old approval: every 3 pieces gives 1 piece.
    db_session.add(CompanyRule(company_id=old.company_id, rule_type="quantity_bonus", enabled=True,
        fingerprint="revision-test", configuration={"trigger": {"mode": "per_quantity", "quantity": 3, "unit": "piece"},
        "reward": {"quantity": 1, "unit": "piece"}}))
    db_session.commit()
    revision = create_revision(db_session, old.id, old.company_id, str(uuid.uuid4()))
    assert [line.requested_quantity for line in revision.lines] == [3, 4]
    assert [line.final_quantity for line in revision.lines] == [5, 6]
    assert original["lines"][0]["final_bonus_quantity"] == 3
    assert [line.calculated_bonus_quantity for line in revision.lines] == [1, 2]
    assert all(line.bonus_quantity == 0 and line.final_bonus_quantity is None for line in revision.lines)
    assert all(line.status == "needs_review" for line in revision.lines)
    with pytest.raises(OrderApprovalError, match="require review"):
        OrderWorkflowService.approve_order(db_session, revision.id)
    assert old.approved_snapshot == original


def test_recheck_existing_revision_keeps_operator_changes_pending(db_session, client):
    old, _, _ = approved_order(db_session)
    revision = create_revision(db_session, old.id, old.company_id, str(uuid.uuid4()))
    for line in revision.lines:
        line.status = "needs_review"  # State produced by the previous revision implementation.
    revision.lines[0].final_quantity = 99  # A new change still requires explicit review.
    db_session.commit()
    response = client.post(f"/api/v1/orders/{revision.id}/revision-review?company_id={old.company_id}")
    assert response.status_code == 200, response.text
    db_session.refresh(revision)
    assert [line.status for line in revision.lines] == ["needs_review", "confirmed"]
    assert revision.lines[0].final_quantity == 99
    assert client.post(f"/api/v1/orders/{old.id}/revision-review?company_id={old.company_id}").status_code == 409
    assert client.post(f"/api/v1/orders/{revision.id}/revision-review?company_id=999").status_code == 404


def test_changed_case_ratio_requires_review_even_with_high_confidence(db_session):
    from backend.app.models.product import Packaging
    old, _, _ = approved_order(db_session, cases=True)
    package = db_session.scalar(select(Packaging).where(Packaging.company_id == old.company_id))
    package.pieces_per_case = 24
    db_session.commit()
    revision = create_revision(db_session, old.id, old.company_id, str(uuid.uuid4()))
    assert all(line.confidence_score == 1 and line.status == "needs_review" for line in revision.lines)


def test_changed_sku_requires_review_even_with_prior_approval(db_session):
    old, _, product = approved_order(db_session)
    product.sku = "RENAMED"
    db_session.commit()
    revision = create_revision(db_session, old.id, old.company_id, str(uuid.uuid4()))
    assert all(line.status == "needs_review" for line in revision.lines)


def test_changed_output_conversion_requires_review(db_session):
    from backend.app.models.business_settings import CompanyBusinessSettings
    old, profile, _ = approved_order(db_session, cases=True)
    db_session.add(CompanyBusinessSettings(company_id=old.company_id, allow_packaging_conversion=True))
    profile.quantity_output_unit = "piece"
    profile.convert_case_using_pieces_per_case = True
    db_session.commit()
    revision = create_revision(db_session, old.id, old.company_id, str(uuid.uuid4()))
    assert all(line.status == "needs_review" for line in revision.lines)


def test_revision_rejects_wrong_company_missing_snapshot_and_pending_orders(db_session, client):
    old, _, _ = approved_order(db_session)
    other = Company(name="Other Synthetic Company")
    db_session.add(other); db_session.commit()
    key = str(uuid.uuid4())
    assert client.post(f"/api/v1/orders/{old.id}/revisions", json={"company_id": other.id, "request_id": key}).status_code == 404
    result = client.post(f"/api/v1/orders/{old.id}/revisions", json={"company_id": old.company_id, "request_id": key})
    child_id = result.json()["id"]
    assert client.post(f"/api/v1/orders/{child_id}/revisions", json={"company_id": old.company_id, "request_id": str(uuid.uuid4())}).status_code == 409
    assert client.post(f"/api/v1/orders/{child_id}/revisions", json={"company_id": old.company_id, "request_id": key}).status_code == 409
    old.approved_snapshot = None
    db_session.commit()
    assert client.post(f"/api/v1/orders/{old.id}/revisions", json={"company_id": old.company_id, "request_id": str(uuid.uuid4())}).status_code == 409
    assert db_session.scalar(select(Order.id).where(Order.id == child_id)) == child_id


def test_revision_does_not_restore_inactive_catalog_product(db_session):
    old, _, product = approved_order(db_session)
    product.active = False
    db_session.commit()
    revision = create_revision(db_session, old.id, old.company_id, str(uuid.uuid4()))
    assert all(line.status == "unresolved" and line.matched_product_id is None for line in revision.lines)


def test_concurrent_revision_requests_share_one_revision(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from sqlalchemy import create_engine, func
    from sqlalchemy.orm import sessionmaker
    from backend.app.core.database import Base, enable_sqlite_wal
    engine = create_engine(f"sqlite:///{(tmp_path / 'concurrent.sqlite').as_posix()}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    enable_sqlite_wal(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as db:
        source, _, _ = approved_order(db)
        source_id, company_id = source.id, source.company_id
    request_id, barrier = str(uuid.uuid4()), Barrier(2)
    def worker():
        with sessions() as db:
            barrier.wait(timeout=10)
            return create_revision(db, source_id, company_id, request_id).id
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(worker) for _ in range(2)]
            results = [future.result(timeout=15) for future in futures]
        assert results[0] == results[1]
        with sessions() as db:
            assert db.scalar(select(func.count()).select_from(OrderRevision)) == 1
            assert db.scalar(select(func.count()).select_from(Order)) == 2
    finally:
        engine.dispose()


def test_incomplete_snapshot_rolls_back_new_order(db_session):
    from backend.app.services.order_revision_service import RevisionConflictError
    from sqlalchemy import func
    source, _, _ = approved_order(db_session)
    source.approved_snapshot = {"lines": [{"line_id": source.lines[0].id}]}
    db_session.commit()
    with pytest.raises(RevisionConflictError, match="incomplete"):
        create_revision(db_session, source.id, source.company_id, str(uuid.uuid4()))
    assert db_session.scalar(select(func.count()).select_from(Order)) == 1
    assert db_session.scalar(select(func.count()).select_from(OrderRevision)) == 0


def test_populated_head_migrates_without_rewriting_old_snapshot_and_enforces_tenant_fk(tmp_path):
    import sqlite3
    from backend.tests.test_migrations import _alembic
    database = tmp_path / "revisions.sqlite"
    _alembic(database, "upgrade", "b8c9d20015")
    with sqlite3.connect(database) as connection:
        connection.execute("INSERT INTO companies(id,name) VALUES(1,'Example'),(2,'Other')")
        connection.execute("INSERT INTO customers(id,company_id,customer_code,customer_name,active) VALUES(1,1,'TEST','Example',1)")
        for number in (1, 2):
            connection.execute("INSERT INTO orders(id,company_id,customer_id,order_number,version,status,overall_confidence,raw_input,approved_snapshot) VALUES(?,1,1,?,1,'exported',1,'original','{\"lines\":[]}')", (number, f"OLD-{number}"))
    _alembic(database, "upgrade", "head")
    _alembic(database, "check")
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        assert connection.execute("SELECT approved_snapshot FROM orders WHERE id=1").fetchone()[0] == '{"lines":[]}'
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO order_revisions(revision_order_id,source_order_id,company_id,request_key) VALUES(2,1,2,'wrong-company')")
        connection.rollback()
        connection.execute("INSERT INTO order_revisions(revision_order_id,source_order_id,company_id,request_key) VALUES(2,1,1,'valid')")
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
