"""add policy_id to claims

Revision ID: add_policy_id_to_claims
Revises: add_pre_auth_001
Create Date: 2026-05-31

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_policy_id_to_claims'
down_revision = 'add_pre_auth_001'
branch_labels = None
depends_on = None


def upgrade():
    # Add policy_id column as nullable first
    op.add_column('claims', sa.Column('policy_id', sa.String(length=64), nullable=True))
    
    # Set default value for existing rows
    op.execute("UPDATE claims SET policy_id = 'PLUM_GHI_2024' WHERE policy_id IS NULL")
    
    # Make the column non-nullable
    op.alter_column('claims', 'policy_id', nullable=False)


def downgrade():
    op.drop_column('claims', 'policy_id')
