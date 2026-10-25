"""Liste des trajets sur un lien de partage

Revision ID: d4f81b2e6a17
Revises: c7e2a91d4f30
Create Date: 2026-10-25 15:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd4f81b2e6a17'
down_revision = 'c7e2a91d4f30'
branch_labels = None
depends_on = None


def upgrade():
    # op.add_column : SQLite ajoute la colonne sans recréer la table.
    op.add_column('share_links', sa.Column('show_trips', sa.Boolean(), nullable=False, server_default='0'))


def downgrade():
    with op.batch_alter_table('share_links', schema=None) as batch_op:
        batch_op.drop_column('show_trips')
