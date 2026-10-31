"""Photos : métadonnées EXIF et GPS relevées à l'envoi

Revision ID: a7e3d9c51f28
Revises: c6d2f8a4e913
Create Date: 2026-10-31 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a7e3d9c51f28'
down_revision = 'c6d2f8a4e913'
branch_labels = None
depends_on = None


def upgrade():
    # ADD COLUMN nullable seulement : les photos existantes n'ont plus leurs métadonnées (exif = NULL).
    op.add_column('photos', sa.Column('exif', sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table('photos', schema=None) as batch_op:
        batch_op.drop_column('exif')
