"""model release lifecycle

Revision ID: 6adf134b3ded
Revises: 4270b70b67a6
Create Date: 2026-09-06 19:59:17.017209

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6adf134b3ded'
down_revision: Union[str, Sequence[str], None] = '4270b70b67a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'model_releases',
        sa.Column('release_id', sa.String(), nullable=False),
        sa.Column('model_name', sa.String(), nullable=False),
        sa.Column('checkpoint_id', sa.String(), nullable=False),
        sa.Column('config_hash', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('previous_release_id', sa.String(), nullable=True),
        sa.Column('gate_passed', sa.Boolean(), nullable=True),
        sa.Column('gate_reason_codes', sa.JSON(), nullable=False),
        sa.Column('approved_by', sa.String(), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('activated_by', sa.String(), nullable=True),
        sa.Column('activated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('rolled_back_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status in ('CANDIDATE', 'ACTIVE', 'SUPERSEDED', 'ROLLED_BACK')", name='ck_model_release_status'
        ),
        sa.ForeignKeyConstraint(['previous_release_id'], ['model_releases.release_id']),
        sa.PrimaryKeyConstraint('release_id'),
    )
    op.create_table(
        'model_release_audit_events',
        sa.Column('event_id', sa.String(), nullable=False),
        sa.Column('release_id', sa.String(), nullable=False),
        sa.Column('event_type', sa.String(), nullable=False),
        sa.Column('actor', sa.String(), nullable=True),
        sa.Column('idempotency_key', sa.String(), nullable=True),
        sa.Column('detail', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['release_id'], ['model_releases.release_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('event_id'),
    )
    op.create_index(
        op.f('ix_model_release_audit_events_idempotency_key'),
        'model_release_audit_events',
        ['idempotency_key'],
        unique=False,
    )
    op.create_index(
        op.f('ix_model_release_audit_events_release_id'), 'model_release_audit_events', ['release_id'], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_model_release_audit_events_release_id'), table_name='model_release_audit_events')
    op.drop_index(op.f('ix_model_release_audit_events_idempotency_key'), table_name='model_release_audit_events')
    op.drop_table('model_release_audit_events')
    op.drop_table('model_releases')
