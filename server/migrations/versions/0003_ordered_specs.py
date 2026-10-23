"""Store workflow specs as json (keeps object key order, so input forms keep the author's field order).

Revision ID: 0003
Revises: 0002
"""

from __future__ import annotations

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE workflow_versions ALTER COLUMN spec TYPE json USING spec::json")


def downgrade() -> None:
    op.execute("ALTER TABLE workflow_versions ALTER COLUMN spec TYPE jsonb USING spec::jsonb")
