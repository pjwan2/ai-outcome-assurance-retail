"""evaluation and release enterprise fields

Revision ID: 3c334903d695
Revises: d90769dacba0
Create Date: 2026-08-24 20:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3c334903d695'
down_revision: Union[str, Sequence[str], None] = 'd90769dacba0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('evaluation_runs', sa.Column('code_version', sa.String(), nullable=True))
    # server_default so ADD COLUMN NOT NULL succeeds against existing rows
    # (SQLite requires a default for a NOT NULL column added to a non-empty
    # table); matches EvaluationRunORM.environment's Python-side default.
    op.add_column(
        'evaluation_runs', sa.Column('environment', sa.String(), nullable=False, server_default='dev')
    )
    op.add_column('evaluation_runs', sa.Column('provider_versions', sa.JSON(), nullable=True))
    op.add_column('evaluation_runs', sa.Column('per_agent_slice', sa.JSON(), nullable=True))
    op.add_column('evaluation_runs', sa.Column('baseline_evaluation_id', sa.String(), nullable=True))
    op.add_column('release_records', sa.Column('approved_by', sa.String(), nullable=True))
    op.add_column('release_records', sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('release_records', sa.Column('approval_notes', sa.Text(), nullable=True))
    op.add_column('release_records', sa.Column('rollback_of', sa.String(), nullable=True))
    op.add_column(
        'release_records', sa.Column('agent_definition_ids', sa.JSON(), nullable=False, server_default='[]')
    )
    # SQLite has no ALTER TABLE ADD CONSTRAINT — batch mode recreates the
    # table (copy-and-move) to add these two self-referencing foreign keys.
    with op.batch_alter_table('evaluation_runs') as batch_op:
        batch_op.create_foreign_key(
            'fk_evaluation_runs_baseline_evaluation_id',
            'evaluation_runs',
            ['baseline_evaluation_id'],
            ['evaluation_id'],
        )
    with op.batch_alter_table('release_records') as batch_op:
        batch_op.create_foreign_key(
            'fk_release_records_rollback_of', 'release_records', ['rollback_of'], ['release_id']
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('release_records') as batch_op:
        batch_op.drop_constraint('fk_release_records_rollback_of', type_='foreignkey')
    with op.batch_alter_table('evaluation_runs') as batch_op:
        batch_op.drop_constraint('fk_evaluation_runs_baseline_evaluation_id', type_='foreignkey')
    op.drop_column('release_records', 'agent_definition_ids')
    op.drop_column('release_records', 'rollback_of')
    op.drop_column('release_records', 'approval_notes')
    op.drop_column('release_records', 'approved_at')
    op.drop_column('release_records', 'approved_by')
    op.drop_column('evaluation_runs', 'baseline_evaluation_id')
    op.drop_column('evaluation_runs', 'per_agent_slice')
    op.drop_column('evaluation_runs', 'provider_versions')
    op.drop_column('evaluation_runs', 'environment')
    op.drop_column('evaluation_runs', 'code_version')
