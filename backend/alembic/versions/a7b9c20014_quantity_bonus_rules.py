"""Add typed quantity promotions and bonus provenance.

Revision ID: a7b9c20014
Revises: f6a7b9c20013
"""
from alembic import op
import sqlalchemy as sa

revision = "a7b9c20014"
down_revision = "f6a7b9c20013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "company_rules",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rule_type", sa.String(40), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("product_id", sa.Integer(), nullable=True),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("configuration", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["product_id", "company_id"], ["products.id", "products.company_id"], name="fk_company_rule_product_company", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["customer_id", "company_id"], ["customers.id", "customers.company_id"], name="fk_company_rule_customer_company", ondelete="RESTRICT"),
        sa.UniqueConstraint("company_id", "fingerprint", name="uq_company_rule_fingerprint"),
    )
    op.create_index("ix_company_rules_company_id", "company_rules", ["company_id"])
    with op.batch_alter_table("order_lines") as batch:
        batch.add_column(sa.Column("calculated_bonus_quantity", sa.Float(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("promotion_result", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("order_lines") as batch:
        batch.drop_column("promotion_result")
        batch.drop_column("calculated_bonus_quantity")
    op.drop_index("ix_company_rules_company_id", table_name="company_rules")
    op.drop_table("company_rules")
