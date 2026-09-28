"""Store request fingerprint for idempotency conflict detection.

Revision ID: a91f2a4d8b70
Revises: 73e685e9111b
"""

from alembic import op
import sqlalchemy as sa

revision = "a91f2a4d8b70"
down_revision = "73e685e9111b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("idempotency_fingerprint", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "idempotency_fingerprint")
