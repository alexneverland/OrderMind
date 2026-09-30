"""Disposable file/DB checks for archive, delimiter and concurrent imports."""
import io
import zipfile
from threading import Event, Thread, current_thread

import openpyxl
import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from backend.app.core.database import Base, enable_sqlite_wal
from backend.app.core.office_archive import validate_office_archive, OfficeArchiveError
from backend.app.models.company import Company
from backend.app.models.customer import Customer
from backend.app.models.product import Product
from backend.app.models.export import ExportProfile
from backend.app.schemas.export import ExportProfileCreate, ExportProfileUpdate
from backend.app.services.master_data_service import MasterDataService
from backend.app.services.export_profile_service import ExportProfileService, ExportProfileValidationError
from backend.app.services.export_engine import ExportEngine, OrderExportError


def workbook(headers, values):
    wb = openpyxl.Workbook()
    wb.active.append(headers); wb.active.append(values)
    output = io.BytesIO(); wb.save(output)
    return output.getvalue()


@pytest.mark.parametrize("value", ["", ";;", "\t\t", ":", "^"])
def test_delimiters_rejected_before_create_and_update(value):
    with pytest.raises(ValidationError):
        ExportProfileCreate(company_id=1, name="Synthetic", delimiter=value)
    with pytest.raises(ValidationError):
        ExportProfileUpdate(delimiter=value)


def test_legacy_invalid_delimiter_cannot_switch_to_csv_or_export(db_session):
    from backend.app.models.order import Order
    from backend.app.models.customer import Customer
    from backend.app.models.export import ExportFieldMapping
    company = Company(name="Synthetic"); db_session.add(company); db_session.flush()
    customer = Customer(company_id=company.id, customer_code="C", customer_name="Buyer")
    profile = ExportProfile(company_id=company.id, name="Legacy", format="xlsx", delimiter=";;")
    db_session.add_all([customer, profile]); db_session.flush()
    db_session.add(ExportFieldMapping(export_profile_id=profile.id, column_order=1,
        output_column_name="Code", mapping_type="constant", constant_value="Synthetic"))
    db_session.commit()
    with pytest.raises(ExportProfileValidationError, match="delimiter"):
        ExportProfileService.update_profile(db_session, profile.id, ExportProfileUpdate(format="csv"))
    db_session.rollback()
    profile.format = "csv"  # simulate an already stored legacy invalid profile
    order = Order(company_id=company.id, customer_id=customer.id, order_number="SEC-1", status="approved",
                  approved_snapshot={"lines": []}, raw_input="Synthetic")
    db_session.add(order); db_session.commit()
    with pytest.raises(OrderExportError, match="invalid delimiter"):
        ExportEngine.export_order(db_session, order.id, profile.id)


def oversized_archive():
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        with archive.open("word/document.xml", "w") as member:
            for _ in range(31):
                member.write(b"x" * (1024 * 1024))
    return output.getvalue()


@pytest.mark.parametrize("extension", ["docx", "xlsx"])
def test_expanded_archive_rejected_before_order_parser(client, monkeypatch, extension):
    def forbidden_parser(*args, **kwargs):
        pytest.fail("Parser must not be entered for an oversized archive")
    monkeypatch.setattr("docx.Document", forbidden_parser)
    monkeypatch.setattr("openpyxl.load_workbook", forbidden_parser)
    content = oversized_archive()
    assert len(content) < 10 * 1024 * 1024
    response = client.post("/api/v1/orders/file-preview", files={"file": (f"order.{extension}", content)})
    assert response.status_code == 400
    assert "expanded-size" in response.json()["detail"]


