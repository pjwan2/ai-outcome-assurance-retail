"""model release concurrency constraints

Revision ID: 97cc7a6ba246
Revises: 6adf134b3ded
Create Date: 2026-09-06 22:20:19.822276

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '97cc7a6ba246'
down_revision: Union[str, Sequence[str], None] = '6adf134b3ded'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # SQLite has no ALTER TABLE ADD CONSTRAINT, so this needs batch mode
    # (copy-and-move) to add the unique constraint.
    with op.batch_alter_table('model_release_audit_events') as batch_op:
        batch_op.drop_index(op.f('ix_model_release_audit_events_idempotency_key'))
        batch_op.create_unique_constraint(
            'uq_model_release_audit_events_idempotency_key', ['idempotency_key']
        )
    op.create_index(
        'uq_model_release_single_active',
        'model_releases',
        ['status'],
        unique=True,
        sqlite_where=sa.text("status = 'ACTIVE'"),
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        'uq_model_release_single_active',
        table_name='model_releases',
        sqlite_where=sa.text("status = 'ACTIVE'"),
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )
    with op.batch_alter_table('model_release_audit_events') as batch_op:
        batch_op.drop_constraint('uq_model_release_audit_events_idempotency_key', type_='unique')
        batch_op.create_index(
            op.f('ix_model_release_audit_events_idempotency_key'), ['idempotency_key'], unique=False
        )
