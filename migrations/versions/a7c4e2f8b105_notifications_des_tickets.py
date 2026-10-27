"""Notifications des tickets par e-mail (par ticket pour l'utilisateur, par administrateur)

Revision ID: a7c4e2f8b105
Revises: f2b8d6e4a913
Create Date: 2026-10-27 11:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a7c4e2f8b105'
down_revision = 'f2b8d6e4a913'
branch_labels = None
depends_on = None


def upgrade():
    # ALTER TABLE … ADD COLUMN, sans batch : la table users ne doit pas être reconstruite
    # (sa reconstruction viderait les tables enfants par ON DELETE CASCADE).
    op.add_column('users', sa.Column('ticket_emails', sa.Boolean(), server_default='1', nullable=False))
    op.add_column('tickets', sa.Column('notify', sa.Boolean(), server_default='1', nullable=False))


def downgrade():
    with op.batch_alter_table('tickets', schema=None) as batch_op:
        batch_op.drop_column('notify')
    # SQLite ≥ 3.35 : suppression de colonne sans reconstruire la table users.
    op.execute('ALTER TABLE users DROP COLUMN ticket_emails')