@pytest.mark.parametrize("prefix", [b"", b"non-zip-prefix"])
def test_master_preview_cannot_retry_oversized_archive_with_another_engine(client, monkeypatch, prefix):
    def forbidden_parser(*args, **kwargs):
        pytest.fail("DataFrame parser must not be entered for an oversized archive")
    monkeypatch.setattr("pandas.read_excel", forbidden_parser)
    response = client.post("/api/v1/imports/preview", data={"entity_type": "products"},
                           files={"file": ("products.xlsx", prefix + oversized_archive())})
    assert response.status_code == 400
    assert "expanded-size" in response.json()["detail"]


def test_invalid_archive_and_entry_limit():
    with pytest.raises(OfficeArchiveError):
        validate_office_archive(b"PKinvalid")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for index in range(1001):
            archive.writestr(str(index), b"")
    with pytest.raises(OfficeArchiveError, match="too many"):
        validate_office_archive(output.getvalue())


@pytest.mark.parametrize("entity", ["customers", "products"])
def test_overlapping_imports_serialize_before_lookup(tmp_path, entity):
    engine = create_engine(f"sqlite:///{tmp_path / 'imports.sqlite'}", poolclass=NullPool,
                           connect_args={"check_same_thread": False, "timeout": 5})
    Base.metadata.create_all(engine); enable_sqlite_wal(engine)
    with Session(engine) as setup:
        company = Company(name="Synthetic concurrent tenant"); setup.add(company); setup.commit()
        company_id = company.id
    headers = ["Code", "Name"]
    content = workbook(headers, ["SAME", "Synthetic"])
    mapping = ({"customer_code": "Code", "customer_name": "Name"} if entity == "customers"
               else {"sku": "Code", "description": "Name"})
    first_reserved, second_attempted = Event(), Event()
    results, failures = [], []

    @event.listens_for(engine, "before_cursor_execute")
    def before(connection, cursor, statement, parameters, context, executemany):
        if statement == "BEGIN IMMEDIATE" and current_thread().name == "second-import":
            second_attempted.set()

    @event.listens_for(engine, "after_cursor_execute")
    def after(connection, cursor, statement, parameters, context, executemany):
        if statement == "BEGIN IMMEDIATE" and current_thread().name == "first-import":
            first_reserved.set()
            if not second_attempted.wait(5):
                raise AssertionError("Second importer did not reach lock acquisition")

    def run():
        try:
            with Session(engine) as session:
                # Match the endpoint's company lookup before parsing/import.
                assert session.get(Company, company_id) is not None
                results.append(getattr(MasterDataService, f"import_{entity}")(
                    session, company_id, content, mapping))
        except Exception as exc:
            failures.append(exc)

    first = Thread(target=run, name="first-import")
    second = Thread(target=run, name="second-import")
    try:
        first.start()
        assert first_reserved.wait(5)
        second.start()
        first.join(8); second.join(8)
        assert not first.is_alive() and not second.is_alive()
        assert not failures
        assert sorted((result.imported, result.errors) for result in results) == [(0, 1), (1, 0)]
        with Session(engine) as session:
            model = Customer if entity == "customers" else Product
            assert len(session.execute(select(model)).scalars().all()) == 1
    finally:
        first.join(8)
        if second.ident is not None:
            second.join(8)
        engine.dispose()


@pytest.mark.parametrize("entity", ["customers", "products", "packaging"])
def test_import_integrity_conflict_rolls_back_and_returns_409(client, db_session, monkeypatch, entity):
    company = Company(name="Synthetic conflicts"); db_session.add(company); db_session.commit()
    def conflicting_import(**kwargs):
        db = kwargs["db"]
        db.add_all([Customer(company_id=company.id, customer_code="SAME", customer_name="Synthetic")
                    for _ in range(2)])
        db.flush()  # actual unique constraint violation, not a fabricated exception
    monkeypatch.setattr(MasterDataService, f"import_{entity}", conflicting_import)
    response = client.post(f"/api/v1/imports/{entity}", data={"company_id": company.id, "mapping": "{}"},
                           files={"file": ("synthetic.xlsx", b"synthetic")})
    assert response.status_code == 409
    assert db_session.execute(select(Customer)).scalars().all() == []
