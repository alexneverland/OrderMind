"""Packaging Excel imports must be repeatable without changing matching data."""

import io
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pandas as pd
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.core.database import Base
from backend.app.models import Company, Packaging, Product
from backend.app.services.master_data_service import MasterDataService


MAPPING = {
    "product_sku": "SKU",
    "package_type": "Type",
    "pieces_per_case": "Pieces",
    "unit": "Unit",
    "package_code": "Code",
    "packaging_barcode": "Barcode",
}


def workbook(**changes) -> bytes:
    row = {
        "SKU": "SKU-1", "Type": "case", "Pieces": 12, "Unit": "piece",
        "Code": "BOX-1", "Barcode": "123456789",
    }
    row.update(changes)
    output = io.BytesIO()
    pd.DataFrame([row]).to_excel(output, index=False)
    return output.getvalue()


def upload(client, company_id: int, content: bytes):
    return client.post(
        "/api/v1/imports/packaging",
        files={"file": ("packaging.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"company_id": company_id, "mapping": json.dumps(MAPPING)},
    )


def test_repeat_import_skips_identical_rows_and_reports_changes(client, db_session):
    company_id = client.post("/api/v1/companies", json={"name": "One"}).json()["id"]
    client.post("/api/v1/products", json={
        "company_id": company_id, "sku": "SKU-1", "description": "Product One", "unit": "piece",
    })

    first = upload(client, company_id, workbook())
    assert first.status_code == 200
    assert (first.json()["imported"], first.json()["skipped"], first.json()["errors"]) == (1, 0, 0)

    repeated = upload(client, company_id, workbook())
    assert repeated.status_code == 200
    assert (repeated.json()["imported"], repeated.json()["skipped"], repeated.json()["errors"]) == (0, 1, 0)

    changed = upload(client, company_id, workbook(Pieces=24))
    assert changed.status_code == 200
    assert (changed.json()["imported"], changed.json()["skipped"], changed.json()["errors"]) == (0, 0, 1)
    assert changed.json()["error_details"][0]["row_number"] == 2
    rows = db_session.execute(select(Packaging).where(Packaging.company_id == company_id)).scalars().all()
    assert len(rows) == 1
    assert rows[0].pieces_per_case == 12


def test_identifiers_are_company_scoped_and_conflicts_are_not_silently_inserted(client, db_session):
    one = client.post("/api/v1/companies", json={"name": "One"}).json()["id"]
    two = client.post("/api/v1/companies", json={"name": "Two"}).json()["id"]
    for company_id in (one, two):
        for sku in ("SKU-1", "SKU-2"):
            client.post("/api/v1/products", json={
                "company_id": company_id, "sku": sku, "description": sku, "unit": "piece",
            })
    assert upload(client, one, workbook()).json()["imported"] == 1
    assert upload(client, two, workbook()).json()["imported"] == 1
    conflict = upload(client, one, workbook(SKU="SKU-2"))
    assert conflict.json()["errors"] == 1
    assert conflict.json()["imported"] == 0
    assert len(db_session.execute(select(Packaging).where(Packaging.company_id == one)).scalars().all()) == 1
    assert len(db_session.execute(select(Packaging).where(Packaging.company_id == two)).scalars().all()) == 1


def test_unidentified_packaging_reimport_is_idempotent(db_session):
    company = Company(name="One")
    db_session.add(company)
    db_session.flush()
    db_session.add(Product(company_id=company.id, sku="SKU-1", description="Product"))
    db_session.commit()
    content = workbook(Code=None, Barcode=None)
    first = MasterDataService.import_packaging(db_session, company.id, content, MAPPING)
    second = MasterDataService.import_packaging(db_session, company.id, content, MAPPING)
    assert (first.imported, second.skipped, second.errors) == (1, 1, 0)
    changed = MasterDataService.import_packaging(
        db_session, company.id, workbook(Code=None, Barcode=None, Pieces=24), MAPPING,
    )
    assert (changed.imported, changed.errors) == (0, 1)
    assert len(db_session.execute(select(Packaging)).scalars().all()) == 1


def test_concurrent_file_imports_serialize_on_sqlite(tmp_path):
    db_path = tmp_path / "packaging.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False, "timeout": 5})
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        company = Company(name="One")
        session.add(company)
        session.flush()
        company_id = company.id
        session.add(Product(company_id=company_id, sku="SKU-1", description="Product"))
        session.commit()

    barrier = Barrier(2)
    content = workbook()

    def do_import():
        with Session(engine) as session:
            barrier.wait(timeout=5)
            result = MasterDataService.import_packaging(session, company_id, content, MAPPING)
            return result.imported, result.skipped

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: do_import(), range(2)))
        assert sorted(results) == [(0, 1), (1, 0)]
        with Session(engine) as session:
            assert len(session.execute(select(Packaging)).scalars().all()) == 1
    finally:
        engine.dispose()
