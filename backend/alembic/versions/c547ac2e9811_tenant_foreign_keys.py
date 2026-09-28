"""Enforce tenant identity on order, memory, packaging, and export links.

Revision ID: c547ac2e9811
Revises: b20e1773d5fc
"""

from alembic import op
import sqlalchemy as sa

revision = "c547ac2e9811"
down_revision = "b20e1773d5fc"
branch_labels = None
depends_on = None


_CROSS_COMPANY_CHECKS = (
    "SELECT COUNT(*) FROM customer_product_aliases a JOIN customers c ON c.id=a.customer_id JOIN products p ON p.id=a.product_id WHERE c.company_id<>p.company_id",
    "SELECT COUNT(*) FROM order_lines l JOIN orders o ON o.id=l.order_id JOIN products p ON p.id=l.matched_product_id WHERE o.company_id<>p.company_id",
    "SELECT COUNT(*) FROM order_lines l JOIN orders o ON o.id=l.order_id JOIN packagings p ON p.id=l.matched_packaging_id JOIN products x ON x.id=p.product_id WHERE o.company_id<>x.company_id",
    "SELECT COUNT(*) FROM match_candidates m JOIN order_lines l ON l.id=m.order_line_id JOIN orders o ON o.id=l.order_id JOIN products p ON p.id=m.product_id WHERE o.company_id<>p.company_id",
    "SELECT COUNT(*) FROM human_corrections h JOIN customers c ON c.id=h.customer_id JOIN products p ON p.id=h.correct_product_id WHERE c.company_id<>p.company_id",
    "SELECT COUNT(*) FROM human_corrections h JOIN customers c ON c.id=h.customer_id JOIN products p ON p.id=h.suggested_product_id WHERE c.company_id<>p.company_id",
    "SELECT COUNT(*) FROM human_corrections h JOIN customers c ON c.id=h.customer_id JOIN orders o ON o.id=h.order_id WHERE c.company_id<>o.company_id",
    "SELECT COUNT(*) FROM human_corrections h JOIN customers c ON c.id=h.customer_id JOIN order_lines l ON l.id=h.order_line_id JOIN orders o ON o.id=l.order_id WHERE c.company_id<>o.company_id",
    "SELECT COUNT(*) FROM export_records e JOIN orders o ON o.id=e.order_id JOIN export_profiles p ON p.id=e.export_profile_id WHERE o.company_id<>p.company_id",
    "SELECT COUNT(*) FROM orders o JOIN export_profiles p ON p.id=o.last_export_profile_id WHERE o.company_id<>p.company_id",
)


def _add_tenant_column(table: str, parent: str, parent_key: str) -> None:
    op.add_column(table, sa.Column("company_id", sa.Integer(), nullable=True))
    op.execute(sa.text(
        f"UPDATE {table} SET company_id=(SELECT company_id FROM {parent} WHERE {parent}.id={table}.{parent_key})"
    ))


def _tenant_fk(batch, table: str, field: str, parent: str, name: str, ondelete: str = "RESTRICT") -> None:
    batch.create_foreign_key(name, parent, [field, "company_id"], ["id", "company_id"], ondelete=ondelete)


