"""Blocage des comptes par un administrateur

Revision ID: a3c9e1f7b204
Revises: e8b2c4d7f105
Create Date: 2026-10-28 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a3c9e1f7b204'
down_revision = 'e8b2c4d7f105'
branch_labels = None
depends_on = None


def upgrade():
    # ADD COLUMN seulement : la table users n'est pas reconstruite (pas de cascade).
    op.add_column('users', sa.Column('is_blocked', sa.Boolean(), nullable=False, server_default='0'))


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('is_blocked')
