"""PB-1 Poreski bilans: section rows and the closing rows' hidden columns are not stored

User's decisions (2026-11-16):
- The closing rows (box at the top: V. Poreska osnovica, Poreska osnovica, Porez 15%, Mesecna
  akontacija) keep only what is shown, description and amount: their columns A (the line
  number 69), D, E and G are not part of the form.
- Section rows (bold description: A., I-IX, B.) are read-only and empty: their cells other
  than the line number, the description and the comment column are not part of the form;
  C5 (A. Poslovna dobit i gubitak) is kept for now. C6 (=D3, a copy of Klasa 6) goes with them.

The app leaves those cells out (app.pb1_workbook: Pb1Sheet.dropped, also when importing); this
removes them from the stored snapshots (pb1_source_cell of every 'poreski-bilans' sheet) and any
edit of them (none on 2026-11-16). Irreversible: the downgrade refuses (they are in the workbook).

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-16
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0016"
down_revision: Union[str, Sequence[str], None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Excel row -> columns no longer part of the form (Pb1Sheet.dropped below the head rows).
DROPPED = {
    5: "DEG",
    6: "CDEG",
    10: "CDEG",
    13: "CDEG",
    46: "CDEG",
    61: "CDEG",
    66: "CDEG",
    69: "CDEG",
    71: "CDEG",
    73: "CDEG",
    78: "CDEG",
    85: "ADEG",
    86: "ADEG",
    87: "ADEG",
    88: "ADEG",
}


def upgrade() -> None:
    cells = ", ".join(f"({row}, '{col}')" for row, cols in DROPPED.items() for col in cols)
    where = f"tab = 'poreski-bilans' AND (row, col) IN ({cells})"
    op.execute(f"DELETE FROM pb1_source_cell WHERE {where}")
    op.execute(f"DELETE FROM pb1_company_edit WHERE {where}")
    op.execute(f"DELETE FROM pb1_template_edit WHERE {where}")


def downgrade() -> None:
    raise RuntimeError("Downgrade refused: the dropped PB-1 cells were removed (they are in the workbook)")
