"""PB-1 Poreski bilans: "V. Poreska osnovica" is a heading without a value

User's decision (2026-11-17): the first row of the closing rows ("V. Poreska osnovica", row 85)
is the heading of the box, so its value field (C85, an amount field since 2026-11-16, used by
nothing) is not part of the form: removed from every snapshot and value (none was entered).
Irreversible (the downgrade refuses).

Revision ID: 0023
Revises: 0022
Create Date: 2026-11-17
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0023"
down_revision: Union[str, Sequence[str], None] = "0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for table in ("pb1_source_cell", "pb1_company_edit", "pb1_template_edit"):
        op.execute(f"DELETE FROM {table} WHERE tab = 'poreski-bilans' AND row = 85 AND col = 'C'")


def downgrade() -> None:
    raise RuntimeError("Migration 0023 can't be undone: the removed cell is in the PB-1 workbook (re-import).")
