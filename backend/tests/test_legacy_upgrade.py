"""Verify migration from the actual pre-Alembic repository schema."""

import io
import os
import sqlite3
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def _legacy_source(tmp_path: Path) -> Path:
    result = subprocess.run(["git", "archive", "--format=zip", "1cd7f52"], cwd=ROOT,
                            capture_output=True)
    if result.returncode:
        pytest.skip("Pre-Alembic Git revision is unavailable")
    source = tmp_path / "legacy_source"
    with zipfile.ZipFile(io.BytesIO(result.stdout)) as archive:
        archive.extractall(source)
    return source


def _old_database(source: Path, database: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["DATABASE_URL"] = "sqlite:///" + database.as_posix()
    subprocess.run([sys.executable, "-c", "from backend.app.core.database import init_db; init_db()"],
                   cwd=source, env=env, check=True, capture_output=True, text=True)
    return env


def test_pre_alembic_database_upgrades_without_losing_pending_orders(tmp_path: Path):
    source = _legacy_source(tmp_path)
    database = tmp_path / "legacy.sqlite"
    env = _old_database(source, database)
    with sqlite3.connect(database) as connection:
        connection.execute("INSERT INTO companies (id,name) VALUES (1,'Legacy A')")
        connection.execute("INSERT INTO customers (id,company_id,customer_code,customer_name,active) VALUES (1,1,'A','Buyer',1)")
        connection.execute("INSERT INTO products (id,company_id,sku,description,unit,active) VALUES (1,1,'SKU-A','Legacy Product','piece',1)")
        connection.execute("INSERT INTO orders (id,company_id,customer_id,order_number,status,overall_confidence,raw_input) VALUES (1,1,1,'LEG-1','pending_review',0,'one')")

    subprocess.run([sys.executable, "-m", "backend.alembic.upgrade_legacy"],
                   cwd=ROOT, env=env, check=True, capture_output=True, text=True)
    assert list(tmp_path.glob("legacy.sqlite.pre-alembic-*.bak"))
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        assert connection.execute("SELECT order_number,version FROM orders WHERE id=1").fetchone() == ("LEG-1", 1)
        assert connection.execute("SELECT normalized_description FROM products WHERE id=1").fetchone() == ("legacy product",)
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("c547ac2e9811",)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_legacy_upgrade_refuses_orders_without_historical_snapshot(tmp_path: Path):
    source = _legacy_source(tmp_path)
    database = tmp_path / "approved.sqlite"
    env = _old_database(source, database)
    with sqlite3.connect(database) as connection:
        connection.execute("INSERT INTO companies (id,name) VALUES (1,'Legacy A')")
        connection.execute("INSERT INTO customers (id,company_id,customer_code,customer_name,active) VALUES (1,1,'A','Buyer',1)")
        connection.execute("INSERT INTO orders (id,company_id,customer_id,order_number,status,overall_confidence,raw_input) VALUES (1,1,1,'LEG-1','approved',0,'one')")

    result = subprocess.run([sys.executable, "-m", "backend.alembic.upgrade_legacy"],
                            cwd=ROOT, env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert "historical snapshot" in result.stderr
    assert not list(tmp_path.glob("approved.sqlite.pre-alembic-*.bak"))
