"""Cache de géocodage : langue sur 10 caractères (les vols y sont rangés sous « flight »)

Revision ID: c6d2f8a4e913
Revises: a3c9e1f7b204
Create Date: 2026-10-28 17:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c6d2f8a4e913'
down_revision = 'a3c9e1f7b204'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column('geocode_cache', 'lang', existing_type=sa.String(length=5), type_=sa.String(length=10),
                    existing_nullable=False)


def downgrade():
    op.execute("DELETE FROM geocode_cache WHERE length(lang) > 5")  # simple cache, recalculé à la demande
    op.alter_column('geocode_cache', 'lang', existing_type=sa.String(length=10), type_=sa.String(length=5),
                    existing_nullable=False)
