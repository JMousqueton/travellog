"""Expiration et dernière consultation des liens de partage

Revision ID: e5a7c3f91b20
Revises: d1b4f12bf24d
Create Date: 2026-10-25 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e5a7c3f91b20'
down_revision = 'd1b4f12bf24d'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('share_links', schema=None) as batch_op:
        batch_op.add_column(sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True))


def downgrade():
    with op.batch_alter_table('share_links', schema=None) as batch_op:
        batch_op.drop_column('last_used_at')
        batch_op.drop_column('expires_at')
