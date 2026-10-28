"""Import de voyages par e-mail : e-mails déjà traités

Revision ID: b9e3f5a1c702
Revises: a7c4e2f8b105
Create Date: 2026-10-27 21:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b9e3f5a1c702'
down_revision = 'a7c4e2f8b105'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'mail_imports',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('message_key', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=10), nullable=False),
        sa.Column('sender', sa.String(length=255), nullable=True),
        sa.Column('subject', sa.String(length=200), nullable=True),
        sa.Column('reason', sa.String(length=255), nullable=True),
        sa.Column('trip_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('ticket_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('imported', 'failed', 'ignored')", name='mail_import_status_valid'),
        sa.ForeignKeyConstraint(['ticket_id'], ['tickets.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('message_key'),
    )
    with op.batch_alter_table('mail_imports', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_mail_imports_user_id'), ['user_id'], unique=False)


def downgrade():
    with op.batch_alter_table('mail_imports', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_mail_imports_user_id'))
    op.drop_table('mail_imports')
