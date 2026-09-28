"""One-time upgrade of an unversioned pre-hardening (1cd7f52) database.

Run ``python -m backend.alembic.upgrade_legacy`` with DATABASE_URL configured.
SQLite files are backed up before schema changes. Approved/exported legacy orders
cannot be migrated automatically because their historical business values were
never snapshotted; this command refuses those databases.
"""

from datetime import datetime, timezone
from pathlib import Path
import sqlite3

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.engine import make_url

from backend.app.config import settings


ROOT = Path(__file__).resolve().parents[2]
FK_NAMES = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}


def _legacy_fk_name(connection, table: str, column: str, fallback: str) -> str:
    for fk in sa.inspect(connection).get_foreign_keys(table):
        if fk["constrained_columns"] == [column]:
            return fk["name"] or fallback
    raise RuntimeError(f"Legacy foreign key {table}.{column} was not found")


def _preflight(connection) -> None:
    inspector = sa.inspect(connection)
    tables = set(inspector.get_table_names())
    if "alembic_version" in tables:
        raise RuntimeError("Database is already Alembic-managed; run alembic upgrade head")
    required = {"companies", "customers", "products", "product_aliases", "orders", "order_lines"}
    if not required.issubset(tables):
        raise RuntimeError("Database does not match the pre-hardening OrderMind schema")
    order_columns = {column["name"] for column in inspector.get_columns("orders")}
    if "version" in order_columns or "approved_snapshot" in order_columns:
        raise RuntimeError("Database is not the supported 1cd7f52 legacy schema")
    if connection.exec_driver_sql("SELECT COUNT(*) FROM orders WHERE status IN ('approved','exported')").scalar():
        raise RuntimeError("Legacy approved/exported orders have no historical snapshot; manual data review is required")
    checks = (
        "SELECT COUNT(*) FROM orders o JOIN customers c ON c.id=o.customer_id WHERE o.company_id<>c.company_id",
        "SELECT COUNT(*) FROM product_aliases a JOIN products p ON p.id=a.product_id WHERE a.company_id<>p.company_id",
    )
    if any(connection.exec_driver_sql(query).scalar() for query in checks):
        raise RuntimeError("Legacy database contains cross-company links; correct them before migration")


def _backup_sqlite() -> Path:
    url = make_url(settings.DATABASE_URL)
    if not url.database or url.database == ":memory:":
        raise RuntimeError("Legacy migration requires a persistent SQLite file")
    source = Path(url.database).resolve()
    if not source.is_file():
        raise RuntimeError(f"SQLite database does not exist: {source}")
    suffix = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = source.with_name(source.name + f".pre-alembic-{suffix}.bak")
    with sqlite3.connect(source) as original, sqlite3.connect(backup) as saved:
        original.backup(saved)
    return backup


def upgrade_legacy() -> Path:
    if make_url(settings.DATABASE_URL).get_backend_name() != "sqlite":
        raise RuntimeError("Legacy upgrade supports SQLite databases only")
    engine = sa.create_engine(settings.DATABASE_URL)
    with engine.connect() as connection:
        _preflight(connection)
    engine.dispose()

    backup = _backup_sqlite()
    engine = sa.create_engine(settings.DATABASE_URL)
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        if connection.exec_driver_sql("PRAGMA foreign_keys").scalar() != 0:
            raise RuntimeError("Could not disable SQLite foreign keys for legacy table rebuild")
        operations = Operations(MigrationContext.configure(connection))

        with operations.batch_alter_table("customers", recreate="auto") as batch:
            batch.create_unique_constraint("uq_customers_id_company_id", ["id", "company_id"])
        with operations.batch_alter_table("products", recreate="auto") as batch:
            batch.create_unique_constraint("uq_products_id_company_id", ["id", "company_id"])
        product_alias_fk = _legacy_fk_name(
            connection, "product_aliases", "product_id", "fk_product_aliases_product_id_products"
        )
        with operations.batch_alter_table("product_aliases", recreate="auto", naming_convention=FK_NAMES) as batch:
            batch.drop_constraint(product_alias_fk, type_="foreignkey")
            batch.create_foreign_key("fk_product_alias_product_company", "products", ["product_id", "company_id"], ["id", "company_id"], ondelete="CASCADE")
        order_customer_fk = _legacy_fk_name(
            connection, "orders", "customer_id", "fk_orders_customer_id_customers"
        )
        with operations.batch_alter_table("orders", recreate="auto", naming_convention=FK_NAMES) as batch:
            batch.drop_constraint(order_customer_fk, type_="foreignkey")
            batch.add_column(sa.Column("idempotency_key", sa.String(100), nullable=True))
            batch.add_column(sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
            batch.add_column(sa.Column("approved_snapshot", sa.JSON(), nullable=True))
            batch.create_unique_constraint("uq_company_idempotency_key", ["company_id", "idempotency_key"])
            batch.create_foreign_key("fk_order_customer_company", "customers", ["customer_id", "company_id"], ["id", "company_id"], ondelete="RESTRICT")
        operations.create_index("ix_orders_idempotency_key", "orders", ["idempotency_key"])

        metadata = sa.MetaData()
        sa.Table("orders", metadata, autoload_with=connection)
        sa.Table("export_profiles", metadata, autoload_with=connection)
        export_records = sa.Table(
            "export_records", metadata,
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
            sa.Column("export_profile_id", sa.Integer(), sa.ForeignKey("export_profiles.id", ondelete="SET NULL"), nullable=True),
            sa.Column("format", sa.String(50), nullable=False),
            sa.Column("filename", sa.String(255), nullable=False),
            sa.Column("content_hash", sa.String(64), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        export_records.create(connection)
        for field in ("id", "order_id", "export_profile_id"):
            sa.Index(f"ix_export_records_{field}", export_records.c[field]).create(connection)

        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        violations = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError(f"Legacy migration created foreign-key violations: {violations[:3]}")
        connection.commit()
    engine.dispose()

    config = Config(str(ROOT / "alembic.ini"))
    command.stamp(config, "73e685e9111b")
    command.upgrade(config, "head")
    return backup


if __name__ == "__main__":
    saved_backup = upgrade_legacy()
    print("Legacy schema upgraded to Alembic head.")
    print(f"SQLite backup: {saved_backup}")
