"""Exercise the file-backed SQLite behavior used by the API."""

import asyncio
from threading import Event, Thread

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError
from sqlalchemy.pool import NullPool

from backend.app.core.database import Base, SQLITE_BUSY_TIMEOUT_MS, enable_sqlite_wal
from backend.app.models import company, customer, product, memory, order, export  # noqa: F401
from backend.app.models.company import Company
from backend.app.models.customer import Customer
from backend.app.models.product import Product
from backend.app.models.memory import CustomerProductAlias, HumanCorrection
from backend.app.models.order import Order
from backend.app.services.learning_memory_service import LearningMemoryService
from backend.app.main import sqlite_operational_error_handler


def _file_engine(tmp_path):
    database = tmp_path / "runtime.sqlite"
    return create_engine(f"sqlite:///{database.as_posix()}", poolclass=NullPool)


def test_every_file_connection_has_foreign_keys_and_bounded_busy_wait(tmp_path):
    engine = _file_engine(tmp_path)
    try:
        for _ in range(2):
            with engine.connect() as connection:
                assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
                assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar_one() == SQLITE_BUSY_TIMEOUT_MS
    finally:
        engine.dispose()


def test_wal_allows_reader_and_waiting_short_writer(tmp_path):
    engine = _file_engine(tmp_path)
    try:
        assert enable_sqlite_wal(engine) == "wal"
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE writes (value INTEGER NOT NULL)")
            connection.exec_driver_sql("INSERT INTO writes VALUES (1)")

        started = Event()
        finished = Event()
        errors = []

        def second_writer():
            try:
                with engine.begin() as connection:
                    started.set()
                    connection.exec_driver_sql("INSERT INTO writes VALUES (3)")
            except Exception as exc:
                errors.append(exc)
            finally:
                finished.set()

        with engine.connect() as first:
            first.exec_driver_sql("BEGIN IMMEDIATE")
            first.exec_driver_sql("INSERT INTO writes VALUES (2)")
            thread = Thread(target=second_writer)
            thread.start()
            try:
                assert started.wait(2)
                assert not finished.wait(0.1)
                with engine.connect() as reader:
                    assert reader.exec_driver_sql("SELECT COUNT(*) FROM writes").scalar_one() == 1
            finally:
                first.commit()
                thread.join(timeout=3)
        assert finished.is_set()
        assert not errors
        with engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA journal_mode").scalar_one() == "wal"
            assert connection.exec_driver_sql("SELECT COUNT(*) FROM writes").scalar_one() == 3
    finally:
        engine.dispose()


def test_persistent_sqlite_lock_returns_retryable_503(tmp_path):
    engine = _file_engine(tmp_path)
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE writes (value INTEGER NOT NULL)")
        with engine.connect() as first, engine.connect() as second:
            first.exec_driver_sql("BEGIN IMMEDIATE")
            second.exec_driver_sql("PRAGMA busy_timeout=1")  # keep this test fast
            with pytest.raises(OperationalError) as failure:
                second.exec_driver_sql("INSERT INTO writes VALUES (1)")
            response = asyncio.run(sqlite_operational_error_handler(None, failure.value))
            assert response.status_code == 503
            assert response.headers["retry-after"] == "1"
            first.rollback()
    finally:
        engine.dispose()


def test_stale_session_correction_increments_alias_counter_atomically(tmp_path):
    engine = _file_engine(tmp_path)
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as setup:
            company = Company(name="A")
            setup.add(company)
            setup.flush()
            customer = Customer(company_id=company.id, customer_code="C", customer_name="Buyer")
            product = Product(company_id=company.id, sku="P", description="Product")
            setup.add_all([customer, product])
            setup.flush()
            alias = CustomerProductAlias(customer_id=customer.id, product_id=product.id,
                                         original_phrase="one", normalized_phrase="one",
                                         confirmed_count=1, corrected_count=0)
            setup.add(alias)
            setup.commit()
            customer_id, product_id, alias_id = customer.id, product.id, alias.id

        with Session(engine) as first, Session(engine) as second:
            second.get(CustomerProductAlias, alias_id)  # stale identity-map state
            LearningMemoryService.correct_match(first, customer_id, product_id, "one")
            first.commit()
            LearningMemoryService.correct_match(second, customer_id, product_id, "one")
            second.commit()
        with Session(engine) as verify:
            assert verify.get(CustomerProductAlias, alias_id).corrected_count == 2
            assert verify.query(HumanCorrection).count() == 2
    finally:
        engine.dispose()


def test_file_backed_order_version_rejects_stale_writer(tmp_path):
    engine = _file_engine(tmp_path)
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as setup:
            company = Company(name="A")
            setup.add(company)
            setup.flush()
            customer = Customer(company_id=company.id, customer_code="C", customer_name="Buyer")
            setup.add(customer)
            setup.flush()
            order = Order(company_id=company.id, customer_id=customer.id,
                          order_number="ONE", raw_input="one")
            setup.add(order)
            setup.commit()
            order_id = order.id

        with Session(engine) as first, Session(engine) as second:
            first_order = first.get(Order, order_id)
            second_order = second.get(Order, order_id)
            first_order.version += 1
            first_order.status = "pending_review"
            first.commit()
            second_order.version += 1
            second_order.status = "cancelled"
            with pytest.raises(StaleDataError):
                second.commit()
            second.rollback()

        with Session(engine) as verify:
            assert verify.get(Order, order_id).status == "pending_review"
    finally:
        engine.dispose()
