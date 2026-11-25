"""PB-1 Poreski bilans: row 41 removed (not a line of the official form)

User's decision (2026-11-22): the workbook's line 32 "Iskoriscena dugorocna rezervisanja koja
nisu bila priznata kao rashod ..." (Excel row 41) is not in the current official PB1, so the
row is not part of the form (app.pb1_workbook drops it: Pb1TabSpec.dropped_rows); its stored
cells, values, template edits and its global comment are removed. Checked before: the only
stored value was a 0 copied into one final report; the comment came from the workbook.
Irreversible (the downgrade refuses).

Revision ID: 0024
Revises: 0023
Create Date: 2026-11-22
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0024"
down_revision: Union[str, Sequence[str], None] = "0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for table in ("pb1_source_cell", "pb1_company_edit", "pb1_template_edit", "pb1_comment"):
        op.execute(f"DELETE FROM {table} WHERE tab = 'poreski-bilans' AND row = 41")


def downgrade() -> None:
    raise RuntimeError("Migration 0024 can't be undone: the removed row is in the PB-1 workbook (re-import).")
