"""add inviter reimbursement tier

Revision ID: a1b2c3d4e5f6
Revises: 0dfedbea360e
Create Date: 2026-05-12 11:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '0dfedbea360e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 邀请人级报销档位（分）：默认 10000（100 元）；现存邀请人也填默认值
    with op.batch_alter_table('inviters', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'reimbursement_tier_cents',
                sa.Integer(),
                nullable=False,
                server_default='10000',
            )
        )

    # 旧的全局固定金额设置已废弃；幂等清理（不存在也不报错）
    op.execute(
        "DELETE FROM settings WHERE key = 'reimbursement_fixed_amount_cents'"
    )


def downgrade() -> None:
    with op.batch_alter_table('inviters', schema=None) as batch_op:
        batch_op.drop_column('reimbursement_tier_cents')
