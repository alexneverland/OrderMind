"""Link new reviewable revisions without modifying historical orders."""
from alembic import op
import sqlalchemy as sa

revision = "c9d20016"
down_revision = "b8c9d20015"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "order_revisions",
        sa.Column("revision_order_id", sa.Integer(), primary_key=True),
        sa.Column("source_order_id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("request_key", sa.String(36), nullable=False),
        sa.UniqueConstraint("company_id", "request_key", name="uq_revision_request"),
        sa.ForeignKeyConstraint(["source_order_id", "company_id"], ["orders.id", "orders.company_id"], ondelete="RESTRICT", name="fk_revision_source_company"),
        sa.ForeignKeyConstraint(["revision_order_id", "company_id"], ["orders.id", "orders.company_id"], ondelete="CASCADE", name="fk_revision_order_company"),
    )
    op.create_index("ix_order_revisions_source_order_id", "order_revisions", ["source_order_id"])


def downgrade():
    op.drop_table("order_revisions")
