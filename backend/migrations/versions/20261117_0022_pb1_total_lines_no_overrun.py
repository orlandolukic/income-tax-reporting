"""PB-1 Poreski bilans: the total lines 57, 59, 62 have no Prekoracenje

User's decision (2026-11-17): Poreska osnovica is the sum of the positive overruns of the form
lines; the total lines 57 (row 70), 59 Oporeziva dobit (74) and 62 Ostatak oporezive dobiti (77)
are not items, so their Prekoracenje (column E) is not part of the form: removed from every
stored snapshot and value (app.pb1_workbook drops it too, Pb1TabSpec.dropped_cells).
Irreversible (the downgrade refuses).

Revision ID: 0022
Revises: 0021
Create Date: 2026-11-17
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0022"
down_revision: Union[str, Sequence[str], None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for table in ("pb1_source_cell", "pb1_company_edit", "pb1_template_edit"):
        op.execute(f"DELETE FROM {table} WHERE tab = 'poreski-bilans' AND col = 'E' AND row IN (70, 74, 77)")


def downgrade() -> None:
    raise RuntimeError("Migration 0022 can't be undone: the removed cells are in the PB-1 workbook (re-import).")
