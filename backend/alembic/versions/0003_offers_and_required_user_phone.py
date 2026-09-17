"""Add offers table and make user phone required

Revision ID: 0003_offers_and_phone
Revises: 0002_refresh_tokens
Create Date: 2026-09-17 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0003_offers_and_phone"
down_revision: Union[str, None] = "0002_refresh_tokens"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Backfill any existing NULL phone numbers before enforcing NOT NULL
    op.execute("UPDATE users SET phone = '+971000000000' WHERE phone IS NULL")

    # 2. Alter users.phone to nullable=False
    op.alter_column("users", "phone", existing_type=sa.String(length=50), nullable=False)

    # 3. Create offers table
    op.create_table(
        "offers",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("discount_percentage", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("discount_amount", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("code", sa.String(length=50), nullable=True),
        sa.Column("banner_url", sa.String(length=500), nullable=True),
        sa.Column("product_id", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_offers_code"), "offers", ["code"], unique=True)
    op.create_index(op.f("ix_offers_product_id"), "offers", ["product_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_offers_product_id"), table_name="offers")
    op.drop_index(op.f("ix_offers_code"), table_name="offers")
    op.drop_table("offers")
    op.alter_column("users", "phone", existing_type=sa.String(length=50), nullable=True)
