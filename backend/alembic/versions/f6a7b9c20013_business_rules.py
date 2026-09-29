"""Store company order policy and explicit export profile rules.

Existing companies/profiles receive compatibility values. New companies use
neutral model defaults and profiles use neutral export defaults.

Revision ID: f6a7b9c20013
Revises: e5a7b9c20012
"""
from alembic import op
import sqlalchemy as sa

revision = "f6a7b9c20013"
down_revision = "e5a7b9c20012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "company_business_settings",
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("bonus_enabled", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("bonus_expression_mode", sa.String(24), nullable=False, server_default="disabled"),
        sa.Column("unitless_order_behavior", sa.String(32), nullable=False, server_default="require_review"),
        sa.Column("allow_packaging_conversion", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("learn_unit_preferences", sa.Boolean(), nullable=False, server_default="0"),
    )
    op.execute(sa.text("""INSERT INTO company_business_settings
        (company_id, bonus_enabled, bonus_expression_mode, unitless_order_behavior,
         allow_packaging_conversion, learn_unit_preferences)
        SELECT id, 1, 'paid_plus_bonus', 'learned_product_preference', 1, 1 FROM companies"""))
    with op.batch_alter_table("export_profiles") as batch:
        batch.add_column(sa.Column("bonus_separate_row", sa.Boolean(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("bonus_marker", sa.String(20), nullable=True))
        batch.add_column(sa.Column("quantity_output_unit", sa.String(20), nullable=False, server_default="source"))
        batch.add_column(sa.Column("convert_case_using_pieces_per_case", sa.Boolean(), nullable=False, server_default="0"))
    op.execute(sa.text("""UPDATE export_profiles SET include_header=0, bonus_separate_row=1,
        bonus_marker='Α', quantity_output_unit='piece',
        convert_case_using_pieces_per_case=1 WHERE format='order_sheet'"""))


def downgrade() -> None:
    with op.batch_alter_table("export_profiles") as batch:
        batch.drop_column("convert_case_using_pieces_per_case")
        batch.drop_column("quantity_output_unit")
        batch.drop_column("bonus_marker")
        batch.drop_column("bonus_separate_row")
    op.drop_table("company_business_settings")
