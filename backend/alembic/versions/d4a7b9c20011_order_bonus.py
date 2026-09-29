"""Store grounded order quantity expression and bonus amount.

Revision ID: d4a7b9c20011
Revises: c547ac2e9811
"""

from alembic import op
import sqlalchemy as sa

revision = "d4a7b9c20011"
down_revision = "c547ac2e9811"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("order_lines", sa.Column("quantity_text", sa.String(100), nullable=True))
    op.add_column("order_lines", sa.Column("bonus_quantity", sa.Float(), nullable=False, server_default="0"))
    op.add_column("order_lines", sa.Column("final_bonus_quantity", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("order_lines", "final_bonus_quantity")
    op.drop_column("order_lines", "bonus_quantity")
    op.drop_column("order_lines", "quantity_text")
