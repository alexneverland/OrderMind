import pytest
from fastapi.testclient import TestClient

from backend.app.models.company import Company
from backend.app.models.customer import Customer
from backend.app.models.product import Product
from backend.app.models.order import Order, OrderLine
from backend.app.models.memory import CustomerProductAlias


def setup_milestone3_api_data(db_session):
    company = Company(name="Olympus Meats")
    db_session.add(company)
    db_session.flush()

    customer = Customer(company_id=company.id, customer_code="CUST-DELI", customer_name="Greek Deli Tavern")
    db_session.add(customer)
    db_session.flush()

    # Product 1: SKU 7843
    prod_turkey = Product(
        company_id=company.id,
        sku="7843",
        description="Γαλοπούλα Καπνιστή 1kg",
        unit="piece",
        active=True
    )
    # Product 2: SKU 100
    prod_salami = Product(
        company_id=company.id,
        sku="100",
        description="Σαλάμι Μπύρας 300g",
        unit="piece",
        active=True
    )
    db_session.add_all([prod_turkey, prod_salami])
    db_session.flush()

    # Store Customer Alias: "κοκκινο" -> SKU 7843, confirmed_count = 8
    alias = CustomerProductAlias(
        customer_id=customer.id,
        product_id=prod_turkey.id,
        original_phrase="κοκκινο",
        normalized_phrase="κοκκινο",
        confirmed_count=8,
        active=True
    )
    db_session.add(alias)
    db_session.commit()

    return {
        "company": company,
        "customer": customer,
        "prod_turkey": prod_turkey,
        "prod_salami": prod_salami,
    }


def test_e2e_milestone3_scenario_18(client: TestClient, db_session):
    """
    Exact Definition of Done scenario from prompt:
    Create Company
    ↓
    Create Customer
    ↓
    Create Product: SKU 7843, Γαλοπούλα Καπνιστή 1kg
    ↓
    Store Customer Alias: 'κοκκινο' -> SKU 7843, confirmed_count = 8
    ↓
    Parse: '10 κοκκινα'
    ↓
    Matching Engine
    ↓
    Best Match: SKU 7843
    ↓
    Confidence: high (0.97)
    ↓
    Decision: auto_accept
    """
    data = setup_milestone3_api_data(db_session)

    response = client.post(
        "/api/v1/orders/match",
        json={
            "company_id": data["company"].id,
            "customer_id": data["customer"].id,
            "text": "10 κοκκινα",
            "source_type": "plain_text"
        }
    )

    assert response.status_code == 200
    res_json = response.json()
    assert res_json["company_id"] == data["company"].id
    assert res_json["customer_id"] == data["customer"].id
    assert res_json["total_lines"] == 1
    assert res_json["auto_accepted_count"] == 1
    assert res_json["needs_review_count"] == 0
    assert res_json["unresolved_count"] == 0

    line = res_json["lines"][0]
    assert line["quantity"] == 10.0
    assert line["product_phrase"] == "κοκκινα"
    assert line["best_match"] is not None
    assert line["best_match"]["sku"] == "7843"
    assert line["best_match"]["product_id"] == data["prod_turkey"].id
    assert line["confidence"]["score"] == 0.97
    assert line["confidence"]["decision"] == "auto_accept"
    assert any("Customer alias 'κοκκινο' matched" in r for r in line["confidence"]["reasons"])
    assert any("Confirmed 8 previous times" in r for r in line["confidence"]["reasons"])


def test_fuzzy_scenario_needs_review_or_unresolved(client: TestClient, db_session):
    """
    Second prompt scenario:
    Unknown/fuzzy phrase -> Fuzzy candidates -> low/medium confidence -> needs_review or unresolved
    """
    data = setup_milestone3_api_data(db_session)

    response = client.post(
        "/api/v1/orders/match",
        json={
            "company_id": data["company"].id,
            "customer_id": data["customer"].id,
            "text": "2 γαλοπουλα καπν",
            "source_type": "plain_text"
        }
    )

    assert response.status_code == 200
    res_json = response.json()
    assert res_json["total_lines"] == 1
    line = res_json["lines"][0]
    assert line["best_match"] is not None
    assert line["best_match"]["sku"] == "7843"
    assert line["confidence"]["decision"] in ["needs_review", "unresolved"]


