"""Persist indexed normalized product descriptions.

Revision ID: b20e1773d5fc
Revises: a91f2a4d8b70
"""

from alembic import op
import sqlalchemy as sa

from backend.app.core.text_normalizer import normalize_text, stem_phrase

revision = "b20e1773d5fc"
down_revision = "a91f2a4d8b70"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("products", sa.Column("normalized_description", sa.String(500), nullable=False, server_default=""))
    op.add_column("products", sa.Column("stemmed_description", sa.String(500), nullable=False, server_default=""))
    connection = op.get_bind()
    products = sa.table(
        "products", sa.column("id", sa.Integer), sa.column("description", sa.String),
        sa.column("normalized_description", sa.String), sa.column("stemmed_description", sa.String),
    )
    for product_id, description in connection.execute(sa.select(products.c.id, products.c.description)):
        normalized = normalize_text(description)
        connection.execute(
            products.update().where(products.c.id == product_id).values(
                normalized_description=normalized,
                stemmed_description=stem_phrase(normalized),
            )
        )
    op.create_index("ix_products_company_normalized_description", "products", ["company_id", "normalized_description"])
    op.create_index("ix_products_company_stemmed_description", "products", ["company_id", "stemmed_description"])


def downgrade() -> None:
    op.drop_index("ix_products_company_stemmed_description", table_name="products")
    op.drop_index("ix_products_company_normalized_description", table_name="products")
    op.drop_column("products", "stemmed_description")
    op.drop_column("products", "normalized_description")
