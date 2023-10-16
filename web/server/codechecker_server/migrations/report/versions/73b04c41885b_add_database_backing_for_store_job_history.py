"""Add database backing for 'store' job history

Revision ID: 73b04c41885b
Revises: 9d956a0fae8d
Create Date: 2023-09-21 14:24:27.395597

"""

# revision identifiers, used by Alembic.
revision = '73b04c41885b'
down_revision = '9d956a0fae8d'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.create_table("action_history",
    sa.Column("token", sa.String(), nullable=False),
    sa.Column("kind", sa.Enum("store", name="kind"), nullable=False),
    sa.Column("status", sa.Enum("ongoing", "successful", "failed", name="status"), nullable=True),
    sa.Column("run_name", sa.String(), nullable=False),
    sa.Column("username", sa.String(), nullable=True),
    sa.Column("started_at", sa.DateTime(), nullable=False),
    sa.Column("finished_at", sa.DateTime(), nullable=True),
    sa.Column("comment", sa.String(), nullable=True),
    sa.PrimaryKeyConstraint("token", name=op.f("pk_action_history"))
    )


def downgrade():
   op.drop_table("action_history")
