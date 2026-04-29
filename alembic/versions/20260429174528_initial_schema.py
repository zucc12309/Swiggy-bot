"""initial schema

Revision ID: 20260429174528
Revises:
Create Date: 2026-04-29
"""
from alembic import op
import sqlalchemy as sa

revision = "20260429174528"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("phone", sa.String(), nullable=False, unique=True, index=True),
        sa.Column("telegram_id", sa.String(), nullable=True, unique=True, index=True),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("address", sa.String(), nullable=True),
        sa.Column("latitude", sa.String(), nullable=True),
        sa.Column("longitude", sa.String(), nullable=True),
        sa.Column("payment_method_id", sa.String(), nullable=True),
        sa.Column("reminder_lead_hours", sa.Integer(), default=12),
        sa.Column("max_auto_charge", sa.Integer(), default=200000),
        sa.Column("is_active", sa.Boolean(), default=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )

    op.create_table(
        "schedules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_phone", sa.String(), sa.ForeignKey("users.phone"), nullable=False, index=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("freq_value", sa.Integer(), nullable=False),
        sa.Column("freq_unit", sa.Enum("days", "weeks", "months", name="frequencyunit"), nullable=False),
        sa.Column("anchor_day", sa.String(), nullable=True),
        sa.Column("next_run", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.Enum("active", "paused", "cancelled", name="schedulestatus"), default="active"),
        sa.Column("reminder_enabled", sa.Integer(), default=1),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )

    op.create_table(
        "schedule_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("schedule_id", sa.Integer(), sa.ForeignKey("schedules.id"), nullable=False, index=True),
        sa.Column("item_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False, default=1),
        sa.Column("unit", sa.String(), nullable=True),
    )

    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_phone", sa.String(), nullable=False, index=True),
        sa.Column("type", sa.Enum("food", "grocery", name="ordertype"), nullable=False),
        sa.Column("swiggy_order_id", sa.String(), nullable=True, unique=True),
        sa.Column("razorpay_order_id", sa.String(), nullable=True),
        sa.Column("schedule_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.Enum("pending_payment", "placed", "confirmed", "picked_up",
                                    "delivered", "cancelled", "failed", name="orderstatus"),
                  default="pending_payment"),
        sa.Column("items", sa.JSON(), nullable=False),
        sa.Column("subtotal", sa.Integer(), nullable=False),
        sa.Column("delivery_fee", sa.Integer(), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("restaurant_id", sa.String(), nullable=True),
        sa.Column("restaurant_name", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )

    op.create_table(
        "price_alerts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_phone", sa.String(), nullable=False, index=True),
        sa.Column("product_id", sa.String(), nullable=False),
        sa.Column("product_name", sa.String(), nullable=False),
        sa.Column("target_price", sa.Integer(), nullable=False),
        sa.Column("previous_price", sa.Integer(), nullable=False),
        sa.Column("status", sa.Enum("active", "fired", "snoozed", "deleted", name="pricealertstatus"),
                  default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("fired_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("price_alerts")
    op.drop_table("orders")
    op.drop_table("schedule_items")
    op.drop_table("schedules")
    op.drop_table("users")
    op.execute("DROP TYPE IF EXISTS pricealertstatus")
    op.execute("DROP TYPE IF EXISTS orderstatus")
    op.execute("DROP TYPE IF EXISTS ordertype")
    op.execute("DROP TYPE IF EXISTS schedulestatus")
    op.execute("DROP TYPE IF EXISTS frequencyunit")
