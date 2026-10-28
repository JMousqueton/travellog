"""Profil public : nom choisi dans les préférences (/u/<nom>)

Revision ID: e8b2c4d7f105
Revises: d5f1a9c3e702
Create Date: 2026-10-28 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e8b2c4d7f105'
down_revision = 'd5f1a9c3e702'
branch_labels = None
depends_on = None


def upgrade():
    # ADD COLUMN et CREATE INDEX seulement : la table users n'est pas reconstruite (pas de cascade).
    op.add_column('users', sa.Column('public_name', sa.String(length=30), nullable=True))
    op.create_index('ix_users_public_name', 'users', ['public_name'], unique=True)


def downgrade():
    op.drop_index('ix_users_public_name', table_name='users')
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('public_name')
