"""Add last used date to API tokens.

Revision ID: bf9d67e81cdd
Revises: 294b07809a3f
Create Date: 2026-06-13 10:23:53.925303

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "bf9d67e81cdd"
down_revision = "294b07809a3f"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "api_token",
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade():
    op.drop_column("api_token", "last_used_at")
