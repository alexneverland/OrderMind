"""Exercise the shipped migrations against a populated SQLite database."""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def _alembic(database: Path, *args: str) -> None:
    env = os.environ.copy()
    env["DATABASE_URL"] = "sqlite:///" + database.as_posix()
    subprocess.run([sys.executable, "-m", "alembic", *args], cwd=ROOT, env=env,
                   check=True, capture_output=True, text=True)


def test_fresh_sqlite_database_reaches_model_head(tmp_path: Path):
    database = tmp_path / "fresh.sqlite"
    _alembic(database, "upgrade", "head")
    _alembic(database, "check")
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("b8c9d20015",)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        connection.execute("INSERT INTO companies (id,name) VALUES (1,'A'),(2,'B')")
        connection.execute("INSERT INTO products (id,company_id,sku,description,unit,active) VALUES (1,1,'SKU-A','Product A','piece',1)")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO company_product_unit_preferences (company_id,product_id,unit) VALUES (2,1,'kg')")
        connection.rollback()
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("""INSERT INTO company_rules
                (company_id,rule_type,fingerprint,enabled,product_id,configuration)
                VALUES (2,'quantity_bonus','foreign',1,1,'{}')""")


def test_populated_previous_head_upgrades_with_neutral_pallet_policy(tmp_path: Path):
    database = tmp_path / "previous.sqlite"
    _alembic(database, "upgrade", "a7b9c20014")
    with sqlite3.connect(database) as connection:
        connection.execute("INSERT INTO companies (id,name) VALUES (1,'Existing')")
        connection.execute("INSERT INTO products (id,company_id,sku,description,unit,active) VALUES (1,1,'SKU','Product','piece',1)")
        connection.execute("INSERT INTO export_profiles (id,company_id,name,format,include_header,encoding) VALUES (1,1,'Sheet','order_sheet',0,'utf-8')")
    _alembic(database, "upgrade", "head")
    _alembic(database, "check")
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT palletization FROM export_profiles WHERE id=1").fetchone() == ('{"enabled": false}',)
        assert connection.execute("SELECT kg_per_piece FROM products WHERE id=1").fetchone() == (None,)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)


def test_existing_companies_and_order_sheets_get_explicit_compatibility_policy(tmp_path: Path):
    database = tmp_path / "existing.sqlite"
    _alembic(database, "upgrade", "e5a7b9c20012")
    with sqlite3.connect(database) as connection:
        connection.execute("INSERT INTO companies (id,name) VALUES (1,'Existing')")
        connection.execute("INSERT INTO export_profiles (id,company_id,name,format,include_header,encoding) VALUES (1,1,'Existing sheet','order_sheet',1,'utf-8')")
    _alembic(database, "upgrade", "head")
    with sqlite3.connect(database) as connection:
        assert connection.execute("""SELECT bonus_enabled,bonus_expression_mode,unitless_order_behavior,
            allow_packaging_conversion,learn_unit_preferences FROM company_business_settings WHERE company_id=1""").fetchone() == (
                1, "paid_plus_bonus", "learned_product_preference", 1, 1,
            )
        assert connection.execute("""SELECT include_header,bonus_separate_row,bonus_marker,quantity_output_unit,
            convert_case_using_pieces_per_case FROM export_profiles WHERE id=1""").fetchone() == (
                0, 1, "Α", "piece", 1,
            )
        connection.execute("INSERT INTO companies (id,name) VALUES (2,'New')")
        assert connection.execute("SELECT * FROM company_business_settings WHERE company_id=2").fetchone() is None
        connection.execute("PRAGMA foreign_keys=ON")
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_tenant_migration_preserves_rows_and_enforces_company_links(tmp_path: Path):
    database = tmp_path / "orders.sqlite"
    _alembic(database, "upgrade", "b20e1773d5fc")
    with sqlite3.connect(database) as connection:
        connection.execute("INSERT INTO companies (id,name) VALUES (1,'A'),(2,'B')")
        connection.execute("INSERT INTO customers (id,company_id,customer_code,customer_name,active) VALUES (1,1,'A','Buyer A',1)")
        connection.execute("INSERT INTO products (id,company_id,sku,description,unit,active) VALUES (1,1,'SKU-A','Product A','piece',1),(2,2,'SKU-B','Product B','piece',1)")
        connection.execute("INSERT INTO export_profiles (id,company_id,name,format,include_header,encoding) VALUES (1,1,'Profile A','json',1,'utf-8')")
        connection.execute("INSERT INTO orders (id,company_id,customer_id,order_number,version,status,overall_confidence,raw_input) VALUES (1,1,1,'A-1',1,'pending_review',0,'one')")
        connection.execute("INSERT INTO packagings (id,product_id,package_type,pieces_per_case,unit) VALUES (1,1,'case',12,'case')")
        connection.execute("INSERT INTO order_lines (id,order_id,line_number,original_text,product_phrase,requested_quantity,requested_unit,unit_explicit,matched_product_id,matched_packaging_id,confidence_score,confidence_reasons,status) VALUES (1,1,1,'one','one',1,'case',1,1,1,1,'[]','auto_accepted')")
        connection.execute("INSERT INTO customer_product_aliases (id,customer_id,product_id,original_phrase,normalized_phrase,confirmed_count,corrected_count,active) VALUES (1,1,1,'one','one',1,0,1)")
        connection.execute("INSERT INTO match_candidates (id,order_line_id,product_id,rank,match_type,score,explanation) VALUES (1,1,1,1,'exact_sku',1,'exact')")
        connection.execute("INSERT INTO human_corrections (id,customer_id,order_id,order_line_id,original_phrase,correct_product_id) VALUES (1,1,1,1,'one',1)")
        connection.execute("INSERT INTO export_records (id,order_id,export_profile_id,format,filename) VALUES (1,1,1,'json','a.json')")

    _alembic(database, "upgrade", "head")
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        for table in ("packagings", "order_lines", "customer_product_aliases", "match_candidates", "human_corrections", "export_records"):
            assert connection.execute(f"SELECT company_id FROM {table} WHERE id=1").fetchone() == (1,)
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE order_lines SET matched_product_id=2 WHERE id=1")
        connection.rollback()

    _alembic(database, "downgrade", "b20e1773d5fc")
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT matched_product_id FROM order_lines WHERE id=1").fetchone() == (1,)
