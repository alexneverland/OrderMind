import os
import json
import pytest


def test_milestone1_definition_of_done_flow(client, fixtures_dir):
    """
    End-to-End Definition of Done flow:
    1. Create Company
    2. Upload customers.xlsx -> Preview columns -> Import customers
    3. Upload products.xlsx -> Preview columns -> Import products
    4. Upload packaging.xlsx -> Preview columns -> Import packaging
    5. Read imported customers & products via API
    """
    # 1. Create Company
    comp_res = client.post("/api/v1/companies", json={"name": "Αφοί Παπαδόπουλοι Α.Ε.", "tax_id": "098765432"})
    assert comp_res.status_code == 201
    comp_data = comp_res.json()
    company_id = comp_data["id"]
    assert comp_data["name"] == "Αφοί Παπαδόπουλοι Α.Ε."

    # 2. Preview customers.xlsx
    customers_file_path = os.path.join(fixtures_dir, "sample_customers.xlsx")
    with open(customers_file_path, "rb") as f:
        prev_res = client.post(
            "/api/v1/imports/preview",
            files={"file": ("sample_customers.xlsx", f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            data={"entity_type": "customers"}
        )
    assert prev_res.status_code == 200
    preview_data = prev_res.json()
    assert "ΚΩΔΙΚΟΣ_ΠΕΛΑΤΗ" in preview_data["available_columns"]
    assert preview_data["suggested_mapping"]["customer_code"] == "ΚΩΔΙΚΟΣ_ΠΕΛΑΤΗ"

    # Import customers with the mapped columns
    customer_mapping = {
        "customer_code": "ΚΩΔΙΚΟΣ_ΠΕΛΑΤΗ",
        "customer_name": "ΕΠΩΝΥΜΙΑ_ΠΕΛΑΤΗ",
        "email": "EMAIL",
        "phone": "ΤΗΛΕΦΩΝΟ",
        "active": "ΚΑΤΑΣΤΑΣΗ"
    }
    with open(customers_file_path, "rb") as f:
        imp_cust_res = client.post(
            "/api/v1/imports/customers",
            files={"file": ("sample_customers.xlsx", f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            data={
                "company_id": company_id,
                "mapping": json.dumps(customer_mapping)
            }
        )
    assert imp_cust_res.status_code == 200
    cust_summary = imp_cust_res.json()
    assert cust_summary["imported"] == 4
    assert cust_summary["errors"] == 0

    # 3. Preview & Import products.xlsx
    products_file_path = os.path.join(fixtures_dir, "sample_products.xlsx")
    with open(products_file_path, "rb") as f:
        prev_prod_res = client.post(
            "/api/v1/imports/preview",
            files={"file": ("sample_products.xlsx", f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            data={"entity_type": "products"}
        )
    assert prev_prod_res.status_code == 200
    prod_preview = prev_prod_res.json()
    assert prod_preview["suggested_mapping"]["sku"] == "ΚΩΔΙΚΟΣ_ΕΙΔΟΥΣ"

    product_mapping = {
        "sku": "ΚΩΔΙΚΟΣ_ΕΙΔΟΥΣ",
        "description": "ΠΕΡΙΓΡΑΦΗ",
        "barcode": "BARCODE",
        "unit": "ΜΟΝΑΔΑ_ΜΕΤΡΗΣΗΣ",
        "active": "ΕΝΕΡΓΟ"
    }
    with open(products_file_path, "rb") as f:
        imp_prod_res = client.post(
            "/api/v1/imports/products",
            files={"file": ("sample_products.xlsx", f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            data={
                "company_id": company_id,
                "mapping": json.dumps(product_mapping)
            }
        )
    assert imp_prod_res.status_code == 200
    prod_summary = imp_prod_res.json()
    assert prod_summary["imported"] == 5
    assert prod_summary["errors"] == 0

    # 4. Preview & Import packaging.xlsx
    packaging_file_path = os.path.join(fixtures_dir, "sample_packaging.xlsx")
    with open(packaging_file_path, "rb") as f:
        prev_pack_res = client.post(
            "/api/v1/imports/preview",
            files={"file": ("sample_packaging.xlsx", f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            data={"entity_type": "packaging"}
        )
    assert prev_pack_res.status_code == 200
    pack_preview = prev_pack_res.json()
    assert "ΚΩΔ_ΕΙΔΟΥΣ" in pack_preview["available_columns"]

    packaging_mapping = {
        "product_sku": "ΚΩΔ_ΕΙΔΟΥΣ",
        "package_type": "ΤΥΠΟΣ_ΣΥΣΚΕΥΑΣΙΑΣ",
        "pieces_per_case": "ΤΕΜ_ΚΙΒΩΤΙΟ",
        "weight": "ΒΑΡΟΣ_KG",
        "unit": "ΜΟΝΑΔΑ",
        "package_code": "ΚΩΔ_ΣΥΣΚΕΥΑΣΙΑΣ",
        "packaging_barcode": "BARCODE_ΚΙΒΩΤΙΟΥ"
    }
    with open(packaging_file_path, "rb") as f:
        imp_pack_res = client.post(
            "/api/v1/imports/packaging",
            files={"file": ("sample_packaging.xlsx", f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            data={
                "company_id": company_id,
                "mapping": json.dumps(packaging_mapping)
            }
        )
    assert imp_pack_res.status_code == 200
    pack_summary = imp_pack_res.json()
    assert pack_summary["imported"] == 4
    assert pack_summary["errors"] == 0

    # 5. Read imported customers from API
    cust_list_res = client.get(f"/api/v1/customers?company_id={company_id}")
    assert cust_list_res.status_code == 200
    customers = cust_list_res.json()
    assert len(customers) == 4
    cust_codes = [c["customer_code"] for c in customers]
    assert "CUST-4531" in cust_codes
    assert "CUST-1022" in cust_codes

    # 6. Read imported products from API (and verify attached packaging)
    prod_list_res = client.get(f"/api/v1/products?company_id={company_id}")
    assert prod_list_res.status_code == 200
    products = prod_list_res.json()
    assert len(products) == 5
    sku_map = {p["sku"]: p for p in products}
    assert "SKU-7843" in sku_map
    sku_7843 = sku_map["SKU-7843"]
    assert len(sku_7843["packagings"]) == 1
    assert sku_7843["packagings"][0]["package_code"] == "BOX-7843-10"
    assert sku_7843["packagings"][0]["pieces_per_case"] == 10.0


def test_api_manual_creation_and_duplicate_rejection(client):
    """Test manual creation of companies, customers, and products including duplicate error handling."""
    # 1. Health check
    health_res = client.get("/health")
    assert health_res.status_code == 200
    assert health_res.json()["status"] == "ok"

    # 2. Create Company
    comp_res = client.post("/api/v1/companies", json={"name": "Beta Wholesale", "tax_id": "123456789"})
    assert comp_res.status_code == 201
    comp_id = comp_res.json()["id"]

    # 3. List Companies
    list_res = client.get("/api/v1/companies")
    assert list_res.status_code == 200
    assert any(c["id"] == comp_id for c in list_res.json())

    # 4. Create Customer
    cust_res = client.post("/api/v1/customers", json={
        "company_id": comp_id,
        "customer_code": "CUST-MANUAL-1",
        "customer_name": "Manual Customer S.A.",
        "email": "manual@test.local"
    })
    assert cust_res.status_code == 201

    # 5. Duplicate customer in same company rejected with 400
    dup_cust_res = client.post("/api/v1/customers", json={
        "company_id": comp_id,
        "customer_code": "CUST-MANUAL-1",
        "customer_name": "Another Name"
    })
    assert dup_cust_res.status_code == 400

    # 6. Create Product
    prod_res = client.post("/api/v1/products", json={
        "company_id": comp_id,
        "sku": "SKU-MANUAL-1",
        "description": "Manual Product Description",
        "unit": "kg"
    })
    assert prod_res.status_code == 201

    # 7. Duplicate SKU in same company rejected with 400
    dup_prod_res = client.post("/api/v1/products", json={
        "company_id": comp_id,
        "sku": "SKU-MANUAL-1",
        "description": "Second Product Description"
    })
    assert dup_prod_res.status_code == 400

