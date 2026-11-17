"""PB-1 Poreski bilans lines 22-25: the limit in Priznati troskovi, the expense in Ostvareni

User's decision (2026-11-17): Prekoracenje = Ostvareni troskovi - Priznati troskovi in every
line. Lines 22-25 (rows 30-33) had them the other way round in the workbook (the actual expense in
C, the limit Klasa 6 x rate in D): their C and D are swapped, in every stored PB-1 snapshot and in
every company value of both reports, so the actual expense is in D (entered) and the limit in C
(computed). Swapping again undoes it (the downgrade does the same).

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-17
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0021"
down_revision: Union[str, Sequence[str], None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ROWS = "30, 31, 32, 33"


def _swap() -> None:
    for table in ("pb1_source_cell", "pb1_company_edit", "pb1_template_edit"):
        where = f"tab = 'poreski-bilans' AND row IN ({ROWS})"
        # Through a temporary column letter: the key (row, col) must stay unique at every step.
        op.execute(f"UPDATE {table} SET col = 'ZC' WHERE {where} AND col = 'C'")
        op.execute(f"UPDATE {table} SET col = 'C' WHERE {where} AND col = 'D'")
        op.execute(f"UPDATE {table} SET col = 'D' WHERE {where} AND col = 'ZC'")


def upgrade() -> None:
    _swap()


def downgrade() -> None:
    _swap()
