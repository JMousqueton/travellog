"""Abonnement Premium (Stripe)

Revision ID: e3a9b7c5d214
Revises: a7e3d9c51f28
Create Date: 2026-10-31 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e3a9b7c5d214'
down_revision = 'a7e3d9c51f28'
branch_labels = None
depends_on = None


def upgrade():
    # Colonnes nullables ou avec valeur par défaut : aucun compte existant n'est modifié (pas d'abonnement).
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('stripe_customer_id', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('subscription_status', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('subscription_interval', sa.String(length=10), nullable=True))
        batch_op.add_column(sa.Column('premium_until', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('cancel_at_period_end', sa.Boolean(), server_default='0', nullable=False))
        batch_op.add_column(sa.Column('premium_granted', sa.Boolean(), server_default='0', nullable=False))
        batch_op.create_unique_constraint(batch_op.f('uq_users_stripe_customer_id'), ['stripe_customer_id'])


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f('uq_users_stripe_customer_id'), type_='unique')
        batch_op.drop_column('premium_granted')
        batch_op.drop_column('cancel_at_period_end')
        batch_op.drop_column('premium_until')
        batch_op.drop_column('subscription_interval')
        batch_op.drop_column('subscription_status')
        batch_op.drop_column('stripe_customer_id')
