"""Add 'enabled_checkers' to 'analysis_info'

Revision ID: c3dad71f8e6b
Revises: 9d956a0fae8d
Create Date: 2023-10-20 14:11:48.371981

"""

# revision identifiers, used by Alembic.
revision = 'c3dad71f8e6b'
down_revision = '9d956a0fae8d'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    # Upgrade the contents of the
    op.add_column('analysis_info',
                  sa.Column('enabled_checkers', sa.LargeBinary(),
                            nullable=True))


def downgrade():
    op.drop_column('analysis_info', 'enabled_checkers')
