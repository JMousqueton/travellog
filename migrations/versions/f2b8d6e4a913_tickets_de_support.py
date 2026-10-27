"""Tickets de support

Revision ID: f2b8d6e4a913
Revises: d4f81b2e6a17
Create Date: 2026-10-27 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f2b8d6e4a913'
down_revision = 'd4f81b2e6a17'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'tickets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('subject', sa.String(length=200), nullable=False),
        sa.Column('status', sa.String(length=10), server_default='open', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('open', 'answered', 'closed')", name='ticket_status_valid'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('tickets', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_tickets_user_id'), ['user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_tickets_status'), ['status'], unique=False)

    op.create_table(
        'ticket_messages',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('ticket_id', sa.Integer(), nullable=False),
        sa.Column('author_id', sa.Integer(), nullable=True),
        sa.Column('from_staff', sa.Boolean(), server_default='0', nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['author_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['ticket_id'], ['tickets.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('ticket_messages', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_ticket_messages_ticket_id'), ['ticket_id'], unique=False)


def downgrade():
    with op.batch_alter_table('ticket_messages', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_ticket_messages_ticket_id'))
    op.drop_table('ticket_messages')
    with op.batch_alter_table('tickets', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_tickets_status'))
        batch_op.drop_index(batch_op.f('ix_tickets_user_id'))
    op.drop_table('tickets')
