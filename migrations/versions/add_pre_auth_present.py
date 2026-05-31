"""add pre_auth_present field

Revision ID: add_pre_auth_001
Revises: 077ed377263a
Create Date: 2026-05-31 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_pre_auth_001'
down_revision: Union[str, None] = '077ed377263a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add pre_auth_present column to claims table
    op.add_column('claims', sa.Column('pre_auth_present', sa.Boolean(), nullable=False, server_default='false'))


def downgrade() -> None:
    # Remove pre_auth_present column from claims table
    op.drop_column('claims', 'pre_auth_present')
