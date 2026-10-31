"""Bilan de l'année par e-mail

Revision ID: b4d8e2f6a017
Revises: e3a9b7c5d214
Create Date: 2026-10-31 13:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b4d8e2f6a017'
down_revision = 'e3a9b7c5d214'
branch_labels = None
depends_on = None


def upgrade():
    # Valeur par défaut et colonne nullable : les comptes existants reçoivent le bilan, aucun n'est encore envoyé.
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('review_emails', sa.Boolean(), server_default='1', nullable=False))
        batch_op.add_column(sa.Column('review_email_year', sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('review_email_year')
        batch_op.drop_column('review_emails')
