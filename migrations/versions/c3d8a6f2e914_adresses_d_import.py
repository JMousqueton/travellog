"""Adresses e-mail supplémentaires autorisées pour l'import par e-mail

Revision ID: c3d8a6f2e914
Revises: b9e3f5a1c702
Create Date: 2026-10-27 22:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c3d8a6f2e914'
down_revision = 'b9e3f5a1c702'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'import_addresses',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email'),
    )
    with op.batch_alter_table('import_addresses', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_import_addresses_user_id'), ['user_id'], unique=False)


def downgrade():
    with op.batch_alter_table('import_addresses', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_import_addresses_user_id'))
    op.drop_table('import_addresses')