def upgrade() -> None:
    bind = op.get_bind()
    sqlite = bind.dialect.name == "sqlite"
    if sqlite:
        bind.exec_driver_sql("PRAGMA foreign_keys=OFF")
        if bind.exec_driver_sql("PRAGMA foreign_keys").scalar() != 0:
            raise RuntimeError("SQLite foreign keys could not be disabled for tenant migration")

    for query in _CROSS_COMPANY_CHECKS:
        if bind.exec_driver_sql(query).scalar():
            raise RuntimeError("Existing cross-company references must be corrected before tenant migration")
    if bind.exec_driver_sql(
        "SELECT COUNT(*) FROM (SELECT order_id,line_number FROM order_lines GROUP BY order_id,line_number HAVING COUNT(*)>1) duplicate_lines"
    ).scalar():
        raise RuntimeError("Duplicate order line numbers must be corrected before tenant migration")

    with op.batch_alter_table("export_profiles", recreate="auto") as batch:
        batch.create_unique_constraint("uq_export_profiles_id_company_id", ["id", "company_id"])
    with op.batch_alter_table("orders", recreate="auto") as batch:
        batch.create_unique_constraint("uq_orders_id_company_id", ["id", "company_id"])
        _tenant_fk(batch, "orders", "last_export_profile_id", "export_profiles", "fk_order_export_profile_company")

    _add_tenant_column("packagings", "products", "product_id")
    with op.batch_alter_table("packagings", recreate="auto") as batch:
        batch.alter_column("company_id", existing_type=sa.Integer(), nullable=False)
        batch.create_unique_constraint("uq_packagings_id_company_id", ["id", "company_id"])
        _tenant_fk(batch, "packagings", "product_id", "products", "fk_packaging_product_company", "CASCADE")
    op.create_index("ix_packagings_company_id", "packagings", ["company_id"])

    _add_tenant_column("order_lines", "orders", "order_id")
    with op.batch_alter_table("order_lines", recreate="auto") as batch:
        batch.alter_column("company_id", existing_type=sa.Integer(), nullable=False)
        batch.create_unique_constraint("uq_order_lines_id_company_id", ["id", "company_id"])
        batch.create_unique_constraint("uq_order_line_number", ["order_id", "line_number"])
        _tenant_fk(batch, "order_lines", "order_id", "orders", "fk_order_line_order_company", "CASCADE")
        _tenant_fk(batch, "order_lines", "matched_product_id", "products", "fk_order_line_product_company")
        _tenant_fk(batch, "order_lines", "matched_packaging_id", "packagings", "fk_order_line_packaging_company")
    op.create_index("ix_order_lines_company_id", "order_lines", ["company_id"])

    _add_tenant_column("customer_product_aliases", "customers", "customer_id")
    with op.batch_alter_table("customer_product_aliases", recreate="auto") as batch:
        batch.alter_column("company_id", existing_type=sa.Integer(), nullable=False)
        _tenant_fk(batch, "customer_product_aliases", "customer_id", "customers", "fk_customer_alias_customer_company", "CASCADE")
        _tenant_fk(batch, "customer_product_aliases", "product_id", "products", "fk_customer_alias_product_company")
    op.create_index("ix_customer_product_aliases_company_id", "customer_product_aliases", ["company_id"])

    _add_tenant_column("match_candidates", "order_lines", "order_line_id")
    with op.batch_alter_table("match_candidates", recreate="auto") as batch:
        batch.alter_column("company_id", existing_type=sa.Integer(), nullable=False)
        _tenant_fk(batch, "match_candidates", "order_line_id", "order_lines", "fk_match_candidate_line_company", "CASCADE")
        _tenant_fk(batch, "match_candidates", "product_id", "products", "fk_match_candidate_product_company")
    op.create_index("ix_match_candidates_company_id", "match_candidates", ["company_id"])

    _add_tenant_column("human_corrections", "customers", "customer_id")
    with op.batch_alter_table("human_corrections", recreate="auto") as batch:
        batch.alter_column("company_id", existing_type=sa.Integer(), nullable=False)
        _tenant_fk(batch, "human_corrections", "customer_id", "customers", "fk_correction_customer_company")
        _tenant_fk(batch, "human_corrections", "order_id", "orders", "fk_correction_order_company")
        _tenant_fk(batch, "human_corrections", "order_line_id", "order_lines", "fk_correction_line_company")
        _tenant_fk(batch, "human_corrections", "suggested_product_id", "products", "fk_correction_suggested_company")
        _tenant_fk(batch, "human_corrections", "correct_product_id", "products", "fk_correction_correct_company")
    op.create_index("ix_human_corrections_company_id", "human_corrections", ["company_id"])

    _add_tenant_column("export_records", "orders", "order_id")
    with op.batch_alter_table("export_records", recreate="auto") as batch:
        batch.alter_column("company_id", existing_type=sa.Integer(), nullable=False)
        _tenant_fk(batch, "export_records", "order_id", "orders", "fk_export_record_order_company", "CASCADE")
        _tenant_fk(batch, "export_records", "export_profile_id", "export_profiles", "fk_export_record_profile_company")
    op.create_index("ix_export_records_company_id", "export_records", ["company_id"])

    if sqlite:
        bind.exec_driver_sql("PRAGMA foreign_keys=ON")
        violations = bind.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError(f"Tenant migration introduced SQLite foreign-key violations: {violations[:3]}")


