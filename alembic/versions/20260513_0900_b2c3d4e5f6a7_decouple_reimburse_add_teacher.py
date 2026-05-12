"""decouple reimburse from inviter + add reimburse teacher entity

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-13 09:00:00.000000+00:00

变更要点：
1. inviters 表：drop `group_label`、drop `reimbursement_tier_cents`
2. 新建 reimburse_teachers 表（报销老师，独立于邀请人）
3. reimbursement_requests 表：drop `application_id` + add `teacher_id` FK + add `teacher_username_snapshot`
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) 新建 reimburse_teachers
    op.create_table(
        'reimburse_teachers',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('telegram_username', sa.String(length=64), nullable=False),
        sa.Column('display_name', sa.String(length=128), nullable=False),
        sa.Column('group_label', sa.String(length=64), nullable=False),
        sa.Column(
            'reimbursement_tier_cents',
            sa.Integer(),
            nullable=False,
            server_default='10000',
        ),
        sa.Column(
            'is_active',
            sa.Boolean(),
            nullable=False,
            server_default=sa.text('true'),
        ),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('(CURRENT_TIMESTAMP)'),
        ),
    )
    with op.batch_alter_table('reimburse_teachers', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_reimburse_teachers_telegram_username'),
            ['telegram_username'],
            unique=True,
        )

    # 2) inviters 表：drop group_label + drop reimbursement_tier_cents
    with op.batch_alter_table('inviters', schema=None) as batch_op:
        batch_op.drop_column('reimbursement_tier_cents')
        batch_op.drop_column('group_label')

    # 3) reimbursement_requests 表：drop application_id, add teacher_id/teacher_username_snapshot
    with op.batch_alter_table('reimbursement_requests', schema=None) as batch_op:
        # 现有 application_id 字段：drop FK + drop 列
        batch_op.drop_index('ix_reimbursement_requests_application_id')
        batch_op.drop_column('application_id')
        # 新增 teacher_id FK（nullable，删老师后保留快照）
        batch_op.add_column(
            sa.Column('teacher_id', sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column('teacher_username_snapshot', sa.String(length=64), nullable=True)
        )
        batch_op.create_foreign_key(
            'fk_reimbursement_requests_teacher_id',
            'reimburse_teachers',
            ['teacher_id'],
            ['id'],
            ondelete='SET NULL',
        )
        batch_op.create_index(
            'ix_reimbursement_requests_teacher_id',
            ['teacher_id'],
        )


def downgrade() -> None:
    # reimbursement_requests: revert
    with op.batch_alter_table('reimbursement_requests', schema=None) as batch_op:
        batch_op.drop_index('ix_reimbursement_requests_teacher_id')
        batch_op.drop_constraint('fk_reimbursement_requests_teacher_id', type_='foreignkey')
        batch_op.drop_column('teacher_username_snapshot')
        batch_op.drop_column('teacher_id')
        batch_op.add_column(
            sa.Column('application_id', sa.Integer(), nullable=False, server_default='0')
        )
        batch_op.create_index(
            'ix_reimbursement_requests_application_id',
            ['application_id'],
        )

    # inviters: restore dropped columns
    with op.batch_alter_table('inviters', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('group_label', sa.String(length=64), nullable=False, server_default='')
        )
        batch_op.add_column(
            sa.Column(
                'reimbursement_tier_cents',
                sa.Integer(),
                nullable=False,
                server_default='10000',
            )
        )

    # drop reimburse_teachers
    with op.batch_alter_table('reimburse_teachers', schema=None) as batch_op:
        batch_op.drop_index(op.f('ix_reimburse_teachers_telegram_username'))
    op.drop_table('reimburse_teachers')
