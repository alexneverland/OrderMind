import pytest


def test_milestone2_definition_of_done_api_flow(client):
    """
    Milestone 2 Definition of Done:
    Existing Company -> Existing Customer -> POST plain-text order -> PlainTextAdapter ->
    Normalized input -> MockAIProvider -> Validated NormalizedOrder -> API response with extracted order lines
    """
    # 1. Create Company
    comp_res = client.post("/api/v1/companies", json={"name": "Hellas Wholesale S.A.", "tax_id": "112233445"})
    assert comp_res.status_code == 201
    comp_id = comp_res.json()["id"]

    # 2. Create Customer
    cust_res = client.post("/api/v1/customers", json={
        "company_id": comp_id,
        "customer_code": "CUST-9901",
        "customer_name": "Taverna O Kostas",
        "phone": "2109876543"
    })
    assert cust_res.status_code == 201
    cust_id = cust_res.json()["id"]

    # 3. Post plain-text order to /api/v1/orders/parse
    raw_order_text = "3 κούτες ζαμπόν 500 και 5 τεμάχια μπέικον"
    parse_payload = {
        "company_id": comp_id,
        "customer_id": cust_id,
        "source_type": "plain_text",
        "text": raw_order_text
    }

    response = client.post("/api/v1/orders/parse", json=parse_payload)
    assert response.status_code == 200
    data = response.json()

    # 4. Verify canonical structure
    assert data["company_id"] == comp_id
    assert data["customer_id"] == cust_id
    assert data["source_type"] == "plain_text"
    assert data["raw_input"] == raw_order_text
    assert data["total_items"] == 2
    assert len(data["items"]) == 2

    # Line 1: 3 κούτες ζαμπόν 500
    line1 = data["items"][0]
    assert line1["line_number"] == 1
    assert line1["quantity"] == 3.0
    assert line1["unit"] == "case"
    assert line1["product_phrase"] == "ζαμπόν 500"

    # Line 2: 5 τεμάχια μπέικον
    line2 = data["items"][1]
    assert line2["line_number"] == 2
    assert line2["quantity"] == 5.0
    assert line2["unit"] == "piece"
    assert line2["product_phrase"] == "μπέικον"


def test_api_parse_order_validation_errors(client):
    """Test API error handling for invalid company, customer, or empty text."""
    # 1. Non-existent company
    res1 = client.post("/api/v1/orders/parse", json={
        "company_id": 99999,
        "customer_id": 1,
        "source_type": "plain_text",
        "text": "3 κούτες ζαμπόν"
    })
    assert res1.status_code == 400
    assert "Company with id 99999 not found" in res1.json()["detail"]

    # 2. Empty text
    res2 = client.post("/api/v1/orders/parse", json={
        "company_id": 1,
        "customer_id": 1,
        "source_type": "plain_text",
        "text": ""
    })
    assert res2.status_code == 422  # Pydantic validation error for min_length=1
