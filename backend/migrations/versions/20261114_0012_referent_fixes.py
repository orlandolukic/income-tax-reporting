"""two referent fixes asked by the user

User's decision (2026-11-14):
- "ОТКAZ" (Cyrillic О, Т, К mixed with Latin A, Z, from the workbook) -> "OTKAZ" in Latin;
- "KARARINA" (a typo) -> "KATARINA": merged into the existing referent KATARINA.
Both in the referent lookups and in the import snapshot texts of the REFERENT column (so the
companies are not shown as edited). change_log keeps its history. Downgrade does nothing.

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-14
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: Union[str, Sequence[str], None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# old spelling -> new spelling
FIXES = {
    "ОТКAZ": "OTKAZ",  # ОТКAZ (Cyrillic О Т К + Latin A Z)
    "KARARINA": "KATARINA",
}


def upgrade() -> None:
    conn = op.get_bind()
    for old, new in FIXES.items():
        old_id = conn.execute(sa.text("SELECT id FROM referent WHERE name = :n"), {"n": old}).scalar()
        if old_id is not None:
            new_id = conn.execute(sa.text("SELECT id FROM referent WHERE name = :n"), {"n": new}).scalar()
            if new_id is None:
                conn.execute(sa.text("UPDATE referent SET name = :new WHERE id = :id"), {"new": new, "id": old_id})
            else:
                conn.execute(sa.text("UPDATE company_year SET referent_id = :to WHERE referent_id = :id"), {"to": new_id, "id": old_id})
                conn.execute(sa.text("DELETE FROM referent WHERE id = :id"), {"id": old_id})
        conn.execute(
            sa.text(
                "UPDATE source_cell c SET value_text = :new FROM gfi_column g"
                " WHERE g.source_file_id = c.source_file_id AND g.col = c.col AND g.field = 'referent' AND c.value_text = :old"
            ),
            {"new": new, "old": old},
        )


def downgrade() -> None:
    pass  # the original spelling is in the workbook
