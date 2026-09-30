"""Add neutral pallet policy and explicit trusted mass fields.

Revision ID: b8c9d20015
Revises: a7b9c20014
"""
from alembic import op
import sqlalchemy as sa

revision = "b8c9d20015"
down_revision = "a7b9c20014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("export_profiles", sa.Column("palletization", sa.JSON(), nullable=False, server_default='{"enabled": false}'))
    op.add_column("products", sa.Column("kg_per_piece", sa.Numeric(16, 6), nullable=True))
    op.add_column("packagings", sa.Column("kg_per_case", sa.Numeric(16, 6), nullable=True))


def downgrade() -> None:
    op.drop_column("packagings", "kg_per_case")
    op.drop_column("products", "kg_per_piece")
    op.drop_column("export_profiles", "palletization")
