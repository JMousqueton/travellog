"""Tâches périodiques : historique des exécutions

Revision ID: d5f1a9c3e702
Revises: c3d8a6f2e914
Create Date: 2026-10-28 09:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd5f1a9c3e702'
down_revision = 'c3d8a6f2e914'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'job_runs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=40), nullable=False),
        sa.Column('status', sa.String(length=10), nullable=False),
        sa.Column('summary', sa.String(length=255), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('running', 'ok', 'failed', 'skipped')", name='job_run_status_valid'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_job_runs_name_started_at', 'job_runs', ['name', 'started_at'], unique=False)


def downgrade():
    op.drop_index('ix_job_runs_name_started_at', table_name='job_runs')
    op.drop_table('job_runs')
