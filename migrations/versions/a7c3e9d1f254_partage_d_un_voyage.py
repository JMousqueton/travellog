"""Partage d'un trajet ou d'un voyage (avec ses photos) et légende des photos

Revision ID: a7c3e9d1f254
Revises: b4d8e2f6a017
Create Date: 2026-11-01 09:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a7c3e9d1f254'
down_revision = 'b4d8e2f6a017'
branch_labels = None
depends_on = None


def upgrade():
    # Nouvelle table et ADD COLUMN seulement : aucune table existante n'est reconstruite.
    op.create_table(
        'trip_shares',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('trip_id', sa.Integer(), nullable=True),
        sa.Column('journey_id', sa.Integer(), nullable=True),
        sa.Column('token', sa.String(length=64), nullable=False),
        sa.Column('show_exif', sa.Boolean(), server_default='0', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint('(trip_id IS NULL) <> (journey_id IS NULL)', name='trip_share_single_target'),
        sa.ForeignKeyConstraint(['journey_id'], ['journeys.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['trip_id'], ['trips.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_trip_shares_user_id', 'trip_shares', ['user_id'])
    op.create_index('ix_trip_shares_trip_id', 'trip_shares', ['trip_id'])
    op.create_index('ix_trip_shares_journey_id', 'trip_shares', ['journey_id'])
    op.create_index('ix_trip_shares_token', 'trip_shares', ['token'], unique=True)
    op.add_column('photos', sa.Column('description', sa.String(length=200), nullable=True))


def downgrade():
    op.drop_column('photos', 'description')
    op.drop_table('trip_shares')