def test_api_confirm_match_endpoint(client: TestClient, db_session):
    data = setup_milestone3_api_data(db_session)
    cust_id = data["customer"].id
    prod_id = data["prod_salami"].id

    # 1. First confirm
    payload = {
        "customer_id": cust_id,
        "product_id": prod_id,
        "original_phrase": "μπυρας"
    }
    resp1 = client.post("/api/v1/orders/lines/confirm", json=payload)
    assert resp1.status_code == 200
    res1 = resp1.json()
    assert res1["status"] == "confirmed"
    assert res1["confirmed_count"] == 1

    # A nonexistent nested path must not fall back to standalone alias mutation.
    invalid = client.post("/api/v1/orders/123/lines/1/confirm", json=payload)
    assert invalid.status_code == 400

    # 2. Second standalone confirm
    resp2 = client.post("/api/v1/orders/lines/confirm", json=payload)
    assert resp2.status_code == 200
    res2 = resp2.json()
    assert res2["confirmed_count"] == 2


def test_api_correct_match_endpoint(client: TestClient, db_session):
    data = setup_milestone3_api_data(db_session)
    cust_id = data["customer"].id
    wrong_id = data["prod_salami"].id
    correct_id = data["prod_turkey"].id

    payload = {
        "customer_id": cust_id,
        "suggested_product_id": wrong_id,
        "correct_product_id": correct_id,
        "original_phrase": "καπνιστη",
        "notes": "Wrong recommendation corrected to turkey"
    }

    resp = client.post("/api/v1/orders/lines/correct", json=payload)
    assert resp.status_code == 200
    res = resp.json()
    assert res["status"] == "corrected"
    assert res["correction_id"] > 0
    assert res["suggested_product_id"] == wrong_id
    assert res["correct_product_id"] == correct_id
    assert res["corrected_count"] == 1


def test_api_correct_match_with_order_line_reference_and_validation(client: TestClient, db_session):
    data = setup_milestone3_api_data(db_session)
    comp_id = data["company"].id
    cust_id = data["customer"].id
    wrong_id = data["prod_salami"].id
    correct_id = data["prod_turkey"].id

    order = Order(
        company_id=comp_id,
        customer_id=cust_id,
        order_number="ORD-API-AUDIT-1",
        raw_input="1 καπνιστη"
    )
    db_session.add(order)
    db_session.flush()

    line = OrderLine(
        order_id=order.id,
        line_number=1,
        original_text="1 καπνιστη",
        product_phrase="καπνιστη",
        requested_quantity=1.0,
        requested_unit="piece"
    )
    db_session.add(line)
    db_session.commit()

    # 1. Success case using nested path parameters
    payload = {
        "customer_id": cust_id,
        "suggested_product_id": wrong_id,
        "correct_product_id": correct_id,
        "original_phrase": "καπνιστη",
        "notes": "Verified line correction"
    }
    resp = client.post(f"/api/v1/orders/{order.id}/lines/{line.id}/correct", json=payload)
    assert resp.status_code == 200
    res = resp.json()
    assert res["status"] == "corrected"
    assert res["order_id"] == order.id
    assert res["order_line_id"] == line.id

    # 2. Mismatched order_id and line_id returns 400 Bad Request
    resp_mismatch = client.post(f"/api/v1/orders/{order.id + 999}/lines/{line.id}/correct", json=payload)
    assert resp_mismatch.status_code == 400
    assert "does not belong to order" in resp_mismatch.json()["detail"] or "does not exist" in resp_mismatch.json()["detail"]

    # 3. Foreign company suggested_product_id returns 400 Bad Request
    other_comp = Company(name="Another Co")
    db_session.add(other_comp)
    db_session.flush()
    foreign_prod = Product(company_id=other_comp.id, sku="FOREIGN-99", description="Foreign")
    db_session.add(foreign_prod)
    db_session.commit()

    payload_foreign = {
        "customer_id": cust_id,
        "suggested_product_id": foreign_prod.id,
        "correct_product_id": correct_id,
        "original_phrase": "καπνιστη"
    }
    resp_foreign = client.post("/api/v1/orders/lines/correct", json=payload_foreign)
    assert resp_foreign.status_code == 400
    assert "belongs to company" in resp_foreign.json()["detail"]
