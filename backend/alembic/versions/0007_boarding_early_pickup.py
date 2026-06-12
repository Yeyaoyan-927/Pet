"""0007 boarding early pickup requests

提前接回改成「宠主申请 → 店员/店长审核」（V8.4.9）。

Revision ID: 8c1d2e4f6a90
Revises: 21fa05283681
Create Date: 2026-10-21 10:20:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '8c1d2e4f6a90'
down_revision: str | None = '21fa05283681'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'boarding_early_pickup',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('order_id', sa.BigInteger(), nullable=False, comment='寄养订单 ID'),
        sa.Column('user_id', sa.BigInteger(), nullable=False, comment='申请宠主 ID'),
        sa.Column('expect_pickup_date', sa.Date(), nullable=False, comment='期望接回日期'),
        sa.Column('reason', sa.String(length=255), nullable=True, comment='申请原因'),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='pending',
                  comment='pending 待审核 / approved 已通过 / rejected 已驳回'),
        sa.Column('review_note', sa.String(length=255), nullable=True, comment='审核意见'),
        sa.Column('reviewed_by', sa.BigInteger(), nullable=True, comment='审核人'),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True, comment='审核时间'),
        sa.Column('created_at', sa.DateTime(), nullable=False,
                  server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), nullable=False,
                  server_default=sa.text('CURRENT_TIMESTAMP'), onupdate=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        comment='提前接回申请（宠主发起、门店审核）',
    )
    op.create_index('ix_boarding_early_pickup_order_id', 'boarding_early_pickup', ['order_id'])
    op.create_index('ix_boarding_early_pickup_user_id', 'boarding_early_pickup', ['user_id'])
    op.create_index('ix_boarding_early_pickup_status', 'boarding_early_pickup', ['status'])


def downgrade() -> None:
    op.drop_index('ix_boarding_early_pickup_status', table_name='boarding_early_pickup')
    op.drop_index('ix_boarding_early_pickup_user_id', table_name='boarding_early_pickup')
    op.drop_index('ix_boarding_early_pickup_order_id', table_name='boarding_early_pickup')
    op.drop_table('boarding_early_pickup')
