"""Remember operator-corrected product order units for a company.

Revision ID: e5a7b9c20012
Revises: d4a7b9c20011
"""

from alembic import op
import sqlalchemy as sa

revision = "e5a7b9c20012"
down_revision = "d4a7b9c20011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "company_product_unit_preferences",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("unit", sa.String(50), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("company_id", "product_id", name="uq_company_product_unit_preference"),
        sa.ForeignKeyConstraint(["product_id", "company_id"], ["products.id", "products.company_id"], ondelete="CASCADE", name="fk_unit_preference_product_company"),
    )
    op.create_index("ix_company_product_unit_preferences_company_id", "company_product_unit_preferences", ["company_id"])
    op.create_index("ix_company_product_unit_preferences_product_id", "company_product_unit_preferences", ["product_id"])


def downgrade() -> None:
    op.drop_index("ix_company_product_unit_preferences_product_id", table_name="company_product_unit_preferences")
    op.drop_index("ix_company_product_unit_preferences_company_id", table_name="company_product_unit_preferences")
    op.drop_table("company_product_unit_preferences")