def downgrade() -> None:
    bind = op.get_bind()
    sqlite = bind.dialect.name == "sqlite"
    if sqlite:
        bind.exec_driver_sql("PRAGMA foreign_keys=OFF")

    op.drop_index("ix_export_records_company_id", table_name="export_records")
    with op.batch_alter_table("export_records", recreate="auto") as batch:
        batch.drop_constraint("fk_export_record_profile_company", type_="foreignkey")
        batch.drop_constraint("fk_export_record_order_company", type_="foreignkey")
        batch.drop_column("company_id")

    op.drop_index("ix_human_corrections_company_id", table_name="human_corrections")
    with op.batch_alter_table("human_corrections", recreate="auto") as batch:
        for name in ("fk_correction_correct_company", "fk_correction_suggested_company", "fk_correction_line_company", "fk_correction_order_company", "fk_correction_customer_company"):
            batch.drop_constraint(name, type_="foreignkey")
        batch.drop_column("company_id")

    op.drop_index("ix_match_candidates_company_id", table_name="match_candidates")
    with op.batch_alter_table("match_candidates", recreate="auto") as batch:
        batch.drop_constraint("fk_match_candidate_product_company", type_="foreignkey")
        batch.drop_constraint("fk_match_candidate_line_company", type_="foreignkey")
        batch.drop_column("company_id")

    op.drop_index("ix_customer_product_aliases_company_id", table_name="customer_product_aliases")
    with op.batch_alter_table("customer_product_aliases", recreate="auto") as batch:
        batch.drop_constraint("fk_customer_alias_product_company", type_="foreignkey")
        batch.drop_constraint("fk_customer_alias_customer_company", type_="foreignkey")
        batch.drop_column("company_id")

    op.drop_index("ix_order_lines_company_id", table_name="order_lines")
    with op.batch_alter_table("order_lines", recreate="auto") as batch:
        batch.drop_constraint("fk_order_line_packaging_company", type_="foreignkey")
        batch.drop_constraint("fk_order_line_product_company", type_="foreignkey")
        batch.drop_constraint("fk_order_line_order_company", type_="foreignkey")
        batch.drop_constraint("uq_order_lines_id_company_id", type_="unique")
        batch.drop_constraint("uq_order_line_number", type_="unique")
        batch.drop_column("company_id")

    op.drop_index("ix_packagings_company_id", table_name="packagings")
    with op.batch_alter_table("packagings", recreate="auto") as batch:
        batch.drop_constraint("fk_packaging_product_company", type_="foreignkey")
        batch.drop_constraint("uq_packagings_id_company_id", type_="unique")
        batch.drop_column("company_id")

    with op.batch_alter_table("orders", recreate="auto") as batch:
        batch.drop_constraint("fk_order_export_profile_company", type_="foreignkey")
        batch.drop_constraint("uq_orders_id_company_id", type_="unique")
    with op.batch_alter_table("export_profiles", recreate="auto") as batch:
        batch.drop_constraint("uq_export_profiles_id_company_id", type_="unique")

    if sqlite:
        bind.exec_driver_sql("PRAGMA foreign_keys=ON")
        violations = bind.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError(f"Tenant downgrade introduced SQLite foreign-key violations: {violations[:3]}")
