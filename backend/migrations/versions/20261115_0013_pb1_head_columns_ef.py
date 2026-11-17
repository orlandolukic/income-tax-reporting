"""PB-1 Poreski bilans head rows without columns E and F

User's decision (2026-11-15): the head rows (title / company / Klasa 5, Klasa 6 totals) of the
Poreski bilans tab end with Klasa 6; columns E and F of rows 1-3 are removed with their values.
E1 (4,874,508) and F1 (=E1*2) were used by nothing; E3 / F3 were where Klasa 5 / 6 were typed in
(Klasa 5 = E3 + J15, Klasa 6 = F3 + J19, J15 = 0 and J19 empty): Klasa 5 / 6 (C3 / D3) are now
amounts entered directly per company, with the same values (app.pb1_workbook / app.pb1_formulas).

Removes those cells from the imported PB-1 snapshot (pb1_source_cell of the 'poreski-bilans'
sheets) and any stored edit of them (none on 2026-11-15). Irreversible: the downgrade refuses;
the values are in the workbook.

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-15
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0013"
down_revision: Union[str, Sequence[str], None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

WHERE = "tab = 'poreski-bilans' AND row IN (1, 2, 3) AND col IN ('E', 'F')"


def upgrade() -> None:
    op.execute(f"DELETE FROM pb1_source_cell WHERE {WHERE}")
    op.execute(f"DELETE FROM pb1_company_edit WHERE {WHERE}")
    op.execute(f"DELETE FROM pb1_template_edit WHERE {WHERE}")


def downgrade() -> None:
    raise RuntimeError("Downgrade refused: the PB-1 head cells E1-F3 were removed (they are in the workbook)")
