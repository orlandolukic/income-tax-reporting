"""PB-1 comments global: one set for every year and every company

User's rule (2026-11-15): the PB-1 comments ("Komentar, stopa, konto") are rules for the form's
sections, the same for every company and every year, edited only on the Global Settings page;
there are no company comments any more.

Creates pb1_comment (tab, row: one value per form row, a rate as a number or a text) from the
per-year pb1_comment_default, then drops that table. Every year must have the same comment for
a row (2026-11-15: 2025 and 2026 had the same 19), otherwise the upgrade stops. Company comments
(pb1_company_edit, Poreski bilans column F below the head rows; none on 2026-11-15) are removed.
Irreversible: the downgrade refuses.

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: Union[str, Sequence[str], None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    conflicts = conn.execute(sa.text(
        "SELECT tab, row FROM pb1_comment_default GROUP BY tab, row "
        "HAVING COUNT(DISTINCT (value_number, value_text)) > 1"
    )).all()
    if conflicts:
        raise RuntimeError(f"PB-1 comments differ between years for {conflicts}; decide which to keep first")
    op.create_table(
        "pb1_comment",
        sa.Column("tab", sa.String(length=20), nullable=False),
        sa.Column("row", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("value_number", sa.Numeric(), nullable=True),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("updated_by", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("tab IN ('poreski-bilans', 'uporedo', 'preliminarni')", name=op.f("ck_pb1_comment_tab")),
        sa.CheckConstraint("(value_number IS NULL) <> (value_text IS NULL)", name=op.f("ck_pb1_comment_one_value")),
        sa.PrimaryKeyConstraint("tab", "row", name=op.f("pk_pb1_comment")),
    )
    # The earliest year's row (its source is "workbook"; the values are the same in every year).
    op.execute(
        "INSERT INTO pb1_comment (tab, row, value_number, value_text, source, updated_by, updated_at) "
        "SELECT DISTINCT ON (tab, row) tab, row, value_number, value_text, source, updated_by, updated_at "
        "FROM pb1_comment_default ORDER BY tab, row, year"
    )
    op.execute("DELETE FROM pb1_company_edit WHERE tab = 'poreski-bilans' AND col = 'F' AND row > 3")
    op.drop_table("pb1_comment_default")


def downgrade() -> None:
    raise RuntimeError("Downgrade refused: the PB-1 comments are global now (pb1_comment)")
