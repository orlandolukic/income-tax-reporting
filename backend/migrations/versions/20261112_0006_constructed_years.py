"""constructed years (Migracija) and active company years

A year can be built in the app from the previous year instead of being imported from a
workbook: source_file.origin = 'constructed', based_on_year, no file hash / time.
company_year.active: a constructed year's company that is deselected is hidden, not deleted.

Downgrade fails while a constructed year exists (its source_file has no hash / time), so no
data is dropped silently.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: Union[str, Sequence[str], None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("company_year", sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False))
    op.add_column("source_file", sa.Column("origin", sa.String(length=20), server_default="workbook", nullable=False))
    op.add_column("source_file", sa.Column("based_on_year", sa.SmallInteger(), nullable=True))
    op.create_check_constraint(op.f("ck_source_file_origin"), "source_file", "origin IN ('workbook', 'constructed')")
    op.alter_column("source_file", "sha256", existing_type=postgresql.BYTEA(), nullable=True)
    op.alter_column("source_file", "file_mtime", existing_type=postgresql.TIMESTAMP(timezone=True), nullable=True)


def downgrade() -> None:
    op.alter_column("source_file", "file_mtime", existing_type=postgresql.TIMESTAMP(timezone=True), nullable=False)
    op.alter_column("source_file", "sha256", existing_type=postgresql.BYTEA(), nullable=False)
    op.drop_constraint(op.f("ck_source_file_origin"), "source_file", type_="check")
    op.drop_column("source_file", "based_on_year")
    op.drop_column("source_file", "origin")
    op.drop_column("company_year", "active")
