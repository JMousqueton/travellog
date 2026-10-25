"""Compagnie, numéro et appareil (vols et trains)

Revision ID: c7e2a91d4f30
Revises: 3645adc57155
Create Date: 2026-10-25 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c7e2a91d4f30'
down_revision = '3645adc57155'
branch_labels = None
depends_on = None


def upgrade():
    # op.add_column plutôt que batch_alter_table : SQLite ajoute la colonne sans recréer la table `trips`
    # (une reconstruction viderait trip_tags par ON DELETE CASCADE).
    op.add_column('trips', sa.Column('carrier', sa.String(length=80), nullable=True))
    op.add_column('trips', sa.Column('service_number', sa.String(length=40), nullable=True))
    op.add_column('trips', sa.Column('vehicle', sa.String(length=80), nullable=True))


def downgrade():
    with op.batch_alter_table('trips', schema=None) as batch_op:
        batch_op.drop_column('vehicle')
        batch_op.drop_column('service_number')
        batch_op.drop_column('carrier')
