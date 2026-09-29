from backend.app.models.company import Company
from backend.app.models.customer import Customer
from backend.app.models.product import Product
from backend.app.models.order import Order, OrderLine
from backend.app.services.export_registry import AVAILABLE_SOURCE_FIELDS
from datetime import datetime, timezone, timedelta


def test_operator_lists_are_company_scoped_and_searchable(client, db_session):
    a, b = Company(name="Company A"), Company(name="Company B")
    db_session.add_all([a, b]); db_session.flush()
    ca = Customer(company_id=a.id, customer_code="A-101", customer_name="Alpha Deli")
    cb = Customer(company_id=b.id, customer_code="B-202", customer_name="Beta Deli")
    pa = Product(company_id=a.id, sku="SKU-A", description="Alpha turkey", barcode="111")
    pb = Product(company_id=b.id, sku="SKU-B", description="Beta turkey", barcode="222")
    db_session.add_all([ca, cb, pa, pb]); db_session.flush()
    oa = Order(company_id=a.id, customer_id=ca.id, order_number="A-ORDER", status="pending_review", raw_input="10 turkey")
    ob = Order(company_id=b.id, customer_id=cb.id, order_number="B-ORDER", status="approved", raw_input="5 turkey")
    db_session.add_all([oa, ob]); db_session.flush()
    db_session.add_all([
        OrderLine(company_id=a.id, order_id=oa.id, line_number=1, original_text="10 turkey", product_phrase="turkey", requested_quantity=10, requested_unit="piece"),
        OrderLine(company_id=b.id, order_id=ob.id, line_number=1, original_text="5 turkey", product_phrase="turkey", requested_quantity=5, requested_unit="piece"),
    ])
    db_session.commit()

    orders = client.get("/api/v1/orders", params={"company_id": a.id, "search": "Alpha", "status": "pending_review"})
    assert orders.status_code == 200
    assert [(item["order_number"], item["line_count"], item["customer"]["customer_code"]) for item in orders.json()] == [("A-ORDER", 1, "A-101")]
    assert client.get("/api/v1/orders", params={"company_id": a.id, "search": "Beta"}).json() == []
    assert client.get("/api/v1/orders", params={"company_id": a.id, "status": "approved"}).json() == []
    assert client.get("/api/v1/orders", params={"status": "invalid"}).status_code == 400

    assert [c["customer_code"] for c in client.get("/api/v1/customers", params={"company_id": a.id, "search": "A-101"}).json()] == ["A-101"]
    assert client.get("/api/v1/customers", params={"company_id": a.id, "search": "B-202"}).json() == []
    assert [p["sku"] for p in client.get("/api/v1/products", params={"company_id": a.id, "search": "111"}).json()] == ["SKU-A"]
    assert client.get("/api/v1/products", params={"company_id": a.id, "search": "222"}).json() == []


def test_source_field_endpoint_is_the_registry(client):
    response = client.get("/api/v1/export-profiles/source-fields")
    assert response.status_code == 200
    assert response.json() == AVAILABLE_SOURCE_FIELDS


def test_dashboard_summary_counts_tenant_and_operator_day(client, db_session):
    a, b = Company(name="A"), Company(name="B")
    db_session.add_all([a, b]); db_session.flush()
    ca = Customer(company_id=a.id, customer_code="A", customer_name="A")
    cb = Customer(company_id=b.id, customer_code="B", customer_name="B")
    db_session.add_all([ca, cb]); db_session.flush()
    now = datetime.now(timezone.utc)
    pending = Order(company_id=a.id, customer_id=ca.id, order_number="A-1", status="pending_review", raw_input="2 unknown")
    exported = Order(company_id=a.id, customer_id=ca.id, order_number="A-2", status="exported", raw_input="2 sku", approved_at=now, exported_at=now)
    other = Order(company_id=b.id, customer_id=cb.id, order_number="B-1", status="pending_review", raw_input="2 unknown")
    db_session.add_all([pending, exported, other]); db_session.flush()
    db_session.add_all([
        OrderLine(company_id=a.id, order_id=pending.id, line_number=1, original_text="2 unknown", product_phrase="unknown", requested_quantity=2, requested_unit="piece", status="unresolved"),
        OrderLine(company_id=b.id, order_id=other.id, line_number=1, original_text="2 unknown", product_phrase="unknown", requested_quantity=2, requested_unit="piece", status="unresolved"),
    ])
    db_session.commit()
    start = now - timedelta(minutes=1)
    end = now + timedelta(minutes=1)
    response = client.get("/api/v1/orders/summary", params={"company_id": a.id, "day_start": start.isoformat(), "day_end": end.isoformat()})
    assert response.status_code == 200
    assert response.json() == {"pending_review": 1, "approved_today": 1, "exported_today": 1, "needs_attention": 1}
    assert client.get("/api/v1/orders/summary", params={"day_start": start.isoformat(), "day_end": end.isoformat()}).json()["pending_review"] == 2
    assert client.get("/api/v1/orders/summary", params={"day_start": end.isoformat(), "day_end": start.isoformat()}).status_code == 400


def test_built_workspace_is_served_at_root_and_review_deep_link(client):
    from pathlib import Path
    import pytest
    if not (Path(__file__).resolve().parents[2] / "frontend" / "dist" / "index.html").is_file():
        pytest.skip("Frontend build is optional for backend-only installs")
    assert "OrderMind" in client.get("/").text
    assert "OrderMind" in client.get("/orders/123").text
