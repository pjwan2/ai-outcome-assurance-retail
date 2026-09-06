"""guardrail reports and relevance scoring

Revision ID: 4270b70b67a6
Revises: 3c334903d695
Create Date: 2026-09-06 14:31:18.183435

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4270b70b67a6'
down_revision: Union[str, Sequence[str], None] = '3c334903d695'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'guardrail_reports',
        sa.Column('report_id', sa.String(), nullable=False),
        sa.Column('case_id', sa.String(), nullable=False),
        sa.Column('input_findings', sa.JSON(), nullable=False),
        sa.Column('relevance_scores', sa.JSON(), nullable=False),
        sa.Column('summary_sentences', sa.JSON(), nullable=False),
        sa.Column('ungrounded_count', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['case_id'], ['cases.case_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('report_id'),
    )
    op.create_index(op.f('ix_guardrail_reports_case_id'), 'guardrail_reports', ['case_id'], unique=False)
    op.add_column('evaluation_runs', sa.Column('mean_retrieval_relevance', sa.Float(), nullable=True))
    op.add_column('evaluation_runs', sa.Column('groundedness_pass_rate', sa.Float(), nullable=True))
    op.add_column('evaluation_runs', sa.Column('pii_redaction_count', sa.Integer(), nullable=True))
    op.add_column('evidence', sa.Column('relevance_score', sa.Float(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('evidence', 'relevance_score')
    op.drop_column('evaluation_runs', 'pii_redaction_count')
    op.drop_column('evaluation_runs', 'groundedness_pass_rate')
    op.drop_column('evaluation_runs', 'mean_retrieval_relevance')
    op.drop_index(op.f('ix_guardrail_reports_case_id'), table_name='guardrail_reports')
    op.drop_table('guardrail_reports')
